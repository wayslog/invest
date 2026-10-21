"""One-shot calendar worker and verifiable offline backup/restore."""

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import FetchSpec
from invest.datasets import checksum, fetch_dataset
from invest.dividends import capture_distributions
from invest.forward import (
    _at,
    _guard,
    _history,
    _load,
    _publish,
    _runs,
    _staging,
    account_lock,
    fail_forward,
    forward_status,
    run_forward,
)
from invest.forward_engine import cancel_future
from invest.quality import latest_completed_session
from invest.research_registry import seal, verify_inventory, write_table


def forward_job(
    account: Path, data_root: Path, issuer: Path | None = None, *, attempts: int = 2
) -> dict[str, Any]:
    """Run from cron hourly; XNYS and the provider cutoff determine whether work is due."""
    if not 1 <= attempts <= 5:
        raise ValueError("Fetch attempts must be between 1 and 5")
    with account_lock(account):
        runs, plan, _, state = _load(account)
        now = _at(plan, None)
        _guard(runs, now)
        if plan.mode == "drill":
            raise ValueError("The network worker cannot run synthetic drills")
        target = latest_completed_session(now, provider_daily=True)
        if state.operations in {"stopped", "completed"} or state.last_session >= target:
            return {"updated": False, "status": state.operations, "due": False}
        history = _history(runs, plan.symbols)
        start = history[plan.symbols[0]]["date"][0].as_py()
        feed = (history[plan.symbols[0]].schema.metadata or {}).get(b"feed", b"sip").decode()
        expected_head = checksum(runs[-1] / "files.parquet")
    sources: dict[str, Path] = {}
    try:
        if issuer is None:
            issuer = data_root / "issuer" / f"{uuid.uuid4().hex}.parquet"
            issuer.parent.mkdir(parents=True, exist_ok=True)
            capture_distributions(issuer)
        for symbol in plan.symbols:
            for _ in range(attempts):
                dataset = fetch_dataset(FetchSpec(symbol, start, target, feed), data_root)
                sources[symbol] = dataset
                if (
                    pq.read_table(dataset / "manifest.parquet")["status"][0].as_py()
                    == "research_only"
                ):
                    break
    except (OSError, ValueError) as exc:
        return fail_forward(account, f"Acquisition failed: {exc}", expected_head=expected_head)
    return run_forward(account, sources, issuer=issuer, expected_head=expected_head)


def backup_forward(account: Path, output: Path) -> dict[str, Any]:
    with account_lock(account):
        return _backup_runs(account, _runs(account), output)


def _backup_runs(account: Path, runs: list[Path], output: Path) -> dict[str, Any]:
    """The caller holds the account lock, including when backing up a migration parent."""
    if output.exists() or output.resolve().is_relative_to(account.resolve()):
        raise ValueError("Backup must be a new path outside the account")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.{uuid.uuid4().hex}.backup"
    try:
        for run in runs:
            shutil.copytree(run, staging / "journal" / run.name)
        copied = _runs(staging)
        head = checksum(copied[-1] / "files.parquet")
        write_table(
            pa.Table.from_pylist(
                [{"head": head, "commits": len(copied)}],
                schema=pa.schema([("head", pa.string()), ("commits", pa.int64())]),
            ),
            staging / "backup.parquet",
        )
        seal(staging)
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"backup": str(output), "head": head, "commits": len(runs)}


def restore_forward(
    backup: Path,
    account: Path,
    expected_head: str,
    actor: str,
    reason: str,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Require the externally retained head; restored copies start paused, with the same ID."""
    if account.exists() or not actor.strip() or not reason.strip():
        raise ValueError("Restore requires a new destination, actor and reason")
    verify_inventory(backup)
    if pq.read_table(backup / "backup.parquet")["head"][0].as_py() != expected_head:
        raise ValueError("Backup is not the expected journal head; do not roll back capital")
    account.parent.mkdir(parents=True, exist_ok=True)
    working = account.parent / f".{account.name}.{uuid.uuid4().hex}.restore"
    try:
        for source in _runs(backup):
            shutil.copytree(source, working / "journal" / source.name)
        runs, plan, _, state = _load(working)
        if checksum(runs[-1] / "files.parquet") != expected_head:
            raise ValueError("Restored journal head mismatch")
        now = _at(plan, at)
        account_id = _guard(runs, now)
        if state.operations not in {"completed", "stopped"}:
            state.operations = "paused"
        outcomes = cancel_future(state, now, "restore: " + reason)
        staging = _staging(working)
        _publish(
            working,
            staging,
            runs,
            account_id,
            now,
            "restore",
            actor,
            reason,
            {**state.tables(), "outcomes": outcomes},
        )
        working.rename(account)
    except BaseException:
        shutil.rmtree(working, ignore_errors=True)
        raise
    return forward_status(account, at=at)
