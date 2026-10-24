"""冻结研究输入、运行共同决策引擎并重放验证；不访问持续账户或券商。"""

import hashlib
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.backtest import BacktestResult, simulate_signals
from invest.backtest_config import BacktestConfig, load_backtest_config
from invest.contracts import UNIVERSE, DataSnapshot, SignalFrame, research_schema
from invest.decision_io import decision_contexts, read_decision_contexts
from invest.engine import engine_digest, research_engine_digest
from invest.evaluation import METRIC_SCHEMA, evaluate, yearly
from invest.market import read_bars
from invest.portfolio_audit import audit_backtest
from invest.quant_report import write_quant_report
from invest.research_artifacts import (
    freeze_engine,
    protect_inputs,
    runtime_versions,
    seal_artifacts,
    verify_artifacts,
)
from invest.research_data import (
    create_snapshot,
    digest,
    identity,
    load_snapshot,
    validate_snapshot_tables,
)
from invest.signals import FrozenFactorPool, generate_signal_history, load_factor_pool
from invest.strategies import Policy, decide

RUN_SCHEMA = research_schema(
    "backtest_run",
    [
        *[
            (name, pa.string())
            for name in (
                "run_id",
                "status",
                "snapshot_id",
                "inference_snapshot_id",
                "pool_id",
                "mining_run_id",
                "mining_manifest_sha256",
                "source",
                "scope",
                "source_scope",
                "engine_digest",
                "financial_digest",
                "versions",
                "history_status",
                "origin_holdout_status",
                "config_sha256",
                "error",
            )
        ],
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("known_through", pa.date32()),
        ("consumed_through", pa.date32()),
        ("account_eligible", pa.bool_()),
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("completed_at", pa.timestamp("us", tz="UTC")),
        ("limitations", pa.list_(pa.string())),
        ("source_limitations", pa.list_(pa.string())),
    ],
)
SUMMARY_SCHEMA = research_schema(
    "backtest_metrics",
    [
        ("scenario", pa.string()),
        *[(field.name, field.type) for field in METRIC_SCHEMA],
        ("closed_cycles", pa.int64()),
        ("wins", pa.int64()),
        ("losses", pa.int64()),
        ("win_rate", pa.float64()),
        ("average_r", pa.float64()),
    ],
)


@dataclass(frozen=True)
class BacktestStudy:
    directory: Path
    run_id: str
    status: str
    history_status: str


MINING_FILES = ("run.parquet", "registration.parquet", "config.toml", "factor_pool.parquet")


def _read_mining_source(path: Path) -> tuple[FrozenFactorPool, dict[str, Any], str]:
    """从同一批读取的字节验证选中因子池、登记和完成记录；原清单保留完整来源范围。"""
    bodies = {
        name: (path.parent / name).read_bytes() for name in (*MINING_FILES, "artifacts.parquet")
    }
    entries = pq.read_table(pa.BufferReader(bodies["artifacts.parquet"])).to_pylist()
    manifest = {row["path"]: row["sha256"] for row in entries}
    if len(manifest) != len(entries) or any(
        manifest.get(name) != hashlib.sha256(bodies[name]).hexdigest() for name in MINING_FILES
    ):
        raise ValueError("Frozen mining provenance changed")
    origin_rows = pq.read_table(pa.BufferReader(bodies["run.parquet"])).to_pylist()
    registrations = pq.read_table(pa.BufferReader(bodies["registration.parquet"])).to_pylist()
    if len(origin_rows) != 1 or len(registrations) != 1:
        raise ValueError("Frozen mining provenance requires one registration and result")
    origin, registration = origin_rows[0], registrations[0]
    pool = FrozenFactorPool(pq.read_table(pa.BufferReader(bodies["factor_pool.parquet"])))
    completed_fields = {"status", "development_snapshot_id", "completed_at", "selected", "pool_id"}
    if (
        path.name != "factor_pool.parquet"
        or origin["status"] != "selected"
        or registration["status"] != "registered"
        or origin["run_id"] != pool.metadata["run_id"]
        or origin["pool_id"] != pool.metadata["pool_id"]
        or origin["selected"] != pool.table.num_rows
        or origin["config_sha256"] != hashlib.sha256(bodies["config.toml"]).hexdigest()
        or any(
            registration[key] != value
            for key, value in origin.items()
            if key not in completed_fields
        )
    ):
        raise ValueError("Frozen mining pool and registration provenance disagree")
    return pool, origin, hashlib.sha256(bodies["artifacts.parquet"]).hexdigest()


def _inputs(config: BacktestConfig) -> dict[str, pa.Table]:
    snapshot = load_snapshot(config.snapshot)
    days = snapshot.calendar["date"].to_pylist()
    if config.start not in days or config.end not in days or days.index(config.start) == 0:
        raise ValueError("Backtest needs a preceding decision session inside the snapshot")
    first = days[days.index(config.start) - 1]
    all_members = snapshot.universe.to_pylist()
    members = {
        row["instrument"]: row["symbol"] for row in all_members if row["start"] <= config.end
    }
    if not set(members) <= set(config.execution) or set(config.execution) - {
        row["instrument"] for row in all_members
    }:
        raise ValueError("Execution inputs must cover the declared snapshot universe")
    inputs = {}
    research_rows = {(row["date"], row["instrument"]): row for row in snapshot.bars.to_pylist()}
    for instrument in sorted(members):
        path = config.execution[instrument]
        table = read_bars(path, members[instrument])
        metadata = table.schema.metadata or {}
        if metadata[b"source"].decode() != snapshot.spec.source:
            raise ValueError("Execution source cannot replace the research source")
        if snapshot.spec.source != "synthetic" and (
            snapshot.spec.source != "ibkr"
            or metadata.get(b"corporate_actions") != b"complete"
            or metadata.get(b"volume_unit") != b"shares"
            or not metadata.get(b"source_ref")
        ):
            raise ValueError(
                "IBKR execution requires normalized raw prices, share volume "
                "and complete corporate-action provenance"
            )
        rows = [
            {**row, "symbol": instrument}
            for row in table.to_pylist()
            if first <= row["date"] <= config.end
        ]
        if snapshot.spec.price_basis == "raw":
            for row in rows:
                reference = research_rows.get((row["date"], instrument))
                if reference is not None and any(
                    row[field] != reference[field].quantize(Decimal(".000001"))
                    for field in ("open", "high", "low", "close")
                ):
                    raise ValueError("Execution raw prices disagree with the research snapshot")
        elif metadata.get(b"research_snapshot_id", b"").decode() != snapshot.snapshot_id:
            raise ValueError(
                "Adjusted research requires an explicitly linked raw execution snapshot"
            )
        inputs[instrument] = pa.Table.from_pylist(rows, schema=table.schema)
    return inputs


def _prefix_tables(source: DataSnapshot, end: date) -> tuple[pa.Table, pa.Table]:
    members = [
        {**row, "end": min(row["end"], end)}
        for row in source.universe.to_pylist()
        if row["start"] <= end
    ]
    instruments = {row["instrument"] for row in members}
    bars = [
        row
        for row in source.bars.to_pylist()
        if row["date"] <= end and row["instrument"] in instruments
    ]
    return pa.Table.from_pylist(bars, schema=source.bars.schema), pa.Table.from_pylist(
        members, schema=UNIVERSE
    )


def _tables(config: BacktestConfig, cache_root: Path) -> dict[str, pa.Table]:
    snapshot = load_snapshot(config.snapshot.parent / "inference")
    pool = load_factor_pool(config.factor_pool)
    inputs = _inputs(config)
    first = min(inputs[next(iter(inputs))]["date"].to_pylist())
    signals = generate_signal_history(
        pool,
        snapshot,
        first,
        config.end,
        allow_exploratory=config.policy.allow_exploratory,
        cache_root=cache_root,
    )
    account_id = identity(
        {
            "snapshot": snapshot.snapshot_id,
            "pool": pool.metadata["pool_id"],
            "policy": config.policy.policy_id,
            "start": config.start.isoformat(),
            "capital": str(config.initial_cash),
        }
    )

    def simulate(frame: SignalFrame, settings: Policy) -> BacktestResult:
        return simulate_signals(
            inputs,
            frame,
            settings,
            config.start,
            config.end,
            initial_cash=config.initial_cash,
            account_id=account_id,
            universe=snapshot.universe,
            availability=snapshot.bars,
        )

    result = simulate(signals, config.policy)
    portfolio = result.portfolio
    checks, attribution, cycles = audit_backtest(
        inputs, portfolio, config.policy, config.initial_cash, availability=snapshot.bars
    )
    contexts = decision_contexts(result.contexts)
    for account, state in read_decision_contexts(contexts):
        expected = [row for row in result.actions.to_pylist() if row["date"] == account.as_of]
        if decide(signals, account, state, config.policy).actions.to_pylist() != expected:
            raise ValueError("Persisted current decisions differ from backtest actions")
    tables = {
        "signals": signals.table,
        "actions": result.actions,
        "orders": portfolio.orders,
        "fills": portfolio.trades,
        "outcomes": result.outcomes,
        "positions": portfolio.positions,
        "equity": portfolio.equity,
        "events": portfolio.events,
        "checks": checks,
        "attribution": attribution,
        "round_trips": cycles,
        "decision_contexts": contexts,
        "final_context": decision_contexts(((result.final_account, result.final_state),)),
    }
    summaries = []
    scenarios = {"strategy": (result, config.policy)}
    rows = signals.table.to_pylist()
    reference = SignalFrame(
        pa.Table.from_pylist(
            [
                {**row, "score": 1.0, "direction": 1, "rank": rank + 1}
                for day in sorted({row["date"] for row in rows})
                for rank, row in enumerate(
                    sorted(
                        (row for row in rows if row["date"] == day),
                        key=lambda row: row["instrument"],
                    )
                )
            ],
            schema=signals.table.schema,
        )
    )
    reference_policy = replace(config.policy, top_k=len(inputs), min_score=0.0)
    scenarios["equal_weight"] = (simulate(reference, reference_policy), reference_policy)
    cash = SignalFrame(
        pa.Table.from_pylist(
            [{**row, "score": 0.0, "direction": 0} for row in rows], schema=signals.table.schema
        )
    )
    scenarios["cash"] = (simulate(cash, config.policy), config.policy)
    stressed = replace(
        config.policy,
        commission=config.policy.commission * 2,
        slippage_bps=config.policy.slippage_bps * 2,
    )
    scenarios["double_cost"] = (simulate(signals, stressed), stressed)
    for name, (simulation, settings) in scenarios.items():
        audit, _, closed = audit_backtest(
            inputs, simulation.portfolio, settings, config.initial_cash, availability=snapshot.bars
        )
        metric = evaluate(simulation.portfolio, config.initial_cash, closed).to_pylist()[0]
        outcomes = closed["outcome"].to_pylist()
        multiples = [value for value in closed["r_multiple"].to_pylist() if value is not None]
        summaries.append(
            {
                "scenario": name,
                **metric,
                "closed_cycles": len(outcomes),
                "wins": outcomes.count("win"),
                "losses": outcomes.count("loss"),
                "win_rate": outcomes.count("win") / len(outcomes) if outcomes else None,
                "average_r": sum(multiples) / len(multiples) if multiples else None,
            }
        )
        if name != "strategy":
            tables.update(
                {
                    f"{name}_{key}": table
                    for key, table in {
                        "equity": simulation.portfolio.equity,
                        "fills": simulation.portfolio.trades,
                        "orders": simulation.portfolio.orders,
                        "positions": simulation.portfolio.positions,
                        "checks": audit,
                        "round_trips": closed,
                    }.items()
                }
            )
    tables["metrics"] = pa.Table.from_pylist(summaries, schema=SUMMARY_SCHEMA)
    tables["yearly"] = yearly(
        portfolio, scenarios["equal_weight"][0].portfolio, config.initial_cash
    )
    return tables


def run_backtest(
    config_path: Path, output: Path, *, cache_root: Path = Path("data/cache")
) -> BacktestStudy:
    config = load_backtest_config(config_path)
    pool, origin, mining_manifest = _read_mining_source(config.factor_pool)
    snapshot = load_snapshot(config.snapshot)
    inputs = _inputs(config)
    prefix_bars, prefix_members = _prefix_tables(snapshot, config.end)
    _, limitations = validate_snapshot_tables(prefix_bars, prefix_members, snapshot.spec)
    if limitations and not config.policy.allow_exploratory:
        raise ValueError("Exploratory backtest history requires explicit opt-in")
    parent = config.factor_pool.parent
    days = snapshot.calendar["date"].to_pylist()
    if days[days.index(config.start) - 1] < date.fromisoformat(pool.metadata["knowledge_through"]):
        raise ValueError("Backtest decisions cannot precede factor selection")
    output = output.resolve()
    protect_inputs((cache_root,), (snapshot.directory, parent, output))
    if output.is_relative_to(snapshot.directory) or output.is_relative_to(parent):
        raise ValueError("Backtest output cannot modify historical research inputs")
    known = max(
        config.known_through,
        origin["known_through"],
        date.fromisoformat(pool.metadata["knowledge_through"]),
    )
    record = {
        "run_id": uuid.uuid4().hex,
        "status": "registered",
        "snapshot_id": snapshot.snapshot_id,
        "inference_snapshot_id": None,
        "pool_id": pool.metadata["pool_id"],
        "mining_run_id": origin["run_id"],
        "mining_manifest_sha256": mining_manifest,
        "source": snapshot.spec.source,
        "scope": "exploratory"
        if limitations or pool.metadata["scope"] == "exploratory"
        else "synthetic"
        if snapshot.spec.source == "synthetic"
        else "research",
        "source_scope": snapshot.scope,
        "source_limitations": list(snapshot.limitations),
        "engine_digest": engine_digest(),
        "financial_digest": research_engine_digest(),
        "versions": runtime_versions(),
        "history_status": "known_history" if known >= config.start else "declared_unseen_evaluated",
        "origin_holdout_status": origin["holdout_status"],
        "known_through": known,
        "config_sha256": digest(config_path),
        "error": "",
        "start": config.start,
        "end": config.end,
        "consumed_through": config.end,
        "account_eligible": False,
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "limitations": list(limitations)
        + [
            "daily_open_proxy",
            "prior_session_volume_proxy",
            "integer_forward_splits_only",
            "complete_common_execution_calendar_required",
            "no_forced_terminal_liquidation",
            "settlement_policy_proxy",
            "daily_ohlc_adverse_first",
            "no_actual_execution_or_profitability_qualification",
            "equal_weight_reference_uses_same_eligible_universe_and_risk_policy",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    pq.write_table(
        pa.Table.from_pylist([record], schema=RUN_SCHEMA),
        output / "registration.parquet",
        compression="zstd",
    )
    try:
        (output / "config.toml").write_bytes(config_path.read_bytes())
        shutil.copytree(snapshot.directory, output / "snapshot")
        inference = create_snapshot(
            prefix_bars,
            prefix_members,
            output / "inference",
            snapshot.spec,
            allow_exploratory=config.policy.allow_exploratory,
        )
        record["inference_snapshot_id"] = inference.snapshot_id
        (output / "mining").mkdir()
        for file in (*MINING_FILES, "artifacts.parquet"):
            shutil.copy2(parent / file, output / "mining" / file)
        (output / "execution").mkdir()
        for instrument in inputs:
            input_path = config.execution[instrument]
            shutil.copy2(input_path, output / "execution" / f"{instrument}.parquet")
        freeze_engine(output)
        frozen = _frozen_config(output)
        frozen_pool, frozen_origin, frozen_manifest = _read_mining_source(frozen.factor_pool)
        if (
            frozen_origin != origin
            or frozen_manifest != mining_manifest
            or digest(output / "config.toml") != record["config_sha256"]
            or load_snapshot(frozen.snapshot).snapshot_id != record["snapshot_id"]
            or frozen_pool.metadata["pool_id"] != record["pool_id"]
        ):
            raise ValueError("Research inputs changed during freezing")
        tables = _tables(frozen, cache_root)
        for name, table in tables.items():
            metadata = {
                b"currency": b"USD",
                b"price_basis": b"raw",
                **(table.schema.metadata or {}),
                b"run_id": record["run_id"].encode(),
                b"source": record["source"].encode(),
                b"scope": record["scope"].encode(),
                b"history_status": record["history_status"].encode(),
                b"evidence_status": b"research_only",
                b"source_snapshot_id": snapshot.snapshot_id.encode(),
                b"source_scope": snapshot.scope.encode(),
                b"policy_id": config.policy.policy_id.encode(),
                b"pool_id": pool.metadata["pool_id"].encode(),
                b"context_kind": b"backtest_simulation",
                b"source_ref": record["run_id"].encode(),
            }
            pq.write_table(
                table.replace_schema_metadata(metadata),
                output / f"{name}.parquet",
                compression="zstd",
            )
        if any(
            "error" in table["status"].to_pylist()
            for name, table in tables.items()
            if name.endswith("checks")
        ):
            raise ValueError("Independent accounting failed; inspect the saved check tables")
        if engine_digest() != record["engine_digest"]:
            raise ValueError("Engine changed during backtest")
        record.update(status="completed", completed_at=datetime.now(UTC))
    except Exception as exc:
        record.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", completed_at=datetime.now(UTC)
        )
        raise
    finally:
        pq.write_table(
            pa.Table.from_pylist([record], schema=RUN_SCHEMA),
            output / "run.parquet",
            compression="zstd",
        )
        if record["status"] in {"completed", "insufficient_evidence"}:
            write_quant_report(output, "backtest", record)
        seal_artifacts(output)
    return BacktestStudy(output, record["run_id"], record["status"], record["history_status"])


def _frozen_config(directory: Path) -> BacktestConfig:
    config = load_backtest_config(directory / "config.toml")
    return replace(
        config,
        snapshot=directory / "snapshot",
        factor_pool=directory / "mining" / "factor_pool.parquet",
        execution={
            instrument: directory / "execution" / f"{instrument}.parquet"
            for instrument in config.execution
        },
    )


def read_backtest(directory: Path) -> tuple[BacktestConfig, dict[str, Any]]:
    """校验冻结回测及版本后提供策略，不运行或改写该实验。"""
    verify_artifacts(directory)
    record = pq.read_table(directory / "run.parquet").to_pylist()[0]
    if (
        record["status"] != "completed"
        or record.get("financial_digest") != research_engine_digest()
        or record["versions"] != runtime_versions()
    ):
        raise ValueError("Replay requires the completed run and its frozen engine version")
    if digest(directory / "config.toml") != record["config_sha256"]:
        raise ValueError("Backtest configuration changed")
    config = _frozen_config(directory)
    pool, origin, manifest = _read_mining_source(config.factor_pool)
    if (
        manifest != record.get("mining_manifest_sha256")
        or origin["run_id"] != record["mining_run_id"]
        or pool.metadata["pool_id"] != record["pool_id"]
    ):
        raise ValueError("Registered mining provenance changed")
    return config, record


def verify_backtest(directory: Path, *, cache_root: Path = Path("data/cache")) -> dict[str, str]:
    """只读校验输入及产物，并在内存重跑全部情景，不覆盖旧研究。"""
    protect_inputs((cache_root,), (directory,))
    config, record = read_backtest(directory)
    for name, table in _tables(config, cache_root).items():
        if not table.equals(pq.read_table(directory / f"{name}.parquet"), check_metadata=False):
            raise ValueError(f"Backtest replay changed: {name}")
    return {
        "status": "verified",
        "run_id": record["run_id"],
        "engine_digest": record["engine_digest"],
    }
