"""Version boundaries preserve capital and verify old events with their archived engine."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.datasets import checksum
from invest.forward_config import parse_observation

MIGRATION_SCHEMA = pa.schema(
    [
        ("account_id", pa.string()),
        ("migrated_at", pa.timestamp("us", tz="UTC")),
        ("actor", pa.string()),
        ("reason", pa.string()),
        ("from_engine_sha256", pa.string()),
        ("to_engine_sha256", pa.string()),
        ("from_head_sha256", pa.string()),
        ("from_version", pa.string()),
        ("to_version", pa.string()),
        ("policy", pa.string()),
    ],
    metadata={b"schema_version": b"invest.forward.migration.v1"},
)
VERIFICATION_SCHEMA = pa.schema(
    [
        ("engine_sha256", pa.string()),
        ("head", pa.string()),
        ("status", pa.string()),
        ("commits", pa.int64()),
        ("reconciliation_checks", pa.int64()),
    ],
    metadata={b"schema_version": b"invest.forward.archived-verification.v1"},
)
SNAPSHOTS = ("state", "ledgers", "pending")


def check_archive(directory: Path, expected: str) -> list[dict[str, Any]]:
    digest = hashlib.sha256()
    sources: list[dict[str, Any]] = pq.read_table(directory / "engine-source.parquet").to_pylist()
    names: set[str] = set()
    for row in sorted(sources, key=lambda row: row["file"]):
        name = row["file"]
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*\.py", name) or name in names:
            raise ValueError("Invalid or duplicate archived engine source name")
        names.add(name)
        digest.update(name.encode())
        digest.update(row["body"])
    if digest.hexdigest() != expected:
        raise ValueError("Archived forward engine differs from registration/version boundary")
    return sources


def paused_snapshot(previous: pa.Table) -> pa.Table:
    rows = previous.to_pylist()
    if rows[0]["operations"] not in {"stopped", "completed"}:
        rows[0]["operations"] = "paused"
    return pa.Table.from_pylist(rows, schema=previous.schema)


def validate_versions(runs: list[Path], initial_engine: str) -> int:
    """Validate every boundary without running archived Python. Return the current epoch start."""
    active, epoch, previous_time = initial_engine, 0, None
    registration = pq.read_table(runs[0] / "registration.parquet").to_pylist()[0]
    active_version = registration["package_version"]
    for i, run in enumerate(runs):
        journal = pq.read_table(run / "journal.parquet").to_pylist()[0]
        if previous_time is not None and journal["recorded_at"] < previous_time:
            raise ValueError("Forward journal clock moved backwards")
        previous_time = journal["recorded_at"]
        if journal["account_id"] != registration["account_id"]:
            raise ValueError("Forward journal account differs from registration")
        if i == 0 and (
            journal["kind"] != "register" or journal["recorded_at"] != registration["registered_at"]
        ):
            raise ValueError("Forward genesis event differs from registration")
        if journal["kind"] == "migrate":
            table = pq.read_table(run / "migration.parquet")
            if (
                i == 0
                or table.num_rows != 1
                or not table.schema.equals(MIGRATION_SCHEMA, check_metadata=True)
            ):
                raise ValueError("Invalid forward migration schema or position")
            migration = table.to_pylist()[0]
            if (
                any(value is None for value in migration.values())
                or migration["from_engine_sha256"] != active
                or migration["to_engine_sha256"] == active
                or migration["to_engine_sha256"] != journal["engine_sha256"]
                or migration["from_head_sha256"] != checksum(runs[i - 1] / "files.parquet")
                or migration["account_id"] != journal["account_id"]
                or migration["migrated_at"] != journal["recorded_at"]
                or migration["actor"] != journal["actor"]
                or migration["reason"] != journal["reason"]
                or not migration["actor"].strip()
                or not migration["reason"].strip()
                or migration["policy"] != "preserve_state_pause_v1"
                or migration["from_version"] != active_version
                or not migration["to_version"]
            ):
                raise ValueError("Forward migration boundary identity/head/engine mismatch")
            plan = parse_observation(registration["observation_body"])
            if plan.mode not in {"cash_observation", "drill"}:
                raise ValueError("Strategy migration requires separate research requalification")
            check_archive(run, migration["to_engine_sha256"])
            proof = pq.read_table(run / "old-engine-verification.parquet")
            if (
                not proof.schema.equals(VERIFICATION_SCHEMA, check_metadata=True)
                or proof.num_rows != 1
            ):
                raise ValueError("Invalid archived-engine verification receipt")
            receipt = proof.to_pylist()[0]
            if (
                receipt["engine_sha256"] != active
                or receipt["head"] != migration["from_head_sha256"]
                or receipt["status"] != "verified"
                or receipt["commits"] != i
            ):
                raise ValueError("Migration archived-engine proof differs from its parent")
            for name in SNAPSHOTS:
                previous = pq.read_table(runs[i - 1] / f"{name}.parquet")
                expected = paused_snapshot(previous) if name == "state" else previous
                if not expected.equals(pq.read_table(run / f"{name}.parquet"), check_metadata=True):
                    raise ValueError(f"Migration changed capital, risk or obligations: {name}")
            active, epoch = migration["to_engine_sha256"], i
            active_version = migration["to_version"]
        elif journal["engine_sha256"] != active:
            raise ValueError("Forward journal engine differs from registration/version boundary")
    return epoch


def verify_archived(runs: list[Path], expected_engine: str) -> dict[str, Any]:
    """Replay a copied prefix with its own source, without passing API/SSH credentials."""
    location = next(run for run in reversed(runs) if (run / "engine-source.parquet").is_file())
    sources = check_archive(location, expected_engine)
    expected_head = checksum(runs[-1] / "files.parquet")
    with tempfile.TemporaryDirectory(prefix="invest-archived-engine-") as temporary:
        root = Path(temporary)
        package = root / "engine" / "invest"
        package.mkdir(parents=True)
        for row in sources:
            (package / row["file"]).write_bytes(row["body"])
        for run in runs:
            shutil.copytree(run, root / "account" / "journal" / run.name)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TZ"}
        }
        environment.update(
            PYTHONPATH=str(package.parent),
            MPLCONFIGDIR=str(root / "matplotlib"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "invest",
                    "forward-verify",
                    "--account",
                    str(root / "account"),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Archived-engine replay timed out; no version transition") from exc
        if result.returncode != 0:
            raise ValueError("Archived-engine replay failed; no version transition")
        try:
            proof = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Invalid archived-engine replay output") from exc
        if (
            proof.get("status") != "verified"
            or proof.get("head") != expected_head
            or proof.get("commits") != len(runs)
        ):
            raise ValueError("Archived-engine replay verified a different prefix")
        return {"engine_sha256": expected_engine, **proof}
