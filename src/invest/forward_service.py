"""Durable one-shot service receipts, reconciliation, backups and an independent watchdog."""

import hashlib
import os
import re
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock, Timeout

from invest import forward
from invest.forward import forward_status, verify_forward
from invest.forward_ops import backup_forward, forward_job
from invest.notifications import send_telegram, telegram_recipient
from invest.research_registry import verify_inventory, write_table

STAMP = pa.timestamp("us", tz="UTC")
SERVICE_SCHEMA = pa.schema(
    [
        ("started_at", STAMP),
        ("finished_at", STAMP),
        ("outcome", pa.string()),
        ("account_id", pa.string()),
        ("head", pa.string()),
        ("backup", pa.string()),
        ("last_session", pa.string()),
        ("sessions", pa.int64()),
        ("missing_sessions", pa.int64()),
        ("operations", pa.string()),
        ("risk_status", pa.string()),
        ("updated", pa.bool_()),
        ("due", pa.bool_()),
        ("reconciliation_checks", pa.int64()),
        ("error", pa.string()),
        ("notification", pa.string()),
    ],
    metadata={b"schema_version": b"invest.forward.service.v1"},
)
ALERT_SCHEMA = pa.schema(
    [
        ("recorded_at", STAMP),
        ("kind", pa.string()),
        ("fingerprint", pa.string()),
        ("delivery", pa.string()),
        ("detail", pa.string()),
    ],
    metadata={b"schema_version": b"invest.forward.alert.v1"},
)


@dataclass(frozen=True)
class ServiceConfig:
    account: Path
    data_root: Path
    backup_root: Path
    state_root: Path
    attempts: int = 2
    heartbeat_max_minutes: int = 150
    alert_cooldown_minutes: int = 360
    telegram_required: bool = True
    telegram_token_env: str = "INVEST_TELEGRAM_BOT_TOKEN"
    telegram_uid_env: str = "INVEST_TELEGRAM_ALLOWED_UID"


def read_service_config(path: Path) -> ServiceConfig:
    values = tomllib.loads(path.read_text())
    try:
        for name in ("account", "data_root", "backup_root", "state_root"):
            if not isinstance(values[name], str) or not values[name].strip():
                raise ValueError("Service paths must be nonempty strings")
            value = Path(values[name])
            absolute = value if value.is_absolute() else path.parent / value
            if absolute.is_symlink():
                raise ValueError("Service paths cannot be symbolic links")
            values[name] = absolute.resolve()
        config = ServiceConfig(**values)
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid service configuration fields") from exc
    if (
        type(config.attempts) is not int
        or not 1 <= config.attempts <= 5
        or type(config.heartbeat_max_minutes) is not int
        or not 65 <= config.heartbeat_max_minutes <= 1440
    ):
        raise ValueError("Service attempts or heartbeat interval is outside its bounds")
    if (
        type(config.alert_cooldown_minutes) is not int
        or config.alert_cooldown_minutes < 1
        or type(config.telegram_required) is not bool
    ):
        raise ValueError("Invalid alert cooldown or notification requirement")
    if any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
        for name in (config.telegram_token_env, config.telegram_uid_env)
    ):
        raise ValueError("Telegram environment-variable names are invalid")
    roots = [config.account, config.data_root, config.backup_root, config.state_root]
    if any(
        a.is_relative_to(b) or b.is_relative_to(a)
        for i, a in enumerate(roots)
        for b in roots[i + 1 :]
    ):
        raise ValueError("Account, data, backups and service state must have separate roots")
    return config


def _write_record(root: Path, table: pa.Table, now: datetime) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(root / ".records.lock", timeout=5):
        existing = sorted(root.glob("*.parquet"))
        sequence = int(existing[-1].stem.split("-")[0]) + 1 if existing else 0
        path = root / f"{sequence:012d}-{uuid.uuid4().hex}.parquet"
        temporary = root / f".{path.name}.tmp"
        write_table(table, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.rename(path)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return path


def _latest(root: Path) -> dict[str, Any] | None:
    paths = sorted(root.glob("*.parquet"))
    return dict(pq.read_table(paths[-1]).to_pylist()[0]) if paths else None


def _notify(config: ServiceConfig, kind: str, message: str, now: datetime) -> str:
    fingerprint = hashlib.sha256(f"{kind}:{message}".encode()).hexdigest()
    directory = config.state_root / "alerts"
    sent = [
        r
        for path in directory.glob("*.parquet")
        for r in pq.read_table(path).to_pylist()
        if r["fingerprint"] == fingerprint and r["delivery"] == "sent"
    ]
    delivery, detail = "sent", ""
    if (
        kind != "test"
        and sent
        and now - max(r["recorded_at"] for r in sent)
        < timedelta(minutes=config.alert_cooldown_minutes)
    ):
        delivery = "suppressed"
    else:
        try:
            send_telegram(message, config.telegram_token_env, config.telegram_uid_env)
        except ValueError as exc:
            delivery, detail = "failed", str(exc)
    _write_record(
        directory,
        pa.Table.from_pylist(
            [
                {
                    "recorded_at": now,
                    "kind": kind,
                    "fingerprint": fingerprint,
                    "delivery": delivery,
                    "detail": detail,
                }
            ],
            schema=ALERT_SCHEMA,
        ),
        now,
    )
    return delivery


def notification_test(config_path: Path) -> dict[str, Any]:
    config = read_service_config(config_path)
    delivery = _notify(
        config,
        "test",
        "Invest：Telegram 告警通道部署自检。仅向配置的 allowed UID 发送。",
        forward.clock(),
    )
    return {
        "notification": delivery,
        **({"error": "Telegram test delivery failed"} if delivery == "failed" else {}),
    }


def system_failure(config_path: Path) -> dict[str, Any]:
    config = read_service_config(config_path)
    delivery = _notify(
        config, "systemd", "Invest：systemd 任务失败或被终止，请检查主机服务日志。", forward.clock()
    )
    return {
        "notification": delivery,
        **({"error": "Telegram failure delivery failed"} if delivery == "failed" else {}),
    }


def _backup(config: ServiceConfig, status: dict[str, Any]) -> dict[str, Any]:
    output = config.backup_root / status["account_id"] / status["head"]
    if output.exists():
        verify_inventory(output)
        manifest = pq.read_table(output / "backup.parquet").to_pylist()[0]
        if manifest["head"] != status["head"]:
            raise ValueError("Existing backup does not match its journal head")
        return {"backup": str(output), **manifest}
    return backup_forward(config.account, output)


def run_service(config_path: Path) -> dict[str, Any]:
    config = read_service_config(config_path)
    config.state_root.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(config.state_root / ".service.lock", timeout=0):
            return _run_service(config)
    except Timeout as exc:
        raise ValueError("Another daily service invocation is running") from exc


def _run_service(config: ServiceConfig) -> dict[str, Any]:
    started = forward.clock()
    previous = None
    status: dict[str, Any] = {}
    result: dict[str, Any] = {}
    saved: dict[str, Any] = {}
    checks, outcome, error = 0, "ok", ""
    try:
        previous = _latest(config.state_root / "runs")
        if config.telegram_required:
            telegram_recipient(config.telegram_token_env, config.telegram_uid_env)
        verify_forward(config.account)
        result = forward_job(config.account, config.data_root, attempts=config.attempts)
        verified = verify_forward(config.account)
        checks = verified["reconciliation_checks"]
        status = forward_status(config.account)
        saved = _backup(config, status)
        if verified["head"] != status["head"] or saved["head"] != status["head"]:
            raise ValueError("Account changed between reconciliation and backup; retry")
        if result.get("error") or status["operations"] == "paused" or status["missing_sessions"]:
            outcome, error = (
                "attention",
                str(result.get("error", "Account paused or missing sessions")),
            )
        elif status["risk_status"] != "active" and status["operations"] not in {
            "completed",
            "stopped",
        }:
            outcome, error = "attention", "Capital risk latch requires review"
    except Exception as exc:
        outcome, error = "error", str(exc)
    finished = forward.clock()
    if finished < started:
        outcome, error = "error", "Service clock moved backwards"
    notification = "not_needed"
    if outcome != "ok":
        notification = _notify(config, "failure", f"Invest 运行异常：{error}", finished)
    elif previous and previous["outcome"] != "ok":
        notification = _notify(config, "recovery", "Invest：运行已恢复，对账及备份通过。", finished)
        if notification == "failed" and config.telegram_required:
            outcome, error = "error", "Telegram recovery delivery failed"
    row = {
        "started_at": started,
        "finished_at": finished,
        "outcome": outcome,
        "account_id": status.get("account_id", ""),
        "head": status.get("head", ""),
        "backup": saved.get("backup", ""),
        "last_session": status.get("last_session", ""),
        "sessions": status.get("sessions", 0),
        "missing_sessions": status.get("missing_sessions", 0),
        "operations": status.get("operations", "unknown"),
        "risk_status": status.get("risk_status", "unknown"),
        "updated": result.get("updated", False),
        "due": result.get("due", bool(result)),
        "reconciliation_checks": checks,
        "error": error,
        "notification": notification,
    }
    record = _write_record(
        config.state_root / "runs", pa.Table.from_pylist([row], schema=SERVICE_SCHEMA), finished
    )
    return {**row, "record": str(record)}


def check_service(config_path: Path) -> dict[str, Any]:
    config = read_service_config(config_path)
    now = forward.clock()
    row = _latest(config.state_root / "runs")
    error = ""
    try:
        if row is None:
            raise ValueError("Daily service has no durable heartbeat")
        if (
            not timedelta(0)
            <= now - row["finished_at"]
            <= timedelta(minutes=config.heartbeat_max_minutes)
        ):
            raise ValueError("Daily service heartbeat is stale or in the future")
        if row["outcome"] != "ok":
            raise ValueError("Daily service last run requires attention")
        status = forward_status(config.account)
        if not status["engine_matches"] or status["head"] != row["head"]:
            raise ValueError("Account version/head changed after its last reconciliation")
        backup = Path(row["backup"])
        verify_inventory(backup)
        if pq.read_table(backup / "backup.parquet")["head"][0].as_py() != row["head"]:
            raise ValueError("Last reconciled backup head differs")
    except (OSError, ValueError) as exc:
        error = str(exc)
    delivery = (
        _notify(config, "watchdog", f"Invest 看门狗告警：{error}", now) if error else "not_needed"
    )
    result = {"recorded_at": now, "healthy": not error, "error": error, "notification": delivery}
    _write_record(config.state_root / "health", pa.Table.from_pylist([result]), now)
    return result
