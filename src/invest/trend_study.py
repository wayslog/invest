"""预先固定的趋势假设研究；复用成交、决策和独立账务，不生成合格因子池。"""

import html
import math
import re
import shutil
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca_research import freeze_execution_evidence
from invest.backtest import simulate_signals
from invest.backtest_config import parse_policy
from invest.backtest_study import SUMMARY_SCHEMA, execution_inputs
from invest.contracts import (
    SIGNAL_SCHEMA,
    AccountSnapshot,
    Quote,
    SignalFrame,
    StrategyState,
    research_schema,
)
from invest.decision_io import decision_contexts
from invest.engine import engine_digest
from invest.evaluation import evaluate, yearly
from invest.market import MONEY
from invest.portfolio_audit import audit_backtest
from invest.qlib_adapter import calculate_factors
from invest.quality import regular_sessions
from invest.quant_report import write_quant_report
from invest.research_artifacts import (
    freeze_engine,
    protect_inputs,
    runtime_versions,
    seal_artifacts,
    verify_artifacts,
)
from invest.research_data import digest, identity, load_snapshot
from invest.stock_funnel import EXPRESSIONS
from invest.strategies import Policy, decide

RUN_SCHEMA = research_schema(
    "trend_study_run",
    [
        (k, pa.string())
        for k in (
            "run_id",
            "status",
            "source",
            "scope",
            "history_status",
            "initial_cash",
            "engine_digest",
            "versions",
            "error",
            "design_sha256",
        )
    ]
    + [
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("account_eligible", pa.bool_()),
        ("limitations", pa.list_(pa.field("element", pa.string()))),
    ],
)


@dataclass(frozen=True)
class TrendConfig:
    design: Path
    snapshot: Path
    benchmark_snapshot: Path
    execution: dict[str, Path]
    benchmark_execution: dict[str, Path]


def load_config(path: Path) -> TrendConfig:
    values = tomllib.loads(path.read_text())
    if set(values) != {
        "design",
        "snapshot",
        "benchmark_snapshot",
        "execution",
        "benchmark_execution",
    }:
        raise ValueError("Invalid trend study input fields")
    for key in ("design", "snapshot", "benchmark_snapshot"):
        values[key] = (path.parent / values[key]).resolve()
    for key in ("execution", "benchmark_execution"):
        values[key] = {
            symbol: (path.parent / name).resolve() for symbol, name in values[key].items()
        }
    return TrendConfig(**values)


def read_design(path: Path) -> tuple[dict[str, Any], Policy]:
    design = tomllib.loads(path.read_text())
    registration = pq.read_table(path.parent / "rule-registration.parquet").to_pylist()
    if (
        len(registration) != 1
        or registration[0]["sha256"] != digest(path)
        or registration[0]["body"] != path.read_bytes()
        or registration[0]["registered_at"] > datetime.now(UTC)
        or registration[0]["strategy_trials"] != 1
        or design["strategy_trials"] != 1
        or design["design"] != "selected_stock_trend_v1"
        or design["history_status"] != "known_history_post_selection"
        or design["account_eligible"] is not False
    ):
        raise ValueError("Trend design must match its prior research registration")
    policy = parse_policy(design["policy"])
    capital = Decimal(design["initial_cash"])
    if (
        not policy.allow_exploratory
        or not design["data_start"] < design["start"] <= design["end"] <= design["known_through"]
        or not capital.is_finite()
        or capital <= policy.commission * 2
        or capital != capital.quantize(Decimal(".000001"))
        or not design["symbols"]
        or len(set(design["symbols"])) != len(design["symbols"])
        or design["benchmark"] in design["symbols"]
        or any(
            not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", symbol)
            for symbol in [*design["symbols"], design["benchmark"]]
        )
        or any(
            type(design[k]) not in {int, float} or not math.isfinite(design[k]) or design[k] <= 0
            for k in ("min_price", "min_dollar_volume", "max_volatility", "max_drawdown")
        )
    ):
        raise ValueError("Invalid trend rule dates, capital, symbols or thresholds")
    return design, policy


def rule_signals(config: TrendConfig) -> tuple[SignalFrame, dict[str, pa.Table], str]:
    """每个决策只使用当日及之前的价格；当前关注分数不作为交易信号。"""
    design, _ = read_design(config.design)
    snapshot, benchmark = load_snapshot(config.snapshot), load_snapshot(config.benchmark_snapshot)
    if (
        set(snapshot.universe["instrument"].to_pylist()) != set(design["symbols"])
        or benchmark.universe["instrument"].to_pylist() != [design["benchmark"]]
        or snapshot.spec.source != benchmark.spec.source
        or snapshot.spec.price_basis != "raw"
        or benchmark.spec.price_basis != "raw"
        or snapshot.spec.currency != "USD"
        or benchmark.spec.currency != "USD"
        or snapshot.calendar["date"].to_pylist() != benchmark.calendar["date"].to_pylist()
    ):
        raise ValueError("Trend stock and benchmark snapshots must have matching raw USD calendars")
    days = snapshot.calendar["date"].to_pylist()
    if (
        days[0] != design["data_start"]
        or days[-1] != design["end"]
        or design["start"] not in days
        or design["end"] not in days
        or days.index(design["start"]) < 253
    ):
        raise ValueError("Trend study requires 253 warmup sessions before the first fill")
    expressions = {**EXPRESSIONS, "liquidity": "Mean($close*$volume,20)"}
    factors = calculate_factors(snapshot, expressions).table
    reference = calculate_factors(benchmark, expressions).table
    lookup: dict[tuple[date, str], dict[str, dict[str, Any]]] = {}
    for row in [*factors.to_pylist(), *reference.to_pylist()]:
        lookup.setdefault((row["date"], row["instrument"]), {})[row["factor"]] = row
    prices = (
        snapshot.bars.to_pandas(date_as_object=True)
        .pivot(index="date", columns="instrument", values="close")
        .astype(float)
        .sort_index()
    )
    calendar = regular_sessions(days[0], design["end"] + timedelta(days=14)).to_pylist()
    closes = {row["date"]: row["close_at"] for row in calendar}
    following = {a["date"]: b["close_at"] for a, b in zip(calendar[:-1], calendar[1:], strict=True)}
    rule_id = identity(
        {
            "design": digest(config.design),
            "stocks": snapshot.snapshot_id,
            "benchmark": benchmark.snapshot_id,
        }
    )
    records, signals = [], []
    first = days[days.index(design["start"]) - 1]
    for day in (d for d in days if first <= d <= design["end"]):
        day_rows = []
        for symbol in sorted(design["symbols"]):
            values, market = (
                lookup.get((day, symbol), {}),
                lookup.get((day, design["benchmark"]), {}),
            )
            if set(values) != set(expressions) or set(market) != set(expressions):
                raise ValueError("Missing trend or benchmark factor observations")
            if not all(
                r["value"] is not None and math.isfinite(r["value"])
                for r in [*values.values(), *market.values()]
            ):
                raise ValueError("Trend indicators must be finite after the complete warmup")
            admitted = all(
                r["available_at"] is None or r["available_at"] <= closes[day]
                for r in [*values.values(), *market.values()]
            )
            history = prices.loc[:day, symbol].tail(253)
            drawdown = float(-(history / history.cummax() - 1).min())
            excess126 = float(values["momentum_126"]["value"] - market["momentum_126"]["value"])
            excess252 = float(values["momentum_252"]["value"] - market["momentum_252"]["value"])
            volatility = float(values["volatility"]["value"] * math.sqrt(252))
            eligible = (
                admitted
                and history.iloc[-1] >= design["min_price"]
                and values["liquidity"]["value"] >= design["min_dollar_volume"]
                and min(
                    values["trend"]["value"], values["momentum_126"]["value"], excess126, excess252
                )
                > 0
                and volatility <= design["max_volatility"]
                and drawdown <= design["max_drawdown"]
            )
            records.append(
                {
                    "date": day,
                    "instrument": symbol,
                    "close": float(history.iloc[-1]),
                    "trend": float(values["trend"]["value"]),
                    "momentum_126": float(values["momentum_126"]["value"]),
                    "momentum_252": float(values["momentum_252"]["value"]),
                    "excess_126": excess126,
                    "excess_252": excess252,
                    "volatility": volatility,
                    "drawdown": drawdown,
                    "liquidity": float(values["liquidity"]["value"]),
                    "entry_eligible": bool(eligible),
                }
            )
            day_rows.append(
                {
                    "date": day,
                    "instrument": symbol,
                    "score": 1.0 if eligible else 0.0,
                    "direction": int(eligible),
                    "horizon": 5,
                    "available_at": closes[day],
                    "expires_at": following[day],
                    "pool_id": rule_id,
                }
            )
        for rank, row in enumerate(
            sorted(day_rows, key=lambda r: (-r["score"], r["instrument"])), 1
        ):
            signals.append({**row, "rank": rank})
    metadata = {
        **snapshot.metadata(SIGNAL_SCHEMA),
        b"pool_id": rule_id.encode(),
        b"signal_kind": b"prespecified_rule",
        b"selection_status": b"research_hypothesis",
        b"trade_eligible": b"false",
    }
    # pool_id 是既有信号契约的定义标识字段；此处不创建或冒充经过挖掘的因子池。
    frame = SignalFrame(pa.Table.from_pylist(signals, schema=SIGNAL_SCHEMA.with_metadata(metadata)))
    schema = pa.schema(
        [("date", pa.date32()), ("instrument", pa.string())]
        + [
            (k, pa.float64())
            for k in (
                "close",
                "trend",
                "momentum_126",
                "momentum_252",
                "excess_126",
                "excess_252",
                "volatility",
                "drawdown",
                "liquidity",
            )
        ]
        + [("entry_eligible", pa.bool_())]
    )
    return (
        frame,
        {
            "factors": factors,
            "benchmark_factors": reference,
            "indicators": pa.Table.from_pylist(records, schema=schema),
        },
        rule_id,
    )


def study_tables(config: TrendConfig) -> dict[str, pa.Table]:
    design, policy = read_design(config.design)
    snapshot, benchmark = load_snapshot(config.snapshot), load_snapshot(config.benchmark_snapshot)
    inputs = execution_inputs(snapshot, config.execution, design["start"], design["end"])
    market_inputs = execution_inputs(
        benchmark, config.benchmark_execution, design["start"], design["end"]
    )
    # 此原价规则的完整指标预热期必须无拆股；不让原价跳变进入动量或风险估计。
    for path in [*config.execution.values(), *config.benchmark_execution.values()]:
        if any(
            r["split_ratio"] != 1
            for r in pq.read_table(path).to_pylist()
            if design["data_start"] <= r["date"] <= design["end"]
        ):
            raise ValueError(
                "Raw trend rule requires a split-free indicator and evaluation interval"
            )
    signals, tables, rule_id = rule_signals(config)
    capital = Decimal(design["initial_cash"])
    rows = signals.table.to_pylist()
    reference = SignalFrame(
        pa.Table.from_pylist(
            [{**r, "score": 1.0, "direction": 1} for r in rows], schema=signals.table.schema
        )
    )
    cash = SignalFrame(
        pa.Table.from_pylist(
            [{**r, "score": 0.0, "direction": 0} for r in rows], schema=signals.table.schema
        )
    )
    market_rows = [
        {**r, "instrument": design["benchmark"], "rank": 1, "score": 1.0, "direction": 1}
        for r in rows
        if r["instrument"] == sorted(design["symbols"])[0]
    ]
    market_signals = SignalFrame(
        pa.Table.from_pylist(
            market_rows,
            schema=SIGNAL_SCHEMA.with_metadata(
                {**(signals.table.schema.metadata or {}), **benchmark.metadata(SIGNAL_SCHEMA)}
            ),
        )
    )
    market_policy = replace(
        policy,
        top_k=1,
        allocation=Decimal(1),
        position_cap=Decimal(1),
        rebalance_sessions=100000,
        stop_loss=Decimal(0),
        trailing_stop=Decimal(0),
        take_profit=Decimal(0),
        max_holding_sessions=0,
        account_drawdown=Decimal(1),
    )
    scenarios = [
        ("strategy", signals, policy, inputs, snapshot),
        ("equal_weight", reference, policy, inputs, snapshot),
        ("cash", cash, policy, inputs, snapshot),
        (
            "double_cost",
            signals,
            replace(policy, commission=policy.commission * 2, slippage_bps=policy.slippage_bps * 2),
            inputs,
            snapshot,
        ),
        ("spy_reference", market_signals, market_policy, market_inputs, benchmark),
    ]
    summaries, costs, portfolios = [], [], {}
    for name, frame, settings, panel, data in scenarios:
        result = simulate_signals(
            panel,
            frame,
            settings,
            design["start"],
            design["end"],
            initial_cash=capital,
            account_id=identity({"rule": rule_id, "scenario": name}),
            universe=data.universe,
            availability=data.bars,
        )
        audit, attribution, cycles = audit_backtest(
            panel, result.portfolio, settings, capital, availability=data.bars
        )
        if "error" in audit["status"].to_pylist():
            raise ValueError("Independent trend ledger audit failed")
        portfolios[name] = result.portfolio
        outcomes = cycles["outcome"].to_pylist()
        multiples = [v for v in cycles["r_multiple"].to_pylist() if v is not None]
        summaries.append(
            {
                "scenario": name,
                **evaluate(result.portfolio, capital, cycles).to_pylist()[0],
                "closed_cycles": len(outcomes),
                "wins": outcomes.count("win"),
                "losses": outcomes.count("loss"),
                "win_rate": outcomes.count("win") / len(outcomes) if outcomes else None,
                "average_r": sum(multiples) / len(multiples) if multiples else None,
            }
        )
        prefix = "" if name == "strategy" else f"{name}_"
        outputs = {
            "signals": frame.table,
            "actions": result.actions,
            "orders": result.portfolio.orders,
            "fills": result.portfolio.trades,
            "equity": result.portfolio.equity,
            "positions": result.portfolio.positions,
            "events": result.portfolio.events,
            "outcomes": result.outcomes,
            "checks": audit,
            "attribution": attribution,
            "round_trips": cycles,
            "decision_contexts": decision_contexts(result.contexts),
            "final_context": decision_contexts(((result.final_account, result.final_state),)),
        }
        tables.update({f"{prefix}{key}": value for key, value in outputs.items()})
        slippage = sum(
            (
                abs(r["price"] - r["base_price"]) * r["quantity"]
                for r in result.portfolio.trades.to_pylist()
            ),
            Decimal(0),
        )
        costs.append(
            {
                "scenario": name,
                "slippage_cost": slippage.quantize(Decimal(".000001")),
                "commission": sum(result.portfolio.trades["commission"].to_pylist(), Decimal(0)),
            }
        )
    tables["metrics"] = pa.Table.from_pylist(summaries, schema=SUMMARY_SCHEMA)
    tables["costs"] = pa.Table.from_pylist(
        costs,
        schema=pa.schema(
            [("scenario", pa.string()), ("slippage_cost", MONEY), ("commission", MONEY)]
        ),
    )
    tables["yearly"] = yearly(portfolios["strategy"], portfolios["equal_weight"], capital)
    quotes = tuple(
        Quote(s, next(r["close"] for r in inputs[s].to_pylist() if r["date"] == design["end"]))
        for s in sorted(inputs)
    )
    account = AccountSnapshot(
        identity({"rule": rule_id, "context": "independent_empty_simulation"}),
        snapshot.snapshot_id,
        snapshot.spec.source,
        design["end"],
        capital,
        capital,
        quotes,
    )
    state = StrategyState(peak_equity=capital)
    tables["current_context"] = decision_contexts(((account, state),))
    actions = decide(signals, account, state, policy).actions
    tables["current_actions"] = actions.replace_schema_metadata(
        {
            **(actions.schema.metadata or {}),
            b"context_kind": b"independent_empty_simulation",
            b"trade_eligible": b"false",
            b"history_status": b"known_history_post_selection",
        }
    )
    return tables


def run_trend_study(config_path: Path, output: Path) -> dict[str, Any]:
    config = load_config(config_path)
    design, _ = read_design(config.design)
    sources = (
        config_path,
        config.design,
        config.design.parent / "rule-registration.parquet",
        config.snapshot,
        config.benchmark_snapshot,
        *config.execution.values(),
        *config.benchmark_execution.values(),
    )
    protect_inputs((output,), sources)
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "run_id": identity(
            {
                "config": digest(config_path),
                "design": digest(config.design),
                "engine": engine_digest(),
                "snapshot": load_snapshot(config.snapshot).snapshot_id,
                "benchmark": load_snapshot(config.benchmark_snapshot).snapshot_id,
                "execution": {k: digest(v) for k, v in config.execution.items()},
                "benchmark_execution": {
                    k: digest(v) for k, v in config.benchmark_execution.items()
                },
            }
        ),
        "status": "registered",
        "source": load_snapshot(config.snapshot).spec.source,
        "scope": "exploratory",
        "history_status": design["history_status"],
        "start": design["start"],
        "end": design["end"],
        "initial_cash": design["initial_cash"],
        "created_at": datetime.now(UTC),
        "engine_digest": engine_digest(),
        "versions": runtime_versions(),
        "account_eligible": False,
        "error": "",
        "design_sha256": digest(config.design),
        "limitations": [
            "known_history_post_selection",
            "prespecified_rule_not_selected_factor_pool",
            "historical_availability_unknown",
            "daily_bar_fill_proxy",
            "pretax_assumed_costs",
            "bounded_corporate_action_evidence",
            "pre_inception_spinoff_excluded",
        ],
    }
    try:
        shutil.copy2(config.design, output / "rule-design.toml")
        shutil.copy2(
            config.design.parent / "rule-registration.parquet", output / "rule-registration.parquet"
        )
        shutil.copy2(config_path, output / "original-config.toml")
        shutil.copytree(config.snapshot, output / "snapshot")
        shutil.copytree(config.benchmark_snapshot, output / "benchmark")
        lines = [
            'design = "rule-design.toml"',
            'snapshot = "snapshot"',
            'benchmark_snapshot = "benchmark"',
        ]
        for field, mapping in (
            ("execution", config.execution),
            ("benchmark_execution", config.benchmark_execution),
        ):
            lines.append(f"\n[{field}]")
            (output / field).mkdir()
            for symbol, path in mapping.items():
                target = output / field / f"{symbol}.parquet"
                shutil.copy2(path, target)
                freeze_execution_evidence(path, target)
                lines.append(f'{symbol} = "{field}/{symbol}.parquet"')
        (output / "config.toml").write_text("\n".join(lines) + "\n")
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "registration.parquet",
            compression="zstd",
        )
        tables = study_tables(load_config(output / "config.toml"))
        for name, table in tables.items():
            pq.write_table(table, output / f"{name}.parquet", compression="zstd")
        if engine_digest() != record["engine_digest"]:
            raise ValueError("Engine changed during trend research")
        record["status"] = "completed"
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "run.parquet",
            compression="zstd",
        )
        write_quant_report(output, "backtest", record)
        write_action_report(output, design, tables["current_actions"])
        freeze_engine(output)
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "run.parquet",
            compression="zstd",
        )
        raise
    finally:
        seal_artifacts(output)
    return {
        "directory": output,
        "status": record["status"],
        "run_id": record["run_id"],
        "trade_eligible": False,
    }


def verify_trend_study(directory: Path) -> dict[str, Any]:
    verify_artifacts(directory)
    record = pq.read_table(directory / "run.parquet").to_pylist()[0]
    if (
        record["status"] != "completed"
        or record["engine_digest"] != engine_digest()
        or record["versions"] != runtime_versions()
    ):
        raise ValueError(
            "Trend replay requires completed results and the frozen engine and dependencies"
        )
    tables = study_tables(load_config(directory / "config.toml"))
    for name, table in tables.items():
        stored = pq.read_table(directory / f"{name}.parquet")
        # Parquet 会把列表元素名 item 规范为 element；数据和顶层来源元数据仍须完全相等。
        if (
            not table.equals(stored, check_metadata=False)
            or table.schema.metadata != stored.schema.metadata
        ):
            raise ValueError(f"Trend replay differs: {name}")
    return {"status": "verified", "tables": len(tables), "run_id": record["run_id"]}


def write_action_report(output: Path, design: dict[str, Any], actions: pa.Table) -> None:
    rows = []
    for row in actions.to_pylist():
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(row[key]))}</td>"
                for key in (
                    "instrument",
                    "action",
                    "quantity",
                    "reference_price",
                    "target_weight",
                    "stop_price",
                    "take_profit_price",
                    "effective_at",
                )
            )
            + "</tr>"
        )
    (
        output / "current.html"
    ).write_text(f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>固定趋势规则与独立空仓模拟</title><style>
body{{font:16px/1.6 system-ui;margin:40px;max-width:1200px}}
td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}
table{{border-collapse:collapse}}</style>
<h1>三股趋势规则：独立 {design["initial_cash"]} USD、空仓</h1>
<p>数据截至 {design["end"]}。这是已知历史、选股后研究；以下是模拟条件动作，不具有券商执行资格。</p>
<p>买入要求：价格高于200日均线、半年收益为正、半年和一年剔除近一月收益均超过SPY，
价格至少{design["min_price"]}美元、20日均成交金额至少{design["min_dollar_volume"]:,.0f}美元，年化波动不超过{design["max_volatility"]:.0%}、253日最大回撤不超过{design["max_drawdown"]:.0%}。</p>
<p>仓位、成本及退出参数见<a href="rule-design.toml">冻结规则</a>。
股数按上一收盘估算，开盘变化会触发现金和仓位预算缩量。止损止盈须按实际含佣金成交均价重算，分红按经济权益调整。
同日触及止损和止盈时先算止损；跳空按开盘成交后扣滑点，不能保证止损价。</p>
<table><thead><tr><th>股票</th><th>模拟动作</th><th>股数</th><th>参考价</th>
<th>目标比例</th><th>参考止损</th><th>参考止盈</th><th>下一会话开盘 UTC</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table>
<p><a href="current_actions.parquet">正式条件动作 Parquet</a>
· <a href="report.html">含成本回测与对账</a></p></html>""")
