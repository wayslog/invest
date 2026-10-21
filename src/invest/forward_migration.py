"""Explicit, append-only engine transitions for cash accounts and synthetic drills."""

import shutil
from datetime import datetime
from importlib.metadata import distributions, version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.datasets import checksum
from invest.forward import _at, _load, _publish, _require_engine, _staging, account_lock
from invest.forward_ops import _backup_runs
from invest.forward_versions import (
    MIGRATION_SCHEMA,
    VERIFICATION_SCHEMA,
    check_archive,
    verify_archived,
)
from invest.research_registry import write_table
from invest.storage import engine_digest


def migrate_forward(
    account: Path,
    expected_head: str,
    from_engine: str,
    backup: Path,
    actor: str,
    reason: str,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Keep the account directory and all old events. Only the operating state pauses."""
    if not actor.strip() or not reason.strip():
        raise ValueError("Migration requires an actor and a reason")
    digest = engine_digest()
    with account_lock(account):
        runs, plan, _, state = _load(account)
        if plan.mode not in {"cash_observation", "drill"}:
            raise ValueError("Strategy migration requires separate research requalification")
        last = pq.read_table(runs[-1] / "journal.parquet").to_pylist()[0]
        if last["kind"] == "migrate":
            previous = pq.read_table(runs[-1] / "migration.parquet").to_pylist()[0]
            if (
                previous["from_head_sha256"] == expected_head
                and previous["from_engine_sha256"] == from_engine
                and previous["to_engine_sha256"] == digest
            ):
                return {
                    "updated": False,
                    "status": state.operations,
                    "head": checksum(runs[-1] / "files.parquet"),
                }
        if checksum(runs[-1] / "files.parquet") != expected_head:
            raise ValueError("Migration expected head differs; do not roll back capital")
        if last["engine_sha256"] != from_engine or from_engine == digest:
            raise ValueError("Migration source engine differs or no engine change is needed")
        now = _at(plan, at)
        if now < last["recorded_at"]:
            raise ValueError("Forward clock cannot move backwards")
        # Old logic proves its own full prefix. New logic never retroactively
        # recalculates the decisions made by an earlier engine.
        proof = verify_archived(runs, from_engine)
        saved = _backup_runs(account, runs, backup)
        if saved["head"] != expected_head:
            raise ValueError("Migration backup differs from the verified parent")
        now = _at(plan, at)
        if now < last["recorded_at"]:
            raise ValueError("Forward clock cannot move backwards")
        _require_engine(digest)
        if state.operations not in {"completed", "stopped"}:
            state.operations = "paused"
        staging = _staging(account)
        try:
            location = next(
                run for run in reversed(runs) if (run / "engine-source.parquet").exists()
            )
            source_version = (
                pq.read_table(location / "migration.parquet")["to_version"][0].as_py()
                if (location / "migration.parquet").exists()
                else pq.read_table(location / "registration.parquet")["package_version"][0].as_py()
            )
            write_table(
                pa.Table.from_pylist(
                    [
                        {
                            "account_id": last["account_id"],
                            "migrated_at": now,
                            "actor": actor,
                            "reason": reason,
                            "from_engine_sha256": from_engine,
                            "to_engine_sha256": digest,
                            "from_head_sha256": expected_head,
                            "from_version": source_version,
                            "to_version": version("wayslog-invest"),
                            "policy": "preserve_state_pause_v1",
                        }
                    ],
                    schema=MIGRATION_SCHEMA,
                ),
                staging / "migration.parquet",
            )
            write_table(
                pa.Table.from_pylist([proof], schema=VERIFICATION_SCHEMA),
                staging / "old-engine-verification.parquet",
            )
            write_table(
                pa.Table.from_pylist(
                    [
                        {"file": source.name, "body": source.read_bytes()}
                        for source in sorted(Path(__file__).parent.glob("*.py"))
                    ],
                    schema=pa.schema([("file", pa.string()), ("body", pa.binary())]),
                ),
                staging / "engine-source.parquet",
            )
            check_archive(staging, digest)
            write_table(
                pa.Table.from_pylist(
                    [
                        {"package": d.metadata["Name"], "version": d.version}
                        for d in distributions()
                    ],
                    schema=pa.schema([("package", pa.string()), ("version", pa.string())]),
                ),
                staging / "dependencies.parquet",
            )
            directory = _publish(
                account,
                staging,
                runs,
                last["account_id"],
                now,
                "migrate",
                actor,
                reason,
                state.tables(),
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "updated": True,
            "status": state.operations,
            "account_id": last["account_id"],
            "run": str(directory),
            "head": checksum(directory / "files.parquet"),
            "backup": str(backup),
            "from_engine": from_engine,
            "to_engine": digest,
        }
