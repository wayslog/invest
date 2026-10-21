"""Freeze a hypothesis, known-data cutoff and genuinely future evaluation with its engine."""

import hashlib
import shutil
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from invest.forward_versions import check_archive
from invest.quality import regular_sessions
from invest.research_registry import read_registration, register_study, seal, write_table
from invest.storage import engine_digest
from invest.study_config import parse_study


def register_proposal(
    config: Path,
    protocol: Path,
    output: Path,
    known_through: date,
    *,
    lockfile: Path = Path("uv.lock"),
) -> dict[str, Any]:
    digest = engine_digest()
    config_body, lock_body = config.read_bytes(), lockfile.read_bytes()
    policy = parse_study(config_body)
    body = protocol.read_bytes()
    if not body.strip() or output.exists():
        raise ValueError("Proposal requires a nonempty protocol and a new output directory")
    now = datetime.now(UTC)
    session = regular_sessions(policy.holdout_start, policy.holdout_start)
    if (
        session.num_rows != 1
        or session["open_at"][0].as_py() <= now
        or policy.reused_end > known_through
        or known_through > now.date()
        or known_through >= policy.holdout_start
    ):
        raise ValueError(
            "Proposal holdout must be an unopened future session after all known history"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.{uuid.uuid4().hex}.proposal"
    staging.mkdir()
    try:
        (staging / "config.toml").write_bytes(config_body)
        register_study(staging / "config.toml", staging / "registration.parquet")
        frozen, registered, _ = read_registration(
            staging / "registration.parquet", required_engine=digest
        )
        if frozen != policy:
            raise ValueError("Proposal configuration changed during registration")
        if registered >= session["open_at"][0].as_py():
            raise ValueError("Proposal registration missed the future session open")
        registration_body = (staging / "registration.parquet").read_bytes()
        write_table(
            pa.Table.from_pylist(
                [
                    {
                        "registered_at": registered,
                        "known_through": known_through,
                        "holdout_start": policy.holdout_start,
                        "holdout_end": policy.holdout_end,
                        "protocol_body": body,
                        "protocol_sha256": hashlib.sha256(body).hexdigest(),
                        "registration_sha256": hashlib.sha256(registration_body).hexdigest(),
                        "engine_sha256": digest,
                    }
                ],
                schema=pa.schema(
                    [
                        ("registered_at", pa.timestamp("us", tz="UTC")),
                        ("known_through", pa.date32()),
                        ("holdout_start", pa.date32()),
                        ("holdout_end", pa.date32()),
                        ("protocol_body", pa.binary()),
                        ("protocol_sha256", pa.string()),
                        ("registration_sha256", pa.string()),
                        ("engine_sha256", pa.string()),
                    ],
                    metadata={b"schema_version": b"invest.proposal.v1"},
                ),
            ),
            staging / "proposal.parquet",
        )
        write_table(
            pa.Table.from_pylist(
                [
                    {"file": path.name, "body": path.read_bytes()}
                    for path in sorted(Path(__file__).parent.glob("*.py"))
                ],
                schema=pa.schema([("file", pa.string()), ("body", pa.binary())]),
            ),
            staging / "engine-source.parquet",
        )
        write_table(
            pa.Table.from_pylist(
                [{"file": "uv.lock", "body": lock_body}],
                schema=pa.schema([("file", pa.string()), ("body", pa.binary())]),
            ),
            staging / "dependency-lock.parquet",
        )
        seal(staging)
        check_archive(staging, digest)
        if engine_digest() != digest:
            raise ValueError("Engine changed during proposal registration")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "proposal": str(output),
        "study_id": policy.study_id,
        "holdout_start": str(policy.holdout_start),
        "holdout_end": str(policy.holdout_end),
        "known_through": str(known_through),
        "engine_sha256": digest,
    }
