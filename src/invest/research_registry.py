"""Immutable experiment registration and hash inventories; no network access."""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.datasets import FILES_SCHEMA, checksum
from invest.storage import engine_digest
from invest.study_config import StudyConfig, parse_study

LEGACY_REGISTRATION_SCHEMA = pa.schema(
    [
        ("study_id", pa.string()),
        ("registered_at", pa.timestamp("us", tz="UTC")),
        ("config_sha256", pa.string()),
        ("config_body", pa.binary()),
    ],
    metadata={b"schema_version": b"invest.research_registration.v1"},
)
REGISTRATION_SCHEMA = pa.schema(
    [*list(LEGACY_REGISTRATION_SCHEMA), ("engine_sha256", pa.string())],
    metadata={b"schema_version": b"invest.research_registration.v2"},
)


def write_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        pq.write_table(table, stream, compression="zstd")


def register_study(config_path: Path, output: Path) -> None:
    body = config_path.read_bytes()
    config = parse_study(body)
    write_table(
        pa.Table.from_pylist(
            [
                {
                    "study_id": config.study_id,
                    "registered_at": datetime.now(UTC),
                    "config_sha256": hashlib.sha256(body).hexdigest(),
                    "config_body": body,
                    "engine_sha256": engine_digest(),
                }
            ],
            schema=REGISTRATION_SCHEMA,
        ),
        output,
    )


def read_registration(
    source: Path | bytes, *, required_engine: str | None = None
) -> tuple[StudyConfig, datetime, str]:
    table = pq.read_table(pa.BufferReader(source) if isinstance(source, bytes) else source)
    legacy = table.schema.equals(LEGACY_REGISTRATION_SCHEMA, check_metadata=True)
    if (
        not legacy and not table.schema.equals(REGISTRATION_SCHEMA, check_metadata=True)
    ) or table.num_rows != 1:
        raise ValueError("Invalid research registration schema")
    row = table.to_pylist()[0]
    if any(value is None for value in row.values()):
        raise ValueError("Incomplete research registration")
    if legacy and required_engine is not None:
        raise ValueError(
            "Legacy registration has no engine binding; create a new registration. "
            "Previously observed holdout data is not unseen evidence"
        )
    if not legacy:
        if not re.fullmatch(r"[0-9a-f]{64}", row["engine_sha256"]):
            raise ValueError("Invalid registered engine fingerprint")
        if required_engine is not None and row["engine_sha256"] != required_engine:
            raise ValueError(
                "Registered engine mismatch; create a new registration for changed code. "
                "Previously observed holdout data is not unseen evidence"
            )
    config = parse_study(row["config_body"])
    if (
        config.study_id != row["study_id"]
        or hashlib.sha256(row["config_body"]).hexdigest() != row["config_sha256"]
        or row["registered_at"] > datetime.now(UTC)
    ):
        raise ValueError("Research registration identity/hash/time mismatch")
    return config, row["registered_at"], row["config_sha256"]


def parse_mappings(values: list[str]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for value in values:
        symbol, separator, path = value.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) or not path:
            raise ValueError("Input must be SYMBOL=PATH")
        if symbol in output:
            raise ValueError(f"Duplicate symbol: {symbol}")
        output[symbol] = Path(path)
    return output


def seal(directory: Path) -> None:
    write_table(
        pa.Table.from_pylist(
            [
                {"file": str(path.relative_to(directory)), "sha256": checksum(path)}
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            ],
            schema=FILES_SCHEMA,
        ),
        directory / "files.parquet",
    )


def verify_inventory(directory: Path) -> None:
    table = pq.read_table(directory / "files.parquet")
    if not table.schema.equals(FILES_SCHEMA) or not table.num_rows:
        raise ValueError("Invalid research inventory")
    names = table["file"].to_pylist()
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    if len(set(names)) != len(names) or set(names) != actual - {"files.parquet"}:
        raise ValueError("Research inventory has missing/extra files")
    for row in table.to_pylist():
        path = directory / row["file"]
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Unsafe research inventory path")
        if checksum(path) != row["sha256"]:
            raise ValueError(f"Research checksum mismatch: {row['file']}")
