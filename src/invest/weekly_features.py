"""逐期历史漏斗和独立技术信号；只使用该决策之前的成员与行情。"""

import math
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa

from invest.contracts import RESEARCH_BARS, SIGNAL_SCHEMA, DataSnapshot, SignalFrame, SnapshotSpec
from invest.qlib_adapter import calculate_factors
from invest.quality import regular_sessions
from invest.research_data import create_snapshot, identity
from invest.stock_funnel import EXPRESSIONS, RANK_SCHEMA, select_focus
from invest.weekly_selection import WeeklySelection
from invest.weekly_universe import weekly_schedule


def adjusted_snapshot(
    snapshot: DataSnapshot, execution: dict[str, pa.Table], destination: Path
) -> DataSnapshot:
    """向前累计已生效拆股比例；未来拆股不会改写此前特征价格。成交仍使用原价。"""
    splits = {s: {r["date"]: r["split_ratio"] for r in t.to_pylist()} for s, t in execution.items()}
    accumulated: dict[str, Decimal] = {}
    rows = []
    for row in sorted(snapshot.bars.to_pylist(), key=lambda r: (r["date"], r["instrument"])):
        symbol = row["instrument"]
        factor = accumulated.get(symbol, Decimal(1)) * splits[symbol][row["date"]]
        accumulated[symbol] = factor
        rows.append(
            {**row, **{field: row[field] * factor for field in ("open", "high", "low", "close")}}
        )
    return create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        snapshot.universe,
        destination,
        SnapshotSpec(
            snapshot.spec.source,
            f"{snapshot.snapshot_id}:causal_forward_splits_v1",
            "split_adjusted",
            "shares",
            snapshot.spec.universe_basis,
        ),
        allow_exploratory=True,
    )


def weekly_frames(
    raw: DataSnapshot,
    adjusted: DataSnapshot,
    members: pa.Table,
    start: date,
    end: date,
    config: dict[str, Any],
    *,
    allow_missing_members: bool = False,
    blocked_history: dict[str, set[date]] | None = None,
) -> tuple[SignalFrame, dict[date, WeeklySelection], dict[str, pa.Table]]:
    days = raw.calendar["date"].to_pylist()
    if start not in days or end not in days or days.index(start) < 253:
        raise ValueError("Weekly funnel requires 253 sessions before the first execution")
    first = days[days.index(start) - 1]
    factors = calculate_factors(adjusted, EXPRESSIONS, start=first, end=end).table
    lookup: dict[tuple[date, str], dict[str, Any]] = {}
    for row in factors.to_pylist():
        lookup.setdefault((row["date"], row["instrument"]), {})[row["factor"]] = row["value"]
    source = raw.bars.to_pandas(date_as_object=True)
    prices = (
        adjusted.bars.to_pandas(date_as_object=True)
        .pivot(index="date", columns="instrument", values="close")
        .astype(float)
        .sort_index()
    )
    returns = prices.pct_change(fill_method=None)
    raw_prices = source.pivot(index="date", columns="instrument", values="close").astype(float)
    volume = source.pivot(index="date", columns="instrument", values="volume").astype(float)
    liquidity = (raw_prices * volume).rolling(20).mean()
    observed = {(r["date"], r["instrument"]): r["available_at"] for r in raw.bars.to_pylist()}
    calendar = regular_sessions(first, end + timedelta(days=14)).to_pylist()
    closes = {r["date"]: r["close_at"] for r in calendar}
    following = {a["date"]: b["close_at"] for a, b in zip(calendar[:-1], calendar[1:], strict=True)}
    schedule = {r["price_as_of"]: r for r in weekly_schedule(start, end)}
    weekly_members: dict[str, dict[str, dict[str, Any]]] = {}
    for row in members.to_pylist():
        group = weekly_members.setdefault(row["week"], {})
        item = group.setdefault(
            row["instrument"],
            {"symbol": row["symbol"], "funds": [], "membership_as_of": row["membership_as_of"]},
        )
        if item["symbol"] != row["symbol"]:
            raise ValueError("Conflicting security mappings across funds")
        item["funds"].append(row["fund"])
        # 合并行显示最早的实际持仓日期；逐基金日期和原件在成员表中完整保留。
        item["membership_as_of"] = min(item["membership_as_of"], row["membership_as_of"])
    all_instruments = sorted(prices.columns)
    if not {"SPY", "QQQ"} <= set(all_instruments):
        raise ValueError("SPY and QQQ reference execution histories are required")
    declared = {r["instrument"] for r in members.to_pylist()}
    if not declared <= set(all_instruments) and not allow_missing_members:
        raise ValueError("Historical members lack research and execution inputs")
    if allow_missing_members:
        all_instruments = sorted(set(all_instruments) | declared)
        prices = prices.reindex(columns=all_instruments)
        returns = returns.reindex(columns=all_instruments)
        raw_prices = raw_prices.reindex(columns=all_instruments)
        liquidity = liquidity.reindex(columns=all_instruments)
    signal_rows, rank_tables, context_rows = [], [], []
    contexts = {}
    candidates: tuple[str, ...] = ()
    source_week, selection_id = "", ""
    known_candidates: set[str] = set()
    rule_id = identity({"funnel": config, "kind": "weekly_rule_hypothesis_v1"})
    declared_at = {r["instrument"]: r["available_at"] for r in raw.universe.to_pylist()}
    for day in (d for d in days if first <= d <= end):
        cutoff = schedule[day]["decision_at"] if day in schedule else closes[day]
        prefix = days[max(0, days.index(day) - 252) : days.index(day) + 1]
        admitted = {
            s: (declared_at.get(s) is None or declared_at[s] <= cutoff)
            and all(
                (d, s) in observed
                and (observed[d, s] is None or observed[d, s] <= cutoff)
                and (blocked_history is None or d not in blocked_history.get(s, set()))
                for d in prefix
            )
            for s in all_instruments
        }
        stats: dict[str, dict[str, Any]] = {}
        for symbol in all_instruments:
            values = lookup.get((day, symbol), {})
            market = lookup.get((day, "SPY"), {})
            record: dict[str, Any] = {"instrument": symbol, "reason": ""}
            if (
                set(values) != set(EXPRESSIONS)
                or set(market) != set(EXPRESSIONS)
                or any(
                    v is None or not math.isfinite(v) for v in [*values.values(), *market.values()]
                )
                or not admitted[symbol]
                or not admitted["SPY"]
            ):
                record["reason"] = "missing_or_unavailable_features"
            else:
                history = prices.loc[:day, symbol].tail(253)
                record.update(values)
                record.update(
                    close=float(raw_prices.loc[day, symbol]),
                    liquidity=float(liquidity.loc[day, symbol]),
                    volatility=float(values["volatility"] * math.sqrt(252)),
                    drawdown=float(-(history / history.cummax() - 1).min()),
                    excess_126=values["momentum_126"] - market["momentum_126"],
                    excess_252=values["momentum_252"] - market["momentum_252"],
                )
                recent_returns = returns.loc[:day, symbol].tail(252)
                if recent_returns.abs().max() > 0.35 or recent_returns.std() <= 0:
                    record["reason"] = "return_outlier_or_constant_prices"
                elif (
                    record["close"] < config["min_price"]
                    or record["liquidity"] < config["min_dollar_volume"]
                ):
                    record["reason"] = "price_or_liquidity_below_threshold"
                elif (
                    min(record[k] for k in ("trend", "momentum_126", "excess_126", "excess_252"))
                    <= 0
                ):
                    record["reason"] = "trend_or_relative_strength_below_threshold"
            stats[symbol] = record
        if day in schedule:
            source_week = schedule[day]["week"]
            chosen = weekly_members[source_week]
            records = []
            for symbol, member in chosen.items():
                records.append(
                    {
                        **stats[symbol],
                        **member,
                        "instrument": symbol,
                        "price_as_of": day,
                        "trade_eligible": False,
                        "action": "EXCLUDED",
                        "limitations": [],
                    }
                )
            frame = pd.DataFrame(records).reindex(columns=RANK_SCHEMA.names)
            frame = select_focus(frame, returns.loc[:day].tail(126), config)
            frame.loc[frame.stage_one, "action"] = "WATCH"
            frame.loc[frame.focus, "action"] = "FOCUS"
            candidates = tuple(
                frame.loc[frame.focus].sort_values(
                    ["score", "instrument"], ascending=[False, True]
                )["instrument"]
            )
            table = pa.Table.from_pandas(
                frame,
                schema=RANK_SCHEMA.with_metadata(
                    {
                        **raw.metadata(RANK_SCHEMA),
                        b"trade_eligible": b"false",
                        b"selection_status": b"research_hypothesis",
                    }
                ),
                preserve_index=False,
            )
            table = table.append_column("week", pa.array([source_week] * table.num_rows))
            rank_tables.append(table)
            selection_id = identity(
                {"week": source_week, "candidates": candidates, "rule": rule_id}
            )
            known_candidates.update(candidates)
        for rank, symbol in enumerate(all_instruments, 1):
            info = stats[symbol]
            if info["reason"] == "missing_or_unavailable_features":
                continue
            independent = (
                not info["reason"]
                and info["volatility"] <= config["max_volatility"]
                and info["drawdown"] <= config["max_drawdown"]
            )
            signal_rows.append(
                {
                    "date": day,
                    "instrument": symbol,
                    "score": float(independent),
                    "direction": int(independent),
                    "rank": rank,
                    "horizon": 5,
                    "available_at": cutoff,
                    "expires_at": following[day],
                    "pool_id": rule_id,
                }
            )
        pairs: list[tuple[str, str, float | None]] = []
        seen = set()
        for left in candidates:
            for right in sorted(known_candidates - {left}):
                key = tuple(sorted((left, right)))
                if key in seen:
                    continue
                seen.add(key)
                value = float(
                    returns.loc[:day, left].tail(126).corr(returns.loc[:day, right].tail(126))
                )
                pairs.append(
                    (
                        key[0],
                        key[1],
                        value
                        if math.isfinite(value) and admitted[left] and admitted[right]
                        else None,
                    )
                )
        contexts[day] = WeeklySelection(
            candidates,
            "rank_rotation",
            cutoff,
            selection_id,
            day in schedule,
            tuple(pairs),
            config["max_correlation"],
        )
        context_rows.append(
            {
                "date": day,
                "week": source_week,
                "decision_at": cutoff,
                "selection_id": selection_id,
                "rebalance": day in schedule,
                "candidates": list(candidates),
            }
        )
    schema = SIGNAL_SCHEMA.with_metadata(
        {
            **raw.metadata(SIGNAL_SCHEMA),
            b"pool_id": rule_id.encode(),
            b"selection_status": b"research_hypothesis",
            b"trade_eligible": b"false",
            b"price_basis": b"split_adjusted",
            b"feature_snapshot_id": adjusted.snapshot_id.encode(),
        }
    )
    context_schema = pa.schema(
        [
            ("date", pa.date32()),
            ("week", pa.string()),
            ("decision_at", pa.timestamp("us", tz="UTC")),
            ("selection_id", pa.string()),
            ("rebalance", pa.bool_()),
            ("candidates", pa.list_(pa.field("element", pa.string()))),
        ]
    )
    return (
        SignalFrame(pa.Table.from_pylist(signal_rows, schema=schema)),
        contexts,
        {
            "factors": factors,
            "weekly_rankings": pa.concat_tables(rank_tables),
            "weekly_contexts": pa.Table.from_pylist(context_rows, schema=context_schema),
        },
    )
