"""冻结策略的只读当前决策；结果建议不会写回账户或发送订单。"""

import shutil
import tomllib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.backtest_study import _prefix_tables, read_backtest
from invest.broker_context import adapt_broker_context
from invest.contracts import TIME, AccountSnapshot, SignalFrame, StrategyState, research_schema
from invest.decision_io import decision_contexts, read_decision_contexts
from invest.engine import engine_digest, research_engine_digest
from invest.quality import regular_sessions
from invest.quant_report import write_quant_report
from invest.research_artifacts import (
    freeze_engine,
    protect_inputs,
    runtime_versions,
    seal_artifacts,
    verify_artifacts,
)
from invest.research_data import create_snapshot, digest, load_snapshot
from invest.signals import evaluate_signals, load_factor_pool
from invest.strategies import Policy, decide

RUN_SCHEMA = research_schema(
    "decision_run",
    [
        *[
            (name, pa.string())
            for name in (
                "run_id",
                "status",
                "strategy_run_id",
                "account_id",
                "snapshot_id",
                "inference_snapshot_id",
                "pool_id",
                "policy_id",
                "source",
                "scope",
                "source_scope",
                "history_status",
                "origin_holdout_status",
                "engine_digest",
                "financial_digest",
                "versions",
                "config_sha256",
                "context_sha256",
                "context_kind",
                "source_ref",
                "broker_capture_id",
                "error",
            )
        ],
        ("as_of", pa.date32()),
        ("known_through", pa.date32()),
        ("consumed_through", pa.date32()),
        ("created_at", TIME),
        ("completed_at", TIME),
        ("account_eligible", pa.bool_()),
        ("limitations", pa.list_(pa.string())),
        ("source_limitations", pa.list_(pa.string())),
    ],
)
RANKING_SCHEMA = research_schema(
    "rankings",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("symbol", pa.string()),
        ("score", pa.float64()),
        ("rank", pa.int32()),
        ("selected", pa.bool_()),
        ("action", pa.string()),
        ("reason", pa.string()),
        ("exit_reason", pa.string()),
        ("available_factors", pa.int32()),
        ("required_factors", pa.int32()),
        ("coverage", pa.float64()),
        ("data_cutoff", TIME),
        ("evidence_status", pa.string()),
    ],
)


@dataclass(frozen=True)
class DecisionConfig:
    strategy: Path
    snapshot: Path
    context: Path
    known_through: date
    broker_capture: Path | None = None


@dataclass(frozen=True)
class DecisionStudy:
    directory: Path
    run_id: str
    status: str


def load_decision_config(path: Path) -> DecisionConfig:
    values = tomllib.loads(path.read_text())
    required = {"strategy", "snapshot", "context", "known_through"}
    if not required <= values.keys() or values.keys() - required - {"broker_capture"}:
        raise ValueError("Decision requires strategy, snapshot, context and known_through")
    if type(values["known_through"]) is not date:
        raise ValueError("known_through must be a TOML date")
    try:
        return DecisionConfig(
            **{
                name: values[name]
                if name == "known_through"
                else (path.parent / values[name]).resolve()
                for name in values
            }
        )
    except TypeError as exc:
        raise ValueError("Decision input paths must be strings") from exc


def _context_table(config: DecisionConfig, day: date) -> pa.Table:
    if config.broker_capture is not None:
        return adapt_broker_context(config.broker_capture, config.context, config.snapshot, day)
    table = pq.read_table(config.context)
    if (table.schema.metadata or {}).get(b"context_kind") == b"broker_capture":
        raise ValueError("Broker context requires its original capture and persistent state")
    return table


def _context(
    config: DecisionConfig, day: date, policy: Policy, pool_id: str
) -> tuple[AccountSnapshot, StrategyState]:
    table = _context_table(config, day)
    metadata = table.schema.metadata or {}
    if (
        metadata.get(b"policy_id", b"").decode() != policy.policy_id
        or metadata.get(b"pool_id", b"").decode() != pool_id
        or metadata.get(b"price_basis") != b"raw"
        or metadata.get(b"context_kind")
        not in {b"backtest_simulation", b"declared_snapshot", b"broker_capture"}
        or not metadata.get(b"source_ref")
    ):
        raise ValueError("Decision context requires frozen policy, pool and raw quote provenance")
    matches = [
        (account, state) for account, state in read_decision_contexts(table) if account.as_of == day
    ]
    if len(matches) != 1:
        raise ValueError("Decision requires exactly one account context at the requested cutoff")
    account, state = matches[0]
    snapshot = load_snapshot(config.snapshot)
    if account.snapshot_id != snapshot.snapshot_id or account.source != snapshot.spec.source:
        raise ValueError("Account quotes must reference the exact research snapshot and source")
    calendar = regular_sessions(day, day).to_pylist()
    if not calendar:
        raise ValueError("Decision cutoff must be an XNYS session")
    closing = calendar[0]["close_at"]
    rows = {row["instrument"]: row for row in snapshot.bars.to_pylist() if row["date"] == day}
    quotes = []
    for quote in account.quotes:
        row = rows.get(quote.instrument)
        if (
            quote.available
            and row is not None
            and snapshot.spec.price_basis == "raw"
            and quote.close != row["close"].quantize(Decimal(".000001"))
        ):
            raise ValueError("Raw account quote disagrees with the research snapshot")
        available = row is not None and (
            (row["available_at"] is None and policy.allow_exploratory)
            or (row["available_at"] is not None and row["available_at"] <= closing)
        )
        active = any(
            member["instrument"] == quote.instrument
            and member["start"] <= day <= member["end"]
            and (
                (member["available_at"] is None and policy.allow_exploratory)
                or (member["available_at"] is not None and member["available_at"] <= closing)
            )
            for member in snapshot.universe.to_pylist()
        )
        quotes.append(
            replace(quote, active=quote.active and active, available=quote.available and available)
        )
    return replace(account, quotes=tuple(quotes)), state


def ranking_table(
    signals: SignalFrame,
    contributions: pa.Table,
    actions: pa.Table,
    universe: pa.Table,
    day: date,
    factor_count: int,
) -> pa.Table:
    values = {row["instrument"]: row for row in signals.table.to_pylist() if row["date"] == day}
    plans = {row["instrument"]: row for row in actions.to_pylist() if row["date"] == day}
    members = {
        row["instrument"]: row["symbol"]
        for row in universe.to_pylist()
        if row["start"] <= day <= row["end"]
    }
    coverage: dict[str, int] = {}
    for row in contributions.to_pylist():
        if row["date"] == day and row["admitted"]:
            coverage[row["instrument"]] = coverage.get(row["instrument"], 0) + 1
    closing = regular_sessions(day, day)["close_at"][0].as_py()
    rows = []
    for instrument in sorted(set(members) | set(plans)):
        signal, action = values.get(instrument, {}), plans.get(instrument, {})
        reason = action.get("reason", "quote_unavailable")
        if not signal and reason == "not_selected":
            reason = "factor_unavailable"
        count = coverage.get(instrument, 0)
        rows.append(
            {
                "date": day,
                "instrument": instrument,
                "symbol": members.get(instrument, instrument),
                "score": signal.get("score"),
                "rank": signal.get("rank"),
                "selected": action.get("target_quantity", 0) > 0,
                "action": action.get("action", "WAIT"),
                "reason": reason,
                "exit_reason": action.get("exit_reason", ""),
                "available_factors": count,
                "required_factors": factor_count,
                "coverage": count / factor_count,
                "data_cutoff": closing,
                "evidence_status": "research_only",
            }
        )
    rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 0, row["instrument"]))
    return pa.Table.from_pylist(
        rows,
        schema=RANKING_SCHEMA.with_metadata(
            {
                **(signals.table.schema.metadata or {}),
                **(RANKING_SCHEMA.metadata or {}),
            }
        ),
    )


def _tables(
    config: DecisionConfig, inference: Path, day: date, cache_root: Path
) -> dict[str, pa.Table]:
    strategy, origin = read_backtest(config.strategy)
    pool = load_factor_pool(strategy.factor_pool)
    account, state = _context(config, day, strategy.policy, pool.metadata["pool_id"])
    snapshot = load_snapshot(inference)
    result = evaluate_signals(
        pool,
        snapshot,
        day,
        day,
        allow_exploratory=strategy.policy.allow_exploratory,
        cache_root=cache_root,
    )
    # 用前缀计算，但动作身份仍绑定输入账户明确引用的来源快照，保持回测动作 ID 一致。
    signals = SignalFrame(
        result.signals.table.replace_schema_metadata(
            {
                **(result.signals.table.schema.metadata or {}),
                b"snapshot_id": account.snapshot_id.encode(),
                b"inference_snapshot_id": snapshot.snapshot_id.encode(),
            }
        )
    )
    plan = decide(signals, account, state, strategy.policy)
    return {
        "signals": signals.table,
        "factors": result.factors.table,
        "contributions": result.contributions,
        "actions": plan.actions,
        "rankings": ranking_table(
            signals, result.contributions, plan.actions, snapshot.universe, day, pool.table.num_rows
        ),
        "effective_context": decision_contexts(((account, state),)),
        "proposed_context": decision_contexts(((account, plan.state),)),
    }


def run_decision(
    config_path: Path, output: Path, as_of: date, *, cache_root: Path = Path("data/cache")
) -> DecisionStudy:
    config = load_decision_config(config_path)
    strategy, origin = read_backtest(config.strategy)
    pool = load_factor_pool(strategy.factor_pool)
    account, _ = _context(config, as_of, strategy.policy, pool.metadata["pool_id"])
    source = load_snapshot(config.snapshot)
    if as_of not in source.calendar["date"].to_pylist():
        raise ValueError("Decision cutoff is not covered by the data snapshot")
    if as_of < date.fromisoformat(pool.metadata["knowledge_through"]):
        raise ValueError("Decision cannot precede factor selection")
    output = output.resolve()
    protected: tuple[Path, ...] = (source.directory, config.strategy)
    if config.broker_capture:
        protected += (config.broker_capture,)
    if any(
        (config.context.parent / marker).exists()
        for marker in (
            "CURRENT",
            "run.parquet",
            "manifest.parquet",
            "registration.parquet",
            "artifacts.parquet",
        )
    ):
        protected += (config.context.parent,)
    protect_inputs((output, cache_root), protected)
    protect_inputs((cache_root,), (output,))
    known = max(config.known_through, origin["known_through"], origin["consumed_through"])
    metadata = _context_table(config, as_of).schema.metadata or {}
    record: dict[str, Any] = {
        "run_id": uuid.uuid4().hex,
        "status": "registered",
        "strategy_run_id": origin["run_id"],
        "account_id": account.account_id,
        "snapshot_id": source.snapshot_id,
        "inference_snapshot_id": None,
        "pool_id": pool.metadata["pool_id"],
        "policy_id": strategy.policy.policy_id,
        "source": source.spec.source,
        "scope": None,
        "source_scope": source.scope,
        "history_status": "known_history" if known >= as_of else "declared_unseen_inference",
        "origin_holdout_status": origin["origin_holdout_status"],
        "engine_digest": engine_digest(),
        "financial_digest": research_engine_digest(),
        "versions": runtime_versions(),
        "config_sha256": digest(config_path),
        "context_sha256": digest(config.context),
        "context_kind": metadata[b"context_kind"].decode(),
        "source_ref": metadata[b"source_ref"].decode(),
        "broker_capture_id": metadata.get(b"broker_capture_id", b"").decode(),
        "as_of": as_of,
        "known_through": known,
        "consumed_through": as_of,
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "account_eligible": False,
        "source_limitations": list(source.limitations),
        "error": "",
        "limitations": [
            "recommendations_only",
            "no_actual_execution_or_profitability_qualification",
            "broker_capture_reconciled_strategy_history_supplied"
            if config.broker_capture
            else "account_context_supplied_not_broker_verified",
            "next_session_open_proxy",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    pq.write_table(
        pa.Table.from_pylist([record], schema=RUN_SCHEMA),
        output / "registration.parquet",
        compression="zstd",
    )
    try:
        freeze_engine(output)
        shutil.copy2(config_path, output / "config.toml")
        shutil.copy2(config.context, output / "context.parquet")
        if config.broker_capture:
            shutil.copytree(config.broker_capture, output / "broker_capture")
        shutil.copytree(config.strategy, output / "strategy")
        shutil.copytree(config.snapshot, output / "snapshot")
        bars, members = _prefix_tables(source, as_of)
        inference = create_snapshot(
            bars,
            members,
            output / "inference",
            source.spec,
            allow_exploratory=strategy.policy.allow_exploratory,
        )
        record["inference_snapshot_id"] = inference.snapshot_id
        frozen = _frozen_config(output)
        _, frozen_origin = read_backtest(frozen.strategy)
        frozen_context = _context_table(frozen, as_of)
        frozen_metadata = frozen_context.schema.metadata or {}
        frozen_account, _ = _context(frozen, as_of, strategy.policy, pool.metadata["pool_id"])
        if (
            frozen_origin != origin
            or digest(output / "config.toml") != record["config_sha256"]
            or digest(frozen.context) != record["context_sha256"]
            or load_snapshot(frozen.snapshot).snapshot_id != record["snapshot_id"]
            or frozen_metadata.get(b"broker_capture_id", b"").decode()
            != record["broker_capture_id"]
            or frozen_metadata.get(b"source_ref", b"").decode() != record["source_ref"]
            or frozen_account.account_id != record["account_id"]
        ):
            raise ValueError("Decision inputs changed during freezing")
        tables = _tables(frozen, inference.directory, as_of, cache_root)
        signal_metadata = tables["signals"].schema.metadata or {}
        record["scope"] = signal_metadata[b"scope"].decode()
        record["limitations"] += list(inference.limitations) + list(origin["limitations"])
        for name, table in tables.items():
            pq.write_table(
                table.replace_schema_metadata(
                    {
                        **(table.schema.metadata or {}),
                        b"run_id": record["run_id"].encode(),
                        b"history_status": record["history_status"].encode(),
                        b"evidence_status": b"research_only",
                        b"source_scope": source.scope.encode(),
                        b"source": source.spec.source.encode(),
                        b"scope": record["scope"].encode(),
                        b"policy_id": record["policy_id"].encode(),
                        b"pool_id": record["pool_id"].encode(),
                        b"context_kind": b"decision_preview",
                    }
                ),
                output / f"{name}.parquet",
                compression="zstd",
            )
        if engine_digest() != record["engine_digest"]:
            raise ValueError("Engine changed during decision")
        record.update(
            status="completed" if tables["signals"].num_rows else "insufficient_evidence",
            completed_at=datetime.now(UTC),
        )
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
            write_quant_report(output, "decision", record)
        seal_artifacts(output)
    return DecisionStudy(output, record["run_id"], record["status"])


def _frozen_config(directory: Path) -> DecisionConfig:
    return replace(
        load_decision_config(directory / "config.toml"),
        strategy=directory / "strategy",
        snapshot=directory / "snapshot",
        context=directory / "context.parquet",
        broker_capture=directory / "broker_capture"
        if (directory / "broker_capture").is_dir()
        else None,
    )


def verify_decision(directory: Path, *, cache_root: Path = Path("data/cache")) -> dict[str, str]:
    protect_inputs((cache_root,), (directory,))
    verify_artifacts(directory)
    record = pq.read_table(directory / "run.parquet").to_pylist()[0]
    if (
        record["status"] not in {"completed", "insufficient_evidence"}
        or record.get("financial_digest") != research_engine_digest()
        or record["versions"] != runtime_versions()
    ):
        raise ValueError("Decision replay requires its completed run and frozen engine")
    context = _context_table(_frozen_config(directory), record["as_of"])
    context_metadata = context.schema.metadata or {}
    if (
        digest(directory / "config.toml") != record["config_sha256"]
        or digest(directory / "context.parquet") != record["context_sha256"]
        or context_metadata.get(b"broker_capture_id", b"").decode()
        != record.get("broker_capture_id", "")
        or context_metadata.get(b"source_ref", b"").decode() != record["source_ref"]
        or [
            account.account_id
            for account, _ in read_decision_contexts(context)
            if account.as_of == record["as_of"]
        ]
        != [record["account_id"]]
    ):
        raise ValueError("Decision configuration or account context changed")
    for name, table in _tables(
        _frozen_config(directory), directory / "inference", record["as_of"], cache_root
    ).items():
        if not table.equals(pq.read_table(directory / f"{name}.parquet"), check_metadata=False):
            raise ValueError(f"Decision replay changed: {name}")
    return {
        "status": "verified",
        "run_id": record["run_id"],
        "engine_digest": record["engine_digest"],
    }
