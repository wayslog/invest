"""不可覆盖的 Parquet 研究快照；不迁移账户或修改原采集记录。"""

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from invest.contracts import (
    RESEARCH_BARS,
    UNIVERSE,
    DataSnapshot,
    SnapshotSpec,
    research_schema,
)
from invest.ibkr_data import SCHEMAS
from invest.quality import regular_sessions

SNAPSHOT_SCHEMA = research_schema(
    "snapshot",
    [
        *[
            (name, pa.string())
            for name in (
                "snapshot_id",
                "source",
                "source_ref",
                "price_basis",
                "volume_unit",
                "universe_basis",
                "currency",
                "scope",
                "bars_sha256",
                "universe_sha256",
                "calendar_sha256",
            )
        ],
        ("limitations", pa.list_(pa.field("element", pa.string()))),
        ("account_eligible", pa.bool_()),
    ],
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_snapshot_tables(
    bars: pa.Table, universe: pa.Table, spec: SnapshotSpec
) -> tuple[pa.Table, tuple[str, ...]]:
    """纯校验快照表和口径，返回交易日历与限制；不创建或改动记录。"""
    for table, schema in ((bars, RESEARCH_BARS), (universe, UNIVERSE)):
        if not table.schema.equals(schema, check_metadata=False) or any(
            (table.schema.metadata or {}).get(k) != v for k, v in (schema.metadata or {}).items()
        ):
            raise ValueError("Research snapshot schema mismatch")
        if not table.num_rows or any(
            table[name].null_count for name in table.column_names if name != "available_at"
        ):
            raise ValueError("Snapshot tables must be nonempty; only available_at may be unknown")
    if (
        not spec.source_ref.strip()
        or not re.fullmatch(r"[a-z][a-z0-9_]*", spec.source)
        or spec.currency != "USD"
        or spec.price_basis not in {"raw", "split_adjusted", "total_return_adjusted"}
        or spec.volume_unit not in {"shares", "provider_reported"}
        or spec.universe_basis not in {"historical", "current_sample", "synthetic"}
    ):
        raise ValueError("Unsupported snapshot source, units, price basis or universe basis")
    rows, members = bars.to_pylist(), universe.to_pylist()
    dates = [row["date"] for row in rows]
    calendar = regular_sessions(min(dates), max(dates))
    sessions = {row["date"]: row for row in calendar.to_pylist()}
    ranges: dict[str, list[tuple[date, date]]] = {}
    symbols: dict[str, str] = {}
    limitations = set()
    for row in members:
        instrument, start, end = row["instrument"], row["start"], row["end"]
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", instrument) or not row["symbol"].strip():
            raise ValueError("Instrument must be a stable uppercase identifier")
        if start not in sessions or end not in sessions or start > end:
            raise ValueError("Universe intervals must use sessions inside the snapshot calendar")
        if any(
            start <= old_end and end >= old_start
            for old_start, old_end in ranges.get(instrument, [])
        ):
            raise ValueError("Universe intervals must not overlap")
        if instrument in symbols and symbols[instrument] != row["symbol"]:
            raise ValueError("An instrument cannot map to conflicting symbols")
        symbols[instrument] = row["symbol"]
        ranges.setdefault(instrument, []).append((start, end))
        if row["available_at"] is None or row["available_at"] > sessions[start]["open_at"]:
            limitations.add("universe_availability_unknown_or_late")
    seen = set()
    for row in rows:
        session, instrument = row["date"], row["instrument"]
        key = (session, instrument)
        if key in seen or session not in sessions or instrument not in ranges:
            raise ValueError("Duplicate bar, invalid session or instrument outside universe")
        seen.add(key)
        if (
            not 0
            < row["low"]
            <= min(row["open"], row["close"])
            <= max(row["open"], row["close"])
            <= row["high"]
            or row["volume"] < 0
        ):
            raise ValueError("Invalid research OHLCV bounds")
        if row["captured_at"] < sessions[session]["close_at"]:
            raise ValueError("An unfinished session cannot enter a daily research snapshot")
        available = row["available_at"]
        if available is None:
            limitations.add("historical_availability_unknown")
        elif not sessions[session]["close_at"] <= available <= row["captured_at"]:
            raise ValueError("available_at must be after session close and no later than capture")
    expected = {
        (session, instrument)
        for instrument, intervals in ranges.items()
        for session in sessions
        if any(start <= session <= end for start, end in intervals)
    }
    if not expected <= seen:
        raise ValueError("Missing bars inside declared universe intervals; no forward fill")
    if spec.source not in {"ibkr", "synthetic"}:
        limitations.add("historical_reference_source")
    if spec.universe_basis == "current_sample":
        limitations.add("current_sample_not_historical_universe")
    if spec.volume_unit != "shares":
        limitations.add("volume_unit_unverified")
    if spec.price_basis == "split_adjusted":
        limitations.add("split_adjusted_without_dividend_returns")
    # P1 快照仅供研究，不能替代包含企业行动的会计输入。
    return calendar, tuple(sorted(limitations))


def create_snapshot(
    bars: pa.Table,
    universe: pa.Table,
    destination: Path,
    spec: SnapshotSpec,
    *,
    allow_exploratory: bool = False,
) -> DataSnapshot:
    calendar, limitations = validate_snapshot_tables(bars, universe, spec)
    if limitations and not allow_exploratory:
        raise ValueError(f"Exploratory snapshot requires explicit opt-in: {', '.join(limitations)}")
    scope = (
        "synthetic" if spec.source == "synthetic" else "exploratory" if limitations else "research"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(destination.parent / f".{destination.name}.lock", timeout=15):
        if destination.exists():
            raise FileExistsError("Snapshot destination already exists; history is immutable")
        staging = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        staging.mkdir()
        try:
            tables = {
                "bars": bars.sort_by([("date", "ascending"), ("instrument", "ascending")]),
                "universe": universe.sort_by([("instrument", "ascending"), ("start", "ascending")]),
                "calendar": calendar,
            }
            for name, table in tables.items():
                pq.write_table(table, staging / f"{name}.parquet", compression="zstd")
            record = {
                **asdict(spec),
                "scope": scope,
                "limitations": list(limitations),
                "account_eligible": False,
                **{f"{name}_sha256": digest(staging / f"{name}.parquet") for name in tables},
            }
            record["snapshot_id"] = identity(record)
            pq.write_table(
                pa.Table.from_pylist([record], schema=SNAPSHOT_SCHEMA),
                staging / "snapshot.parquet",
                compression="zstd",
            )
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return load_snapshot(destination)


def load_snapshot(directory: Path, *, expected_id: str | None = None) -> DataSnapshot:
    manifest = pq.read_table(directory / "snapshot.parquet")
    if manifest.num_rows != 1 or not manifest.schema.equals(SNAPSHOT_SCHEMA, check_metadata=True):
        raise ValueError("Invalid snapshot manifest")
    record = manifest.to_pylist()[0]
    snapshot_id = record.pop("snapshot_id")
    if expected_id is not None and snapshot_id != expected_id:
        raise ValueError("Snapshot identity changed since it was loaded")
    if snapshot_id != identity(record) or record["account_eligible"] is not False:
        raise ValueError("Snapshot identity or account eligibility mismatch")
    tables = {}
    for name in ("bars", "universe", "calendar"):
        path = directory / f"{name}.parquet"
        if digest(path) != record[f"{name}_sha256"]:
            raise ValueError(f"Snapshot data changed: {name}")
        tables[name] = pq.read_table(path)
    spec = SnapshotSpec(**{name: record[name] for name in SnapshotSpec.__dataclass_fields__})
    calendar, limitations = validate_snapshot_tables(tables["bars"], tables["universe"], spec)
    scope = (
        "synthetic" if spec.source == "synthetic" else "exploratory" if limitations else "research"
    )
    if (
        not calendar.equals(tables["calendar"])
        or list(limitations) != record["limitations"]
        or scope != record["scope"]
    ):
        raise ValueError("Snapshot calendar or limitations mismatch")
    return DataSnapshot(
        directory.resolve(),
        snapshot_id,
        spec,
        scope,
        limitations,
        tables["bars"],
        tables["universe"],
        calendar,
    )


def snapshot_from_ibkr(
    capture: Path, destination: Path, *, allow_exploratory: bool = False
) -> DataSnapshot:
    tables = {
        name: pq.read_table(capture / f"{name}.parquet")
        for name in ("capture", "historical", "contracts", "quality")
    }
    for name, table in tables.items():
        if not table.schema.equals(SCHEMAS[name], check_metadata=False) or any(
            (table.schema.metadata or {}).get(k) != v
            for k, v in (SCHEMAS[name].metadata or {}).items()
        ):
            raise ValueError("IBKR capture schema mismatch")
    if tables["capture"].num_rows != 1:
        raise ValueError("One capture manifest is required")
    record = tables["capture"].to_pylist()[0]
    if not record["complete"] or "error" in tables["quality"]["status"].to_pylist():
        raise ValueError("Incomplete IBKR capture cannot enter research")
    if record["source"] not in {"ibkr", "synthetic"}:
        raise ValueError("Unsupported IBKR capture source")
    expected = {
        b"source": record["source"].encode(),
        b"environment": record["environment"].encode(),
        b"account": record["account"].encode(),
        b"captured_at": record["captured_at"].isoformat().encode(),
    }
    for table in tables.values():
        if any((table.schema.metadata or {}).get(k) != v for k, v in expected.items()):
            raise ValueError("IBKR capture provenance metadata mismatch")
    contracts = {r["con_id"]: r for r in tables["contracts"].to_pylist()}
    if len(contracts) != tables["contracts"].num_rows:
        raise ValueError("Duplicate qualified IBKR contracts")
    bars, members = [], {}
    for row in tables["historical"].to_pylist():
        contract = contracts.get(row["con_id"])
        if (
            contract is None
            or row["con_id"] <= 0
            or row["symbol"] != contract["symbol"]
            or contract["currency"] != "USD"
            or contract["security_type"] != "STK"
            or row["currency"] != "USD"
            or row["bar_size"] != "1 day"
            or row["bar_at"] is not None
            or row["what_to_show"] != "TRADES"
            or not row["use_rth"]
            or row["price_basis"] != "split_adjusted"
            or row["volume_unit"] != "provider_reported_unverified"
        ):
            raise ValueError(
                "P1 requires qualified USD regular-session split-adjusted daily TRADES"
            )
        instrument = f"IBKR{row['con_id']}"
        bars.append(
            {
                "date": row["session"],
                "instrument": instrument,
                **{name: row[name] for name in ("open", "high", "low", "close", "volume")},
                "available_at": None,
                "captured_at": record["captured_at"],
            }
        )
        if instrument not in members:
            members[instrument] = {
                "instrument": instrument,
                "symbol": row["symbol"],
                "start": row["session"],
                "end": row["session"],
                "available_at": None,
            }
        members[instrument]["start"] = min(members[instrument]["start"], row["session"])
        members[instrument]["end"] = max(members[instrument]["end"], row["session"])
    return create_snapshot(
        pa.Table.from_pylist(bars, schema=RESEARCH_BARS),
        pa.Table.from_pylist(list(members.values()), schema=UNIVERSE),
        destination,
        SnapshotSpec(
            record["source"],
            str(capture.resolve()),
            "split_adjusted",
            "provider_reported",
            "current_sample",
        ),
        allow_exploratory=allow_exploratory,
    )
