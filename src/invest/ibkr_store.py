"""Durable, append-only Paper execution evidence, separate from M3 capital journals."""

import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Context, Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock

from invest.ibkr_models import timestamp

EVENT_SCHEMA = pa.schema(
    [
        ("sequence", pa.int64()),
        ("recorded_at", pa.timestamp("us", tz="UTC")),
        ("kind", pa.string()),
        ("event_key", pa.string()),
        ("payload", pa.binary()),
    ],
    metadata={b"schema_version": b"invest.ibkr.execution-events.v1"},
)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(context=Context(prec=50)), "f") if value else "0"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


def encode(value: Any) -> bytes:
    return json.dumps(
        value, default=json_value, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def publish(table: pa.Table, path: Path) -> None:
    """Flush bytes before publication; callers hold the journal lock for mutations."""
    if path.exists():
        raise ValueError("IBKR evidence is append-only; output already exists")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        pq.write_table(table, temporary, compression="zstd")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if path.exists():
            raise ValueError("IBKR evidence output already exists")
        temporary.rename(path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class EventStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @contextmanager
    def locked(self) -> Iterator["EventStore"]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with FileLock(self.directory / ".writer.lock", timeout=15):
            yield self

    def read(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        folder = self.directory / "events"
        files = sorted(folder.glob("*.parquet"))
        keys: set[str] = set()
        for index, path in enumerate(files):
            table = pq.read_table(path)
            if (
                path.name != f"{index:08d}.parquet"
                or table.num_rows != 1
                or not (table.schema.equals(EVENT_SCHEMA, check_metadata=True))
            ):
                raise ValueError("Invalid or noncontiguous IBKR event history")
            row = table.to_pylist()[0]
            if (
                row["sequence"] != index
                or row["event_key"] in keys
                or (events and row["recorded_at"] < events[-1]["recorded_at"])
            ):
                raise ValueError("Invalid IBKR event ordering/key")
            keys.add(row["event_key"])
            row["payload"] = json.loads(row["payload"])
            events.append(row)
        return events

    def append(
        self,
        kind: str,
        key: str,
        payload: dict[str, Any],
        at: datetime | None = None,
    ) -> bool:
        events = self.read()
        body = encode(payload)
        existing = next((e for e in events if e["event_key"] == key), None)
        if existing is not None:
            if existing["kind"] != kind or encode(existing["payload"]) != body:
                raise ValueError("Conflicting duplicate IBKR event; original evidence retained")
            return False
        recorded = timestamp(at or datetime.now(UTC))
        if events and recorded < events[-1]["recorded_at"]:
            raise ValueError("IBKR execution journal clock moved backwards")
        folder = self.directory / "events"
        folder.mkdir(exist_ok=True)
        row = {
            "sequence": len(events),
            "recorded_at": recorded,
            "kind": kind,
            "event_key": key,
            "payload": body,
        }
        publish(
            pa.Table.from_pylist([row], schema=EVENT_SCHEMA), folder / f"{len(events):08d}.parquet"
        )
        return True
