"""历史周度成员准入、两种落选策略的连续账户比较和冻结重放。"""

import html
import json
import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca_research import freeze_execution_evidence
from invest.backtest import simulate_signals
from invest.backtest_config import parse_policy
from invest.backtest_study import SUMMARY_SCHEMA, execution_inputs
from invest.contracts import DataSnapshot, SignalFrame, research_schema
from invest.decision_io import decision_contexts
from invest.engine import engine_digest
from invest.evaluation import evaluate
from invest.market import MONEY
from invest.portfolio_audit import audit_backtest
from invest.research_artifacts import (
    freeze_engine,
    protect_inputs,
    runtime_versions,
    seal_artifacts,
    verify_artifacts,
)
from invest.research_data import digest, identity, load_snapshot
from invest.stock_funnel import load_funnel_config
from invest.strategies import Policy
from invest.weekly_features import adjusted_snapshot, weekly_frames
from invest.weekly_universe import membership_coverage, read_membership_catalog

RUN_SCHEMA = research_schema(
    "weekly_study_run",
    [
        *[
            (name, pa.string())
            for name in (
                "run_id",
                "status",
                "history_status",
                "scope",
                "engine_digest",
                "versions",
                "error",
            )
        ],
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("initial_cash", MONEY),
        ("weeks", pa.int64()),
        ("ready_weeks", pa.int64()),
        ("executed_paths", pa.int64()),
        ("synthetic", pa.bool_()),
        ("free_only", pa.bool_()),
        ("trade_eligible", pa.bool_()),
    ],
)


@dataclass(frozen=True)
class WeeklyConfig:
    catalog: Path
    funnel: Path
    start: date
    end: date
    initial_cash: Decimal
    synthetic: bool
    max_membership_age: int
    policy: Policy
    snapshot: Path | None
    execution: dict[str, Path]


def load_config(path: Path) -> WeeklyConfig:
    data = tomllib.loads(path.read_text())
    required = {
        "catalog",
        "funnel",
        "start",
        "end",
        "initial_cash",
        "synthetic",
        "max_membership_age",
        "free_only",
        "history_status",
        "policy",
    }
    if not required <= set(data) or set(data) - required - {"snapshot", "execution"}:
        raise ValueError("Invalid weekly study configuration fields")
    if not isinstance(data["initial_cash"], str):
        raise ValueError("Initial capital must be a decimal string")
    capital = Decimal(data["initial_cash"])
    policy = parse_policy(data["policy"])
    if (
        data["free_only"] is not True
        or data["history_status"] != "known_history"
        or type(data["synthetic"]) is not bool
        or not policy.allow_exploratory
        or type(data["start"]) is not date
        or type(data["end"]) is not date
        or data["end"] >= datetime.now(UTC).date()
        or data["start"] > data["end"]
        or not capital.is_finite()
        or capital <= policy.commission * 2
        or capital != capital.quantize(Decimal(".000001"))
        or type(data["max_membership_age"]) is not int
        or data["max_membership_age"] < 0
        or bool(data.get("snapshot")) != bool(data.get("execution"))
        or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", s) for s in data.get("execution", {}))
    ):
        raise ValueError("Invalid weekly study scope, capital, dates or paths")
    return WeeklyConfig(
        (path.parent / data["catalog"]).resolve(),
        (path.parent / data["funnel"]).resolve(),
        data["start"],
        data["end"],
        capital,
        data["synthetic"],
        data["max_membership_age"],
        policy,
        (path.parent / data["snapshot"]).resolve() if data.get("snapshot") else None,
        {s: (path.parent / p).resolve() for s, p in data.get("execution", {}).items()},
    )


def preflight(config: WeeklyConfig) -> dict[str, pa.Table]:
    coverage, members = membership_coverage(
        read_membership_catalog(config.catalog, synthetic=config.synthetic),
        config.start,
        config.end,
        max_age_sessions=config.max_membership_age,
    )
    return {"membership_coverage": coverage, "weekly_members": members}


def study_tables(config: WeeklyConfig, adjusted: DataSnapshot) -> dict[str, pa.Table]:
    tables = preflight(config)
    if set(tables["membership_coverage"]["status"].to_pylist()) != {"ready"}:
        raise ValueError("Historical membership is incomplete")
    if config.snapshot is None:
        raise ValueError("Research and execution snapshots are required")
    raw = load_snapshot(config.snapshot)
    if raw.spec.price_basis != "raw" or (raw.spec.source == "synthetic") != config.synthetic:
        raise ValueError("Weekly research requires matching raw source scope")
    inputs = execution_inputs(raw, config.execution, config.start, config.end)
    frame, selections, features = weekly_frames(
        raw,
        adjusted,
        tables["weekly_members"],
        config.start,
        config.end,
        load_funnel_config(config.funnel),
    )
    tables.update(features)
    tables["signals"] = frame.table
    scenarios = []
    for mode in ("rank_rotation", "hold_until_exit"):
        for multiple in (1, 2):
            policy = replace(
                config.policy,
                commission=config.policy.commission * multiple,
                slippage_bps=config.policy.slippage_bps * multiple,
            )
            contexts = {d: replace(s, mode=mode) for d, s in selections.items()}
            name = mode + ("_double_cost" if multiple == 2 else "")
            scenarios.append((name, frame, policy, inputs, contexts))
    for symbol in ("SPY", "QQQ"):
        # 参照使用共同原价与企业行动；没有排名退出或择时规则。
        rows = [
            {**r, "score": 1.0, "direction": 1, "rank": 1}
            for r in frame.table.to_pylist()
            if r["instrument"] == symbol
        ]
        reference = SignalFrame(pa.Table.from_pylist(rows, schema=frame.table.schema))
        policy = replace(
            config.policy,
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
        # 周末可得信号仍使用相同决策截点；买入后只持有，不每周重新配仓。
        contexts = {
            d: replace(s, candidates=(symbol,), mode="hold_until_exit", rebalance=False)
            for d, s in selections.items()
        }
        scenarios.append(
            (f"{symbol.lower()}_reference", reference, policy, {symbol: inputs[symbol]}, contexts)
        )
    summaries, costs, quarters = [], [], []
    for name, signals, policy, panel, contexts in scenarios:
        result = simulate_signals(
            panel,
            signals,
            policy,
            config.start,
            config.end,
            initial_cash=config.initial_cash,
            account_id=identity(
                {
                    "snapshot": raw.snapshot_id,
                    "scenario": name,
                    "catalog": digest(config.catalog),
                    "policy": policy.policy_id,
                }
            ),
            universe=raw.universe,
            availability=raw.bars,
            selections=contexts,
        )
        checks, attribution, cycles = audit_backtest(
            panel,
            result.portfolio,
            policy,
            config.initial_cash,
            availability=raw.bars,
            decision_times={d: s.decision_at for d, s in contexts.items()},
        )
        if "error" in checks["status"].to_pylist():
            raise ValueError(f"Independent weekly ledger audit failed: {name}")
        outcomes = cycles["outcome"].to_pylist()
        multiples = [v for v in cycles["r_multiple"].to_pylist() if v is not None]
        summaries.append(
            {
                "scenario": name,
                **evaluate(result.portfolio, config.initial_cash, cycles).to_pylist()[0],
                "closed_cycles": len(outcomes),
                "wins": outcomes.count("win"),
                "losses": outcomes.count("loss"),
                "win_rate": outcomes.count("win") / len(outcomes) if outcomes else None,
                "average_r": sum(multiples) / len(multiples) if multiples else None,
            }
        )
        outputs = {
            "actions": result.actions,
            "orders": result.portfolio.orders,
            "fills": result.portfolio.trades,
            "equity": result.portfolio.equity,
            "positions": result.portfolio.positions,
            "events": result.portfolio.events,
            "outcomes": result.outcomes,
            "checks": checks,
            "attribution": attribution,
            "round_trips": cycles,
            "decision_contexts": decision_contexts(result.contexts),
            "final_context": decision_contexts(((result.final_account, result.final_state),)),
        }
        tables.update({f"{name}_{key}": value for key, value in outputs.items()})
        fills = result.portfolio.trades.to_pylist()
        costs.append(
            {
                "scenario": name,
                "commission": sum((r["commission"] for r in fills), Decimal(0)),
                "slippage_cost": sum(
                    (abs(r["price"] - r["base_price"]) * r["quantity"] for r in fills), Decimal(0)
                ).quantize(Decimal(".000001")),
            }
        )
        previous = config.initial_cash
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in result.portfolio.equity.to_pylist():
            key = f"{row['date'].year}-Q{(row['date'].month - 1) // 3 + 1}"
            groups.setdefault(key, []).append(row)
        for quarter, rows in groups.items():
            final = rows[-1]["equity"]
            quarters.append(
                {
                    "scenario": name,
                    "quarter": quarter,
                    "start": rows[0]["date"],
                    "end": rows[-1]["date"],
                    "starting_equity": previous,
                    "final_equity": final,
                    "return": float(final / previous - 1),
                    "worst_account_drawdown": min(r["drawdown"] for r in rows),
                }
            )
            previous = final
    tables["metrics"] = pa.Table.from_pylist(summaries, schema=SUMMARY_SCHEMA)
    tables["costs"] = pa.Table.from_pylist(
        costs,
        schema=research_schema(
            "weekly_costs",
            [("scenario", pa.string()), ("commission", MONEY), ("slippage_cost", MONEY)],
        ),
    )
    tables["quarterly"] = pa.Table.from_pylist(
        quarters,
        schema=research_schema(
            "continuous_quarters",
            [
                ("scenario", pa.string()),
                ("quarter", pa.string()),
                ("start", pa.date32()),
                ("end", pa.date32()),
                ("starting_equity", MONEY),
                ("final_equity", MONEY),
                ("return", pa.float64()),
                ("worst_account_drawdown", pa.float64()),
            ],
        ),
    )
    return tables


def _freeze_inputs(path: Path, config: WeeklyConfig, output: Path) -> None:
    shutil.copy2(path, output / "original-config.toml")
    shutil.copy2(config.catalog, output / "membership-sources.parquet")
    shutil.copy2(config.funnel, output / "funnel.toml")
    # 按解析后的有效参数生成配置，避免原文引号、缩进或多行字符串遗漏路径冻结。
    lines = [
        'catalog = "membership-sources.parquet"',
        'funnel = "funnel.toml"',
        f"start = {config.start}",
        f"end = {config.end}",
        f"initial_cash = {json.dumps(str(config.initial_cash))}",
        f"synthetic = {str(config.synthetic).lower()}",
        "free_only = true",
        'history_status = "known_history"',
        f"max_membership_age = {config.max_membership_age}",
    ]
    if config.snapshot is not None:
        lines.append('snapshot = "snapshot"')
        shutil.copytree(config.snapshot, output / "snapshot")
        (output / "execution").mkdir()
    lines.append("\n[policy]")
    for key, value in asdict(config.policy).items():
        lines.append(f"{key} = {json.dumps(str(value) if isinstance(value, Decimal) else value)}")
    if config.snapshot is not None:
        lines.append("\n[execution]")
        for symbol, source in config.execution.items():
            target = output / "execution" / f"{symbol}.parquet"
            shutil.copy2(source, target)
            freeze_execution_evidence(source, target)
            lines.append(f'{symbol} = "execution/{symbol}.parquet"')
    (output / "config.toml").write_text("\n".join(lines) + "\n")


def run_weekly_study(path: Path, output: Path) -> dict[str, Any]:
    config = load_config(path)
    sources = (path, config.catalog, config.funnel, *config.execution.values())
    if config.snapshot is not None:
        sources += (config.snapshot,)
    protect_inputs((output,), sources)
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "run_id": identity(
            {
                "config": digest(path),
                "catalog": digest(config.catalog),
                "funnel": digest(config.funnel),
                "engine": engine_digest(),
                "snapshot": load_snapshot(config.snapshot).snapshot_id if config.snapshot else None,
                "execution": {s: digest(p) for s, p in config.execution.items()},
            }
        ),
        "status": "registered",
        "history_status": "known_history",
        "scope": "exploratory",
        "start": config.start,
        "end": config.end,
        "initial_cash": config.initial_cash,
        "engine_digest": engine_digest(),
        "versions": runtime_versions(),
        "error": "",
        "created_at": datetime.now(UTC),
        "synthetic": config.synthetic,
        "free_only": True,
        "trade_eligible": False,
        "weeks": 0,
        "ready_weeks": 0,
        "executed_paths": 0,
    }
    try:
        _freeze_inputs(path, config, output)
        frozen = load_config(output / "config.toml")
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "registration.parquet",
            compression="zstd",
        )
        tables = preflight(frozen)
        groups: dict[str, list[str]] = {}
        for row in tables["membership_coverage"].to_pylist():
            groups.setdefault(row["week"], []).append(row["status"])
        record.update(
            weeks=len(groups), ready_weeks=sum(v == ["ready", "ready"] for v in groups.values())
        )
        if record["ready_weeks"] != record["weeks"]:
            record.update(status="blocked", error="historical_membership_unavailable")
        elif frozen.snapshot is None:
            record.update(status="blocked", error="research_execution_inputs_missing")
        else:
            raw = load_snapshot(frozen.snapshot)
            if (
                raw.spec.price_basis != "raw"
                or (raw.spec.source == "synthetic") != frozen.synthetic
            ):
                raise ValueError("Weekly research requires matching raw source scope")
            days = raw.calendar["date"].to_pylist()
            full = execution_inputs(raw, frozen.execution, days[1], frozen.end)
            # 不支持的公司行动由既有准入拒绝；缺历史/退市价格不能删除标的或填平收益。
            if any(t["date"].to_pylist() != days for t in full.values()):
                raise ValueError(
                    "Incomplete execution histories require lifecycle handling before replay"
                )
            adjusted = adjusted_snapshot(raw, full, output / "features")
            tables = study_tables(frozen, adjusted)
            record.update(status="completed", executed_paths=6)
        for name, table in tables.items():
            pq.write_table(table, output / f"{name}.parquet", compression="zstd")
        if engine_digest() != record["engine_digest"]:
            raise ValueError("Engine changed during weekly research")
        freeze_engine(output)
        status = "合成行为验证" if record["synthetic"] else "真实历史回测"
        summary = (
            f"{status}：{record['status']}。区间 {config.start} 至 {config.end}；"
            f"完整历史成员 {record['ready_weeks']}/{record['weeks']} 周；"
            f"完成账户路径 {record['executed_paths']}。原因：{record['error'] or '无'}。"
        )
        details = (
            "固定规则、历史逐期重放；季度表沿用连续账户，不是未经查看的样本外验证。"
            "FOCUS 和动作均不可直接下单。"
        )
        (output / "report.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>周度动态回测</title>'
            '<main style="max-width:900px;margin:60px auto;font:18px/1.8 system-ui">'
            "<h1>周度动态回测</h1>"
            f"<p>{html.escape(summary)}</p><p>{details}</p></main>"
        )
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "run.parquet",
            compression="zstd",
        )
        seal_artifacts(output)
    return {
        "directory": output,
        "status": record["status"],
        "ready_weeks": record["ready_weeks"],
        "weeks": record["weeks"],
        "executed_paths": record["executed_paths"],
        "error": record["error"],
        "trade_eligible": False,
    }


def verify_weekly_study(directory: Path) -> dict[str, Any]:
    verify_artifacts(directory)
    record = pq.read_table(directory / "run.parquet").to_pylist()[0]
    if (
        record["status"] not in {"blocked", "completed"}
        or record["engine_digest"] != engine_digest()
        or record["versions"] != runtime_versions()
    ):
        raise ValueError("Weekly replay requires the frozen engine and dependencies")
    config = load_config(directory / "config.toml")
    tables = (
        study_tables(config, load_snapshot(directory / "features"))
        if record["status"] == "completed"
        else preflight(config)
    )
    for name, expected in tables.items():
        actual = pq.read_table(directory / f"{name}.parquet")
        if (
            not expected.equals(actual, check_metadata=False)
            or expected.schema.metadata != actual.schema.metadata
        ):
            raise ValueError(f"Weekly replay differs: {name}")
    return {"status": "verified", "study_status": record["status"], "tables": len(tables)}
