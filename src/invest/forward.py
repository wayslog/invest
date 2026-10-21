"""Single-host, append-only forward accounts with atomic directory commits."""

import os
import shutil
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import distributions, version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock, Timeout

from invest.datasets import checksum, verify_dataset
from invest.dividends import audit_dividends
from invest.forward_config import Observation, parse_observation
from invest.forward_engine import (
    ForwardState,
    advance,
    as_portfolio,
    cancel_future,
    next_session,
)
from invest.forward_versions import check_archive, validate_versions, verify_archived
from invest.market import read_bars
from invest.paper import ZERO, Account
from invest.portfolio_audit import audit_portfolio
from invest.quality import (
    audit_bars,
    daily_capture_after,
    latest_completed_session,
    regular_sessions,
)
from invest.research_registry import (
    read_registration,
    registration_known_history,
    seal,
    verify_inventory,
    write_table,
)
from invest.storage import engine_digest
from invest.study_config import StudyConfig, parse_study

STAMP = pa.timestamp("us", tz="UTC")
JOURNAL_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("account_id", pa.string()),
        ("recorded_at", STAMP),
        ("kind", pa.string()),
        ("actor", pa.string()),
        ("reason", pa.string()),
        ("engine_sha256", pa.string()),
        ("parent_sha256", pa.string()),
    ],
    metadata={b"schema_version": b"invest.forward.journal.v1"},
)
REGISTRATION_SCHEMA = pa.schema(
    [
        ("account_id", pa.string()),
        ("registered_at", STAMP),
        ("engine_sha256", pa.string()),
        ("observation_body", pa.binary()),
        ("policy_body", pa.binary()),
        ("python_version", pa.string()),
        ("package_version", pa.string()),
    ],
    metadata={b"schema_version": b"invest.forward.registration.v1"},
)
RECEIPT_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("first_received_at", STAMP),
        ("last_received_at", STAMP),
        ("scope", pa.string()),
    ]
)
HISTORY_TABLES = [
    "equity",
    "positions",
    "trades",
    "orders",
    "events",
    "correlations",
    "signals",
    "outcomes",
]


def clock() -> datetime:
    return datetime.now(UTC)


@contextmanager
def account_lock(account: Path) -> Iterator[None]:
    if not account.is_dir() or account.is_symlink():
        raise ValueError("Forward account does not exist or is a link")
    try:
        with FileLock(account / ".lock", timeout=0):
            yield
    except Timeout as exc:
        raise ValueError("Another process is updating this forward account") from exc


def _runs(account: Path) -> list[Path]:
    directory = account / "journal"
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Invalid forward account journal")
    runs = sorted(p for p in directory.iterdir() if not p.name.startswith("."))
    parent, account_id = "", None
    for i, run in enumerate(runs):
        if run.name != f"{i:08d}" or not run.is_dir() or run.is_symlink():
            raise ValueError("Missing or invalid forward journal sequence")
        verify_inventory(run)
        table = pq.read_table(run / "journal.parquet")
        if not table.schema.equals(JOURNAL_SCHEMA, check_metadata=True) or table.num_rows != 1:
            raise ValueError("Invalid forward journal manifest")
        row = table.to_pylist()[0]
        account_id = row["account_id"] if account_id is None else account_id
        if (
            row["sequence"] != i
            or row["parent_sha256"] != parent
            or row["account_id"] != account_id
        ):
            raise ValueError("Forward journal chain mismatch")
        parent = checksum(run / "files.parquet")
    if not runs:
        raise ValueError("Forward account has no committed registration")
    return runs


def _load(account: Path) -> tuple[list[Path], Observation, StudyConfig, ForwardState]:
    runs = _runs(account)
    row = pq.read_table(runs[0] / "registration.parquet").to_pylist()[0]
    plan, policy = parse_observation(row["observation_body"]), parse_study(row["policy_body"])
    _check_binding(runs[0], row["engine_sha256"], plan)
    validate_versions(runs, row["engine_sha256"])
    state = ForwardState.load(
        {
            name: pq.read_table(runs[-1] / f"{name}.parquet")
            for name in ["state", "ledgers", "pending"]
        }
    )
    return runs, plan, policy, state


def _check_binding(genesis: Path, digest: str, plan: Observation) -> None:
    check_archive(genesis, digest)
    if plan.mode in {"qualified_strategy", "shadow_research"}:
        qualification = genesis / "qualification"
        read_registration(qualification / "registration.parquet", required_engine=digest)
        if pq.read_table(qualification / "manifest.parquet")["engine_sha256"][0].as_py() != digest:
            raise ValueError("Research qualification engine differs from forward registration")


def _require_engine(digest: str) -> None:
    if engine_digest() != digest:
        raise ValueError("Engine changed during the forward transaction")


def _at(plan: Observation, at: datetime | None) -> datetime:
    if at is not None and plan.mode != "drill":
        raise ValueError("An explicit clock is only allowed for synthetic drills")
    now = at or clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Clock must have a timezone")
    return now.astimezone(UTC)


def _guard(runs: list[Path], now: datetime) -> str:
    row = pq.read_table(runs[-1] / "journal.parquet").to_pylist()[0]
    if row["engine_sha256"] != engine_digest():
        raise ValueError("Frozen forward engine changed; retain this account and use archived code")
    if now < row["recorded_at"]:
        raise ValueError("Forward clock cannot move backwards")
    return str(row["account_id"])


def _publish(
    account: Path,
    staging: Path,
    runs: list[Path],
    account_id: str,
    now: datetime,
    kind: str,
    actor: str,
    reason: str,
    tables: dict[str, pa.Table],
) -> Path:
    genesis = runs[0] if runs else staging
    registration = pq.read_table(genesis / "registration.parquet").to_pylist()[0]
    digest = (
        pq.read_table(staging / "migration.parquet")["to_engine_sha256"][0].as_py()
        if kind == "migrate"
        else pq.read_table(runs[-1] / "journal.parquet")["engine_sha256"][0].as_py()
        if runs
        else registration["engine_sha256"]
    )
    _require_engine(digest)
    for name, table in tables.items():
        write_table(table, staging / f"{name}.parquet")
    write_table(
        pa.Table.from_pylist(
            [
                {
                    "sequence": len(runs),
                    "account_id": account_id,
                    "recorded_at": now,
                    "kind": kind,
                    "actor": actor,
                    "reason": reason,
                    "engine_sha256": digest,
                    "parent_sha256": checksum(runs[-1] / "files.parquet") if runs else "",
                }
            ],
            schema=JOURNAL_SCHEMA,
        ),
        staging / "journal.parquet",
    )
    state = tables["state"].to_pylist()[0]
    purpose = parse_observation(registration["observation_body"]).mode
    if not runs:
        _check_binding(genesis, digest, parse_observation(registration["observation_body"]))
    purpose_note = (
        "**影子研究账户：尚未取得正式策略资格。**"
        if purpose == "shadow_research"
        else f"用途：{purpose}。"
    )
    activity = ""
    if "equity" in tables and tables["equity"].num_rows:
        closing = tables["equity"].to_pylist()[-1]
        activity = (
            f"期末净值：{closing['equity']} 美元；持仓市值：{closing['market_value']}；"
            f"应收：{closing['receivables']}；当前回撤：{closing['drawdown']:.2%}。\n\n"
            f"本次新订单 {tables['orders'].num_rows}，核算成交 {tables['trades'].num_rows}，"
            f"原始信号记录 {tables['signals'].num_rows}，"
            f"独立对账 {tables['reconciliation'].num_rows} 项。\n\n"
        )
    (staging / "report.md").write_text(
        f"# Paper 每次运行记录\n\n账户：`{account_id}`；提交：{len(runs)}；"
        f"时间：{now.isoformat()}。\n\n"
        f"{purpose_note}\n\n"
        f"任务：{kind}；运行状态：{state['operations']}；风险状态：{state['risk_status']}。\n\n"
        f"核算到：{state['last_session']}；已核算 {state['sessions']} 个交易日；"
        f"现金：{state['cash']} 美元；净值高点：{state['peak']} 美元。\n\n"
        f"{activity}说明：{reason}\n\n"
        "成交为日线开盘代理的延迟核算；不代表券商订单或实时成交。\n",
        encoding="utf-8",
    )
    seal(staging)
    if kind == "migrate":
        validate_versions([*runs, staging], registration["engine_sha256"])
    # There is no separately updated CURRENT pointer: the rename IS the commit.
    for path in staging.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for directory in sorted(
        [p for p in staging.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True
    ) + [staging]:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _require_engine(digest)
    if (
        "orders" in tables
        and parse_observation(registration["observation_body"]).mode != "drill"
        and any(
            clock() + timedelta(minutes=1) >= t
            for t in tables["orders"]["effective_at"].to_pylist()
        )
    ):
        raise ValueError("Decision publication missed the next-open safety deadline; retry")
    destination = account / "journal" / f"{len(runs):08d}"
    staging.rename(destination)
    descriptor = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def _staging(account: Path) -> Path:
    path = account / "journal" / f".{uuid.uuid4().hex}.tmp"
    path.mkdir(parents=True)
    return path


def _collect(runs: list[Path], name: str, extra: pa.Table | None = None) -> pa.Table:
    tables = [
        pq.read_table(run / f"{name}.parquet") for run in runs if (run / f"{name}.parquet").exists()
    ]
    if extra is not None:
        tables.append(extra)
    if not tables:
        raise ValueError(f"No {name} records")
    return pa.concat_tables(tables)


def _history(runs: list[Path], symbols: tuple[str, ...]) -> dict[str, pa.Table]:
    location = next(run for run in reversed(runs) if (run / "accepted").is_dir())
    return {s: read_bars(location / "accepted" / f"{s}.parquet", s) for s in symbols}


def _inputs(
    sources: dict[str, Path],
    staging: Path,
    plan: Observation,
    now: datetime,
    issuer: Path | None,
    registered: datetime | None,
) -> tuple[dict[str, pa.Table], datetime]:
    if set(sources) != set(plan.symbols):
        raise ValueError("Every frozen observation symbol is required")
    inputs: dict[str, pa.Table] = {}
    receipts: list[dict[str, Any]] = []
    if plan.mode != "drill":
        if issuer is None:
            raise ValueError("Real observations require independent issuer evidence")
        shutil.copyfile(issuer, staging / "issuer-source.parquet")
        source_time = pq.read_table(staging / "issuer-source.parquet")["observed_at"][0].as_py()
        if source_time is None or source_time > now:
            raise ValueError("Issuer evidence was not available at this observation time")
    for symbol, source in sorted(sources.items()):
        destination = staging / "inputs" / symbol
        destination.parent.mkdir(exist_ok=True)
        if plan.mode == "drill":
            destination.mkdir()
            shutil.copyfile(source, destination / "bars.parquet")
            table = read_bars(destination / "bars.parquet", symbol)
            if (table.schema.metadata or {}).get(b"source") != b"synthetic":
                raise ValueError("Drills require explicitly synthetic data")
            first = last = now
        else:
            shutil.copytree(source, destination)
            table = verify_dataset(destination)
            if table["symbol"][0].as_py() != symbol:
                raise ValueError("Dataset symbol differs from frozen observation")
            audit = audit_dividends(destination, staging / "issuer-source.parquet")
            write_table(audit.checks, staging / f"issuer-{symbol}.parquet")
            if audit.errors:
                raise ValueError("Issuer audit failed; dividends require review")
            raw = pq.read_table(destination / "raw.parquet").to_pylist()
            first = min(r["received_at"] for r in raw)
            last = max(r["received_at"] for r in raw)
            if last > now or now - first > timedelta(minutes=plan.max_capture_age_minutes):
                raise ValueError("Input capture is stale or in the future")
            if registered is not None and first <= registered:
                raise ValueError(
                    "New forward inputs must be received after observation registration"
                )
        quality = audit_bars(
            destination / "bars.parquet",
            symbol,
            table["date"][0].as_py(),
            table["date"][-1].as_py(),
            now,
        )
        if quality.errors:
            raise ValueError("Input has missing/unfinished sessions or invalid bars")
        inputs[symbol] = table
        receipts.append(
            {
                "symbol": symbol,
                "first_received_at": first,
                "last_received_at": last,
                "scope": "synthetic_drill" if plan.mode == "drill" else "observed_daily_proxy",
            }
        )
    write_table(pa.Table.from_pylist(receipts, schema=RECEIPT_SCHEMA), staging / "receipts.parquet")
    dates = inputs[plan.symbols[0]]["date"].to_pylist()
    if any(t["date"].to_pylist() != dates for t in inputs.values()):
        raise ValueError("Symbols must have identical complete sessions")
    expected = latest_completed_session(now, provider_daily=plan.mode != "drill")
    if dates[-1] != expected:
        raise ValueError(f"Missing latest admissible session {expected}")
    return inputs, max(r["last_received_at"] for r in receipts)


def _qualify(
    study: Path | None,
    staging: Path,
    policy: StudyConfig,
    plan: Observation,
    *,
    required_engine: str | None = None,
) -> None:
    digest = required_engine if required_engine is not None else engine_digest()
    _require_engine(digest)
    if plan.mode not in {"qualified_strategy", "shadow_research"}:
        if study is not None:
            raise ValueError("Research evidence requires a strategy observation mode")
        return
    if study is None:
        raise ValueError("Strategy observation requires registered research evidence")
    from invest.research import eligibility, verify_study

    destination = staging / "qualification"
    shutil.copytree(study, destination)
    verify_inventory(destination)
    manifest = pq.read_table(destination / "manifest.parquet").to_pylist()[0]
    if plan.mode == "qualified_strategy":
        if not manifest["m3_research_eligible"] or manifest["scope"] != "historical_research_only":
            raise ValueError("M2 candidate did not pass the research gate")
    elif manifest["scope"] != "known_history_research_only" or manifest["m3_research_eligible"]:
        raise ValueError(
            "Shadow research requires explicit known-history evidence, without qualification"
        )
    if manifest["engine_sha256"] != digest:
        raise ValueError("Research qualification engine differs from forward registration")
    frozen, registered, _ = read_registration(
        destination / "registration.parquet", required_engine=digest
    )
    known_history = registration_known_history((destination / "registration.parquet").read_bytes())
    if known_history != (plan.mode == "shadow_research"):
        raise ValueError("Research exposure declaration differs from observation purpose")
    admission = pq.read_table(destination / "admission.parquet")
    admitted = {r["symbol"] for r in admission.to_pylist() if r["admitted"]}
    if (
        frozen != policy
        or set(plan.symbols) != admitted
        or manifest["selected_candidate"] != plan.candidate
        or plan.start_session <= policy.holdout_end
    ):
        raise ValueError("Observation differs from the qualified policy/candidate/universe")
    verify_study(destination)
    gates = eligibility(
        pq.read_table(destination / "comparison.parquet").to_pylist(),
        plan.signal,
        policy,
        False,
        admission,
        registered,
    )
    if plan.mode == "qualified_strategy" and not all(gates["passed"].to_pylist()):
        raise ValueError("Recomputed M2 research gates failed")
    _require_engine(digest)


def init_forward(
    account: Path,
    observation: Path,
    policy_path: Path,
    sources: dict[str, Path],
    *,
    issuer: Path | None = None,
    study: Path | None = None,
    at: datetime | None = None,
) -> Path:
    digest = engine_digest()
    observation_body, policy_body = observation.read_bytes(), policy_path.read_bytes()
    plan, policy = parse_observation(observation_body), parse_study(policy_body)
    now = _at(plan, at)
    if set(plan.symbols) - set(policy.symbols):
        raise ValueError("Observation symbols must come from the frozen policy")
    if plan.signal.is_strategy and (
        plan.signal.lookback not in policy.lookbacks
        or plan.signal.kind not in policy.candidate_kinds
    ):
        raise ValueError("Candidate window was not registered in the policy")
    if regular_sessions(plan.start_session, plan.start_session).num_rows != 1:
        raise ValueError("Observation must start on an XNYS session")
    if now >= regular_sessions(plan.start_session, plan.start_session)["open_at"][0].as_py():
        raise ValueError("Observation must be registered before its first session opens")
    if account.exists():
        raise ValueError("Forward account already exists; never reset a capital account")
    account.parent.mkdir(parents=True, exist_ok=True)
    working = account.parent / f".{account.name}.{uuid.uuid4().hex}.init"
    working.mkdir()
    try:
        staging = _staging(working)
        _qualify(study, staging, policy, plan, required_engine=digest)
        _require_engine(digest)
        inputs, _ = _inputs(sources, staging, plan, now, issuer, None)
        _require_engine(digest)
        dates = inputs[plan.symbols[0]]["date"].to_pylist()
        if len(dates) < policy.warmup or next_session(dates[-1])["date"] != plan.start_session:
            raise ValueError("Seed history must cover warmup through the session before start")
        now = _at(plan, at)
        if now >= regular_sessions(plan.start_session, plan.start_session)["open_at"][0].as_py():
            raise ValueError("Registration missed its first-session open; choose a future start")
        account_id = uuid.uuid4().hex
        state = ForwardState(
            policy.initial_cash,
            policy.initial_cash,
            "active",
            "active",
            dates[-1],
            0,
            {s: Account(ZERO) for s in plan.symbols},
        )
        write_table(
            pa.Table.from_pylist(
                [
                    {
                        "account_id": account_id,
                        "registered_at": now,
                        "engine_sha256": digest,
                        "observation_body": observation_body,
                        "policy_body": policy_body,
                        "python_version": sys.version.split()[0],
                        "package_version": version("wayslog-invest"),
                    }
                ],
                schema=REGISTRATION_SCHEMA,
            ),
            staging / "registration.parquet",
        )
        write_table(
            pa.Table.from_pylist(
                [
                    {"file": p.name, "body": p.read_bytes()}
                    for p in sorted(Path(__file__).parent.glob("*.py"))
                ],
                schema=pa.schema([("file", pa.string()), ("body", pa.binary())]),
            ),
            staging / "engine-source.parquet",
        )
        write_table(
            pa.Table.from_pylist(
                [{"package": d.metadata["Name"], "version": d.version} for d in distributions()],
                schema=pa.schema([("package", pa.string()), ("version", pa.string())]),
            ),
            staging / "dependencies.parquet",
        )
        for symbol, table in inputs.items():
            write_table(table, staging / "accepted" / f"{symbol}.parquet")
        _publish(
            working,
            staging,
            [],
            account_id,
            now,
            "register",
            "operator",
            f"{plan.mode}; {plan.sessions} sessions; minimum fills={plan.minimum_fills}",
            state.tables(),
        )
        _require_engine(digest)
        working.rename(account)
    except BaseException:
        shutil.rmtree(working, ignore_errors=True)
        raise
    return account / "journal" / "00000000"


def _superseded(
    runs: list[Path], state: ForwardState, expected_head: str | None
) -> dict[str, Any] | None:
    head = checksum(runs[-1] / "files.parquet")
    if expected_head is not None and expected_head != head:
        return {
            "updated": False,
            "stale": True,
            "status": state.operations,
            "run": str(runs[-1]),
            "head": head,
        }
    return None


def _record_failure(
    account: Path,
    staging: Path,
    runs: list[Path],
    plan: Observation,
    state: ForwardState,
    reason: str,
    at: datetime | None,
) -> dict[str, Any]:
    # Validation/acquisition may have crossed an open. Only still-future intents
    # can be cancelled at the actual failure decision time.
    now = _at(plan, at)
    account_id = _guard(runs, now)
    state.operations = "paused"
    cancelled = cancel_future(state, now, "data_failure")
    directory = _publish(
        account,
        staging,
        runs,
        account_id,
        now,
        "data_failure",
        "scheduler",
        reason,
        {**state.tables(), "outcomes": cancelled},
    )
    return {"updated": True, "status": "paused", "error": reason, "run": str(directory)}


def fail_forward(account: Path, reason: str, *, expected_head: str) -> dict[str, Any]:
    """Apply an acquisition failure only to the journal version that requested it."""
    with account_lock(account):
        runs, plan, _, state = _load(account)
        stale = _superseded(runs, state, expected_head)
        if stale is not None:
            return stale
        if state.operations in {"stopped", "completed"}:
            raise ValueError("Observation is stopped/completed; retain account history")
        staging = _staging(account)
        try:
            return _record_failure(account, staging, runs, plan, state, reason, None)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def run_forward(
    account: Path,
    sources: dict[str, Path],
    *,
    issuer: Path | None = None,
    at: datetime | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    with account_lock(account):
        runs, plan, policy, state = _load(account)
        stale = _superseded(runs, state, expected_head)
        if stale is not None:
            return stale
        now = _at(plan, at)
        account_id = _guard(runs, now)
        if state.operations in {"stopped", "completed"}:
            raise ValueError("Observation is stopped/completed; retain account history")
        old = _history(runs, plan.symbols)
        staging = _staging(account)
        try:
            registered = pq.read_table(runs[0] / "registration.parquet")["registered_at"][0].as_py()
            try:
                inputs, received = _inputs(sources, staging, plan, now, issuer, registered)
                for s, history in old.items():

                    def stable(t: pa.Table) -> dict[bytes, bytes]:
                        return {
                            k: v
                            for k, v in (t.schema.metadata or {}).items()
                            if k not in {b"dataset_id", b"observed_at"}
                        }

                    if (
                        inputs[s].num_rows < history.num_rows
                        or not inputs[s]
                        .slice(0, history.num_rows)
                        .equals(history, check_metadata=False)
                        or stable(inputs[s]) != stable(history)
                    ):
                        raise ValueError("Data revision detected; original decisions are preserved")
            except (ValueError, OSError) as exc:
                return _record_failure(account, staging, runs, plan, state, str(exc), at)
            new_count = inputs[plan.symbols[0]].num_rows - old[plan.symbols[0]].num_rows
            if new_count == 0:
                shutil.rmtree(staging)
                return {"updated": False, "status": state.operations, "run": str(runs[-1])}
            reason = "Latest close observed; opening fills are delayed accounting"
            if new_count > 1:
                state.operations = "paused"
                reason = "Missed sessions: account for existing intents only; review before resume"
            now = _at(plan, at)
            _guard(runs, now)
            tables = advance(state, inputs, policy, plan, account_id, now, received)
            combined = {name: _collect(runs, name, tables[name]) for name in HISTORY_TABLES}
            audit, attribution, closed = audit_portfolio(inputs, as_portfolio(combined), policy)
            if "error" in audit["status"].to_pylist():
                raise ValueError("Independent forward reconciliation failed; no commit")
            tables.update(reconciliation=audit, attribution=attribution, closed_trades=closed)
            for symbol, table in inputs.items():
                write_table(table, staging / "accepted" / f"{symbol}.parquet")
            directory = _publish(
                account, staging, runs, account_id, now, "daily", "scheduler", reason, tables
            )
            return {
                "updated": True,
                "status": state.operations,
                "risk_status": state.risk_status,
                "run": str(directory),
                "account_id": account_id,
            }
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def control_forward(
    account: Path,
    action: str,
    actor: str,
    reason: str,
    *,
    at: datetime | None = None,
) -> Path:
    if action not in {"pause", "resume", "stop"} or not actor.strip() or not reason.strip():
        raise ValueError("Control requires pause/resume/stop, actor and reason")
    with account_lock(account):
        runs, plan, _, state = _load(account)
        now = _at(plan, at)
        account_id = _guard(runs, now)
        if state.operations in {"stopped", "completed"}:
            raise ValueError("Stopped/completed observation cannot be resumed")
        if action == "resume":
            if state.operations != "paused":
                raise ValueError("Only a paused observation can resume")
            if state.last_session != latest_completed_session(
                now, provider_daily=plan.mode != "drill"
            ):
                raise ValueError("Catch up accounting with valid data before resuming")
            # Operational recovery NEVER clears the capital risk latch.
            state.operations = "active"
        elif action == "stop":
            if state.pending or any(a.shares or a.receivables for a in state.ledgers.values()):
                raise ValueError(
                    "Cannot stop with unresolved orders, positions or receivables; pause instead"
                )
            state.operations = "stopped"
        else:
            state.operations = "paused"
        outcomes = cancel_future(state, now, f"{action}: {reason}") if action != "resume" else None
        staging = _staging(account)
        try:
            return _publish(
                account,
                staging,
                runs,
                account_id,
                now,
                action,
                actor,
                reason,
                {**state.tables(), **({"outcomes": outcomes} if outcomes is not None else {})},
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def forward_status(account: Path, *, at: datetime | None = None) -> dict[str, Any]:
    with account_lock(account):
        runs, plan, _, state = _load(account)
        now = _at(plan, at)
        registration = pq.read_table(runs[0] / "registration.parquet").to_pylist()[0]
        fills = sum(
            pq.read_metadata(r / "trades.parquet").num_rows
            for r in runs
            if (r / "trades.parquet").exists()
        )
        end = regular_sessions(
            plan.start_session, plan.start_session + timedelta(days=plan.sessions * 3 + 14)
        )["date"][plan.sessions - 1].as_py()
        decision_sessions = {
            d
            for run in runs
            if (run / "signals.parquet").exists()
            for d in pq.read_table(run / "signals.parquet")["date"].to_pylist()
            if d <= end
        }
        target = latest_completed_session(now, provider_daily=plan.mode != "drill")
        missing = (
            regular_sessions(state.last_session + timedelta(days=1), target).num_rows
            if target > state.last_session
            else 0
        )
        next_day = next_session(state.last_session)["date"]
        return {
            "account_id": registration["account_id"],
            "mode": plan.mode,
            "formal_strategy_qualified": plan.mode == "qualified_strategy",
            "candidate": plan.candidate,
            "operations": state.operations,
            "risk_status": state.risk_status,
            "cash": str(state.cash),
            "peak": str(state.peak),
            "last_session": str(state.last_session),
            "sessions": state.sessions,
            "registered_sessions": plan.sessions,
            "observation_end_session": str(end),
            "decision_sessions": len(decision_sessions),
            "fills": fills,
            "minimum_fills": plan.minimum_fills,
            "coverage_met": (
                state.operations == "completed"
                and len(decision_sessions) >= plan.sessions
                and fills >= plan.minimum_fills
            ),
            "pending_orders": len(state.pending),
            "missing_sessions": missing,
            "next_capture_after": daily_capture_after(next_day).isoformat(),
            "decision_deadline": next_session(next_day)["open_at"].isoformat(),
            "head": checksum(runs[-1] / "files.parquet"),
            "commits": len(runs),
            "registration_engine_sha256": registration["engine_sha256"],
            "active_engine_sha256": pq.read_table(runs[-1] / "journal.parquet")["engine_sha256"][
                0
            ].as_py(),
            "migrations": sum((r / "migration.parquet").exists() for r in runs),
            "engine_matches": pq.read_table(runs[-1] / "journal.parquet")["engine_sha256"][
                0
            ].as_py()
            == engine_digest(),
            "execution_basis": "delayed_daily_open_proxy",
        }


def verify_forward(account: Path) -> dict[str, Any]:
    with account_lock(account):
        runs, plan, policy, state = _load(account)
        _guard(runs, pq.read_table(runs[-1] / "journal.parquet")["recorded_at"][0].as_py())
        # Rebuild exact risk anchors and pending intents, not just cash/market value.
        seed = _history(runs[:1], plan.symbols)
        replay = ForwardState(
            policy.initial_cash,
            policy.initial_cash,
            "active",
            "active",
            seed[plan.symbols[0]]["date"][-1].as_py(),
            0,
            {s: Account(ZERO) for s in plan.symbols},
        )
        registration = pq.read_table(runs[0] / "registration.parquet").to_pylist()[0]
        epoch = validate_versions(runs, registration["engine_sha256"])
        if epoch:
            boundary = pq.read_table(runs[epoch] / "migration.parquet").to_pylist()[0]
            verify_archived(runs[:epoch], boundary["from_engine_sha256"])
            replay = ForwardState.load(
                {
                    name: pq.read_table(runs[epoch] / f"{name}.parquet")
                    for name in ("state", "ledgers", "pending")
                }
            )
        for i, run in enumerate(runs):
            if i < epoch:
                continue
            journal = pq.read_table(run / "journal.parquet").to_pylist()[0]
            expected = replay.tables()
            if i > epoch:
                kind, now = journal["kind"], journal["recorded_at"]
                if kind == "daily":
                    inputs = _history(runs[: i + 1], plan.symbols)
                    previous = _history(runs[:i], plan.symbols)
                    if inputs[plan.symbols[0]].num_rows - previous[plan.symbols[0]].num_rows > 1:
                        replay.operations = "paused"
                    received = max(
                        pq.read_table(run / "receipts.parquet")["last_received_at"].to_pylist()
                    )
                    expected = advance(
                        replay, inputs, policy, plan, journal["account_id"], now, received
                    )
                elif kind in {"data_failure", "pause", "restore"}:
                    if replay.operations not in {"stopped", "completed"}:
                        replay.operations = "paused"
                    cancel_future(replay, now, journal["reason"])
                    expected = replay.tables()
                elif kind in {"resume", "stop"}:
                    replay.operations = "active" if kind == "resume" else "stopped"
                    expected = replay.tables()
                else:
                    raise ValueError("Unknown forward journal event")
            for name, table in expected.items():
                if not table.equals(pq.read_table(run / f"{name}.parquet"), check_metadata=True):
                    raise ValueError(f"Forward event replay mismatch: {run.name}/{name}")
        checks = 0
        daily = [r for r in runs if (r / "equity.parquet").exists()]
        if daily:
            combined = {name: _collect(runs, name) for name in HISTORY_TABLES}
            audit, _, _ = audit_portfolio(
                _history(runs, plan.symbols), as_portfolio(combined), policy
            )
            if "error" in audit["status"].to_pylist():
                raise ValueError("Forward ledger reconciliation failed")
            checks = audit.num_rows
            intents = {r["order_id"]: r for r in combined["orders"].to_pylist()}
            outcomes = combined["outcomes"]["order_id"].to_pylist()
            if len(intents) != combined["orders"].num_rows or len(outcomes) != len(set(outcomes)):
                raise ValueError("Duplicate forward order or terminal outcome")
            for fill in combined["trades"].to_pylist():
                intent = intents[fill["order_id"]]
                if not (
                    intent["input_received_at"]
                    <= intent["decided_at"]
                    < fill["proxy_at"]
                    <= fill["recorded_at"]
                    and fill["decided_at"] == intent["decided_at"]
                ):
                    raise ValueError("Forward decision/fill chronology failed")
            last = combined["equity"].to_pylist()[-1]
            if state.cash != last["cash"] or state.peak != max(
                policy.initial_cash, *combined["equity"]["equity"].to_pylist()
            ):
                raise ValueError("Continuous capital cash/peak mismatch")
        return {
            "commits": len(runs),
            "reconciliation_checks": checks,
            "status": "verified",
            "head": checksum(runs[-1] / "files.parquet"),
        }
