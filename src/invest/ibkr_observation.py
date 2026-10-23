"""Read-only IBKR cash observations; no strategy orders or broker-capital mapping.

Each successful session proves that its IBKR data was actually received between
XNYS close + 60 minutes and the next XNYS open. Later history revisions do not
restate earlier observations. The project cash is a fixed USD 5,000 fixture.
"""

import json
import shutil
import subprocess
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from invest.datasets import checksum
from invest.engine import engine_digest
from invest.ibkr_data import SCHEMAS
from invest.ibkr_models import read_config, timestamp
from invest.ibkr_store import EventStore, publish
from invest.quality import latest_completed_session, regular_sessions
from invest.research_registry import seal

CASH = Decimal("5000.00")
SESSION_COUNT = 60
STAMP = pa.timestamp("us", tz="UTC")
REGISTRATION_SCHEMA = pa.schema(
    [
        ("account_id", pa.string()),
        ("registered_at", STAMP),
        ("source", pa.string()),
        ("purpose", pa.string()),
        ("broker_account", pa.string()),
        ("initial_cash", pa.decimal128(20, 2)),
        ("previous_session", pa.date32()),
        ("sessions", pa.int64()),
        ("engine_sha256", pa.string()),
        ("sdk_python", pa.string()),
        ("sdk_runner", pa.string()),
        ("config_body", pa.binary()),
        ("preflight_capture", pa.string()),
        ("preflight_started_at", STAMP),
        ("actor", pa.string()),
        ("reason", pa.string()),
    ],
    metadata={b"schema_version": b"invest.ibkr.cash-observation.registration.v1"},
)
SCHEDULE_SCHEMA = pa.schema(
    [
        ("session", pa.date32()),
        ("open_at", STAMP),
        ("capture_after", STAMP),
        ("deadline", STAMP),
    ],
    metadata={b"schema_version": b"invest.ibkr.cash-observation.schedule.v1"},
)
INVOCATION_SCHEMA = pa.schema(
    [
        ("started_at", STAMP),
        ("finished_at", STAMP),
        ("outcome", pa.string()),
        ("returncode", pa.int64()),
        ("stdout", pa.binary()),
        ("stderr", pa.binary()),
    ],
    metadata={b"schema_version": b"invest.ibkr.cash-observation.sdk-invocation.v1"},
)


def clock() -> datetime:
    return datetime.now(UTC)


def _invocation(
    output: Path,
    started: datetime,
    outcome: str,
    returncode: int | None,
    stdout: bytes | str | None,
    stderr: bytes | str | None,
) -> None:
    """Keep SDK diagnostics private even when no broker capture batch was published."""
    directory = output / "invocations"
    directory.mkdir(parents=True, exist_ok=True)
    row = {
        "started_at": started,
        "finished_at": clock(),
        "outcome": outcome,
        "returncode": returncode,
        "stdout": stdout.encode() if isinstance(stdout, str) else stdout or b"",
        "stderr": stderr.encode() if isinstance(stderr, str) else stderr or b"",
    }
    publish(
        pa.Table.from_pylist([row], schema=INVOCATION_SCHEMA),
        directory / f"{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex}.parquet",
    )


def _capture(sdk_python: Path, runner: Path, config: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    started = clock()
    try:
        process = subprocess.run(
            [
                str(sdk_python),
                str(runner),
                "capture",
                "--config",
                str(config),
                "--output",
                str(output),
            ],
            capture_output=True,
            timeout=240,
            check=False,
        )
        _invocation(output, started, "returned", process.returncode, process.stdout, process.stderr)
        if process.returncode:
            raise ValueError("IBKR read-only capture failed; inspect protected capture data")
        result = json.loads(process.stdout)
        path = Path(result["capture"])
        if not path.resolve().is_relative_to(output.resolve()) or not path.is_dir():
            raise ValueError("IBKR capture returned an unexpected destination")
        return path
    except subprocess.TimeoutExpired as exc:
        _invocation(output, started, "timeout", None, exc.stdout, exc.stderr)
        raise ValueError("IBKR read-only capture could not complete") from exc
    except OSError as exc:
        _invocation(output, started, "launch_error", None, b"", str(exc))
        raise ValueError("IBKR read-only capture could not complete") from exc
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError("IBKR read-only capture could not complete") from exc


def _table(folder: Path, name: str) -> pa.Table:
    table = pq.read_table(folder / f"{name}.parquet")
    if not table.schema.equals(SCHEMAS[name], check_metadata=False):
        raise ValueError("IBKR observation capture has an invalid table schema")
    return table


def _validate_capture(
    folder: Path,
    config: Path,
    session: date,
    started: datetime,
    finished: datetime,
    broker_account: str | None = None,
) -> dict[str, Any]:
    spec = read_config(config)
    manifest = _table(folder, "capture")
    if manifest.num_rows != 1:
        raise ValueError("IBKR observation requires one capture manifest")
    row: dict[str, Any] = manifest.to_pylist()[0]
    if (
        row["source"] != "ibkr"
        or row["environment"] != "paper"
        or not row["account"].startswith("DU")
        or row["client_id"] != spec.client_id
        or (broker_account is not None and row["account"] != broker_account)
        or not row["complete"]
        or row["engine_sha256"] != engine_digest()
        or not started <= row["captured_at"] <= finished
        or finished - row["captured_at"] > timedelta(minutes=5)
    ):
        raise ValueError("IBKR capture is incomplete, stale or has a different Paper identity")
    for name in SCHEMAS:
        table = _table(folder, name)
        metadata = table.schema.metadata or {}
        if (
            metadata.get(b"source") != b"ibkr"
            or metadata.get(b"environment") != b"paper"
            or metadata.get(b"account") != row["account"].encode()
        ):
            raise ValueError("IBKR capture tables have inconsistent provenance")
    if "error" in _table(folder, "quality")["status"].to_pylist():
        raise ValueError("IBKR observation capture did not pass its quality checks")
    bars = _table(folder, "historical").to_pylist()
    for symbol in spec.symbols:
        selected = [r for r in bars if r["symbol"] == symbol and r["session"] == session]
        if len(selected) != 1 or any(
            r["bar_size"] != "1 day" or r["currency"] != "USD" or not r["use_rth"] for r in selected
        ):
            raise ValueError("IBKR observation lacks the required regular-session daily bar")
    return row


def _schedule(now: datetime) -> tuple[date, pa.Table]:
    rows = regular_sessions(now.date() - timedelta(days=14), now.date() + timedelta(days=220))
    future = [row for row in rows.to_pylist() if row["open_at"] > now]
    if len(future) <= SESSION_COUNT:
        raise ValueError("Insufficient future XNYS schedule for the observation")
    previous = max(row["date"] for row in rows.to_pylist() if row["date"] < future[0]["date"])
    return previous, pa.Table.from_pylist(
        [
            {
                "session": row["date"],
                "open_at": row["open_at"],
                "capture_after": row["close_at"] + timedelta(minutes=60),
                "deadline": future[index + 1]["open_at"],
            }
            for index, row in enumerate(future[:SESSION_COUNT])
        ],
        schema=SCHEDULE_SCHEMA,
    )


def initialize(
    account: Path,
    config_path: Path,
    sdk_python: Path,
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    """Register a new cash observation after an actual IBKR preflight, never reset one."""
    if not actor.strip() or not reason.strip():
        raise ValueError("A new observation requires its actor and explicit restart reason")
    config = read_config(config_path)
    if (
        config.client_id != 73
        or config.symbols != ("SPY", "XLF")
        or config.bar_size != "1 day"
        or config.duration != "5 D"
        or config.what_to_show != "TRADES"
        or not config.use_rth
    ):
        raise ValueError("Cash observation requires client 73 and SPY/XLF regular daily TRADES/5 D")
    account.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(account.parent / f".{account.name}.initialize.lock", timeout=15):
        if account.exists():
            registered, _, _ = _load(account)
            if registered["config_body"] != config_path.read_bytes() or registered[
                "sdk_python"
            ] != str(sdk_python.absolute()):
                raise ValueError("An existing cash observation cannot be reconfigured or reset")
            return status(account)
        staging = account.parent / f".{account.name}.{uuid.uuid4().hex}.init"
        staging.mkdir()
        runner = Path(__file__).resolve().parents[2] / "integrations" / "ibkr" / "run.py"
        try:
            shutil.copyfile(config_path, staging / "config.toml")
            started = clock()
            capture = _capture(
                sdk_python.absolute(),
                runner,
                staging / "config.toml",
                account.parent / (account.name + "-captures") / "preflight",
            )
            now = clock()
            if now < started:
                raise ValueError("IBKR observation clock moved backwards")
            manifest = _validate_capture(
                capture, staging / "config.toml", latest_completed_session(now), started, now
            )
            validated_at = clock()
            if validated_at < now:
                raise ValueError("IBKR observation clock moved backwards")
            if latest_completed_session(validated_at) != latest_completed_session(
                now
            ) or validated_at - manifest["captured_at"] > timedelta(minutes=5):
                raise ValueError("IBKR preflight expired during validation; retry registration")
            now = validated_at
            previous, schedule = _schedule(now)
            row = {
                "account_id": uuid.uuid4().hex,
                "registered_at": now,
                "source": "ibkr",
                "purpose": "cash_operations_only",
                "broker_account": manifest["account"],
                "initial_cash": CASH,
                "previous_session": previous,
                "sessions": SESSION_COUNT,
                "engine_sha256": engine_digest(),
                "sdk_python": str(sdk_python.absolute()),
                "sdk_runner": str(runner),
                "config_body": (staging / "config.toml").read_bytes(),
                "preflight_capture": str(capture.absolute()),
                "preflight_started_at": started,
                "actor": actor,
                "reason": reason,
            }
            publish(
                pa.Table.from_pylist([row], schema=REGISTRATION_SCHEMA),
                staging / "registration.parquet",
            )
            publish(schedule, staging / "schedule.parquet")
            store = EventStore(staging)
            with store.locked():
                store.append(
                    "register",
                    "registration",
                    {"account_id": row["account_id"], "cash": CASH, "peak": CASH},
                    now,
                )
            if clock() >= schedule["open_at"][0].as_py():
                raise ValueError("IBKR observation registration crossed its first open; retry")
            staging.rename(account)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return status(account)


def _load(account: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    registration = pq.read_table(account / "registration.parquet")
    schedule = pq.read_table(account / "schedule.parquet")
    if (
        registration.num_rows != 1
        or not registration.schema.equals(REGISTRATION_SCHEMA, check_metadata=True)
        or not schedule.schema.equals(SCHEDULE_SCHEMA, check_metadata=True)
        or schedule.num_rows != SESSION_COUNT
    ):
        raise ValueError("Invalid IBKR cash observation registration")
    row: dict[str, Any] = registration.to_pylist()[0]
    if (
        row["source"] != "ibkr"
        or row["purpose"] != "cash_operations_only"
        or row["initial_cash"] != CASH
        or row["sessions"] != SESSION_COUNT
        or (account / "config.toml").read_bytes() != row["config_body"]
    ):
        raise ValueError("IBKR cash observation registration or cash basis changed")
    previous, expected_schedule = _schedule(row["registered_at"])
    if previous != row["previous_session"] or not schedule.equals(expected_schedule):
        raise ValueError("IBKR cash observation window differs from registration")
    events = EventStore(account).read()
    if (
        not events
        or events[0]["kind"] != "register"
        or events[0]["recorded_at"] != row["registered_at"]
        or events[0]["payload"].get("account_id") != row["account_id"]
    ):
        raise ValueError("IBKR observation registration event is missing or inconsistent")
    days = {r["session"].isoformat(): r for r in schedule.to_pylist()}
    terminal: set[str] = set()
    for event in events:
        body = event["payload"]
        if Decimal(body.get("cash", "0")) != CASH or Decimal(body.get("peak", "0")) != CASH:
            raise ValueError("IBKR cash observation cannot change project funds or high-water mark")
        if event["kind"] not in {"register", "observation", "missed", "failure"}:
            raise ValueError("Unknown IBKR cash observation event")
        if event["kind"] in {"observation", "missed"}:
            session = body.get("session", "")
            if session not in days or session in terminal:
                raise ValueError("IBKR observation has an invalid or duplicate terminal session")
            day = days[session]
            if event["kind"] == "observation":
                captured = timestamp(body["captured_at"])
                if not day["capture_after"] <= captured <= event["recorded_at"] < day["deadline"]:
                    raise ValueError(
                        "An IBKR session was not observed within its registered window"
                    )
            elif event["recorded_at"] < day["deadline"]:
                raise ValueError("An IBKR observation cannot be marked missed before its deadline")
            terminal.add(session)
    return row, schedule.to_pylist(), events


def _head(account: Path, events: list[dict[str, Any]]) -> str:
    return checksum(account / "events" / f"{events[-1]['sequence']:08d}.parquet")


def _status(account: Path, now: datetime) -> dict[str, Any]:
    registration, days, events = _load(account)
    if now < events[-1]["recorded_at"]:
        raise ValueError("IBKR observation clock moved backwards")
    outcomes = {
        e["payload"]["session"]: e for e in events if e["kind"] in {"observation", "missed"}
    }
    remaining = [day for day in days if day["session"].isoformat() not in outcomes]
    timely = sum(e["kind"] == "observation" for e in outcomes.values())
    missed = sum(e["kind"] == "missed" for e in outcomes.values())
    last_session = max(
        (date.fromisoformat(s) for s in outcomes), default=registration["previous_session"]
    )
    next_day = remaining[0] if remaining else None
    return {
        "account_id": registration["account_id"],
        "source": "ibkr",
        "mode": "cash_observation",
        "candidate": "cash",
        "formal_strategy_qualified": False,
        "execution_basis": "read_only_ibkr_cash_operations",
        "operations": "active" if remaining else "completed",
        "risk_status": "active",
        "cash": str(CASH),
        "peak": str(CASH),
        "sessions": timely,
        "decision_sessions": timely,
        "missed_sessions": missed,
        "registered_sessions": SESSION_COUNT,
        "last_session": str(last_session),
        "observation_start_session": str(days[0]["session"]),
        "observation_end_session": str(days[-1]["session"]),
        "missing_sessions": sum(day["capture_after"] <= now for day in remaining),
        "next_capture_after": next_day["capture_after"].isoformat() if next_day else None,
        "decision_deadline": next_day["deadline"].isoformat() if next_day else None,
        "fills": 0,
        "pending_orders": 0,
        "coverage_met": timely == SESSION_COUNT,
        "head": _head(account, events),
        "commits": len(events),
        "engine_matches": registration["engine_sha256"] == engine_digest(),
        "registration_engine_sha256": registration["engine_sha256"],
    }


def status(account: Path) -> dict[str, Any]:
    if not (account / "registration.parquet").is_file():
        raise ValueError("IBKR cash observation does not exist")
    with EventStore(account).locked():
        return _status(account, clock())


def verify(account: Path) -> dict[str, Any]:
    with EventStore(account).locked():
        registration, _, events = _load(account)
        if registration["engine_sha256"] != engine_digest():
            raise ValueError("IBKR cash observation engine changed; retain the registered runtime")
        _validate_capture(
            Path(registration["preflight_capture"]),
            account / "config.toml",
            latest_completed_session(registration["registered_at"]),
            registration["preflight_started_at"],
            registration["registered_at"],
            registration["broker_account"],
        )
        checks = 4
        for event in events:
            if event["kind"] != "observation":
                continue
            body = event["payload"]
            manifest = _validate_capture(
                Path(body["capture"]),
                account / "config.toml",
                date.fromisoformat(body["session"]),
                timestamp(body["started_at"]),
                event["recorded_at"],
                registration["broker_account"],
            )
            if manifest["captured_at"] != timestamp(body["captured_at"]):
                raise ValueError("Observation time differs from its original IBKR capture")
            checks += 3
        return {"head": _head(account, events), "reconciliation_checks": checks, "cash": str(CASH)}


def job(account: Path, data_root: Path, *, attempts: int = 2) -> dict[str, Any]:
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError("IBKR observation attempts must be between 1 and 5")
    with EventStore(account).locked() as store:
        registration, days, events = _load(account)
        now = clock()
        if now < events[-1]["recorded_at"]:
            raise ValueError("IBKR observation clock moved backwards")
        if registration["engine_sha256"] != engine_digest():
            raise ValueError("IBKR cash observation engine changed; retain the registered runtime")
        done = {e["payload"]["session"] for e in events if e["kind"] in {"observation", "missed"}}
        updated, missed = False, 0
        for day in days:
            session = day["session"].isoformat()
            if session in done or now < day["capture_after"]:
                continue
            if now >= day["deadline"]:
                store.append(
                    "missed",
                    "session:" + session,
                    {
                        "session": session,
                        "cash": CASH,
                        "peak": CASH,
                        "reason": "No timely IBKR observation before next XNYS open",
                    },
                    now,
                )
                updated, missed = True, missed + 1
                continue
            for attempt in range(attempts):
                started = clock()
                try:
                    capture = _capture(
                        Path(registration["sdk_python"]),
                        Path(registration["sdk_runner"]),
                        account / "config.toml",
                        data_root / registration["account_id"],
                    )
                    finished = clock()
                    manifest = _validate_capture(
                        capture,
                        account / "config.toml",
                        day["session"],
                        started,
                        finished,
                        registration["broker_account"],
                    )
                    committed_at = clock()
                    if committed_at < finished:
                        raise ValueError("IBKR observation clock moved backwards")
                    finished = committed_at
                    if finished >= day["deadline"]:
                        store.append(
                            "missed",
                            "session:" + session,
                            {
                                "session": session,
                                "cash": CASH,
                                "peak": CASH,
                                "capture": str(capture.absolute()),
                                "reason": "IBKR capture completed after the next XNYS open",
                            },
                            finished,
                        )
                        updated, missed = True, missed + 1
                        break
                    store.append(
                        "observation",
                        "session:" + session,
                        {
                            "session": session,
                            "cash": CASH,
                            "peak": CASH,
                            "capture": str(capture.absolute()),
                            "started_at": started,
                            "captured_at": manifest["captured_at"],
                        },
                        finished,
                    )
                    updated = True
                    break
                except (OSError, ValueError) as exc:
                    failed = clock()
                    if failed < started:
                        raise ValueError("IBKR observation clock moved backwards") from exc
                    store.append(
                        "failure",
                        "failure:" + uuid.uuid4().hex,
                        {
                            "session": session,
                            "cash": CASH,
                            "peak": CASH,
                            "error": "IBKR observation acquisition or quality check failed",
                            "exception_type": type(exc).__name__,
                        },
                        failed,
                    )
                    if attempt == attempts - 1:
                        return {
                            "updated": updated,
                            "due": True,
                            "status": "active",
                            "error": (
                                "IBKR observation acquisition or quality check failed; "
                                "a later run can retry"
                            ),
                        }
        result = {
            "updated": updated,
            "due": updated,
            "status": _status(account, clock())["operations"],
        }
        if missed:
            result["error"] = (
                "Missed observation sessions retained; the registered window was not extended"
            )
        return result


def backup(account: Path, output: Path) -> dict[str, Any]:
    """Keep a local immutable snapshot; referenced market batches remain in data_root."""
    with EventStore(account).locked():
        _, _, events = _load(account)
        if output.exists() or output.resolve().is_relative_to(account.resolve()):
            raise ValueError("IBKR observation backup requires a new path outside the account")
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = output.parent / f".{output.name}.{uuid.uuid4().hex}.backup"
        try:
            shutil.copytree(
                account, staging, ignore=shutil.ignore_patterns(".writer.lock", ".*.tmp")
            )
            manifest = {"head": _head(account, events), "commits": len(events)}
            publish(pa.Table.from_pylist([manifest]), staging / "backup.parquet")
            seal(staging)
            staging.rename(output)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {"backup": str(output), **manifest}
