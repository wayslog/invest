"""研究快照、因子和标签的统一表格契约。"""

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

AMOUNT = pa.decimal128(38, 18)
TIME = pa.timestamp("us", tz="UTC")


def research_schema(name: str, fields: list[tuple[str, pa.DataType]]) -> pa.Schema:
    return pa.schema(fields, metadata={b"schema_version": f"invest.research.{name}.v1".encode()})


RESEARCH_BARS = research_schema(
    "bars",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        *[(name, AMOUNT) for name in ("open", "high", "low", "close", "volume")],
        ("available_at", TIME),
        ("captured_at", TIME),
    ],
)
UNIVERSE = research_schema(
    "universe",
    [
        ("instrument", pa.string()),
        ("symbol", pa.string()),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("available_at", TIME),
    ],
)
FACTOR_SCHEMA = research_schema(
    "factors",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("factor", pa.string()),
        ("expression", pa.string()),
        ("value", pa.float64()),
        ("available_at", TIME),
    ],
)
LABEL_SCHEMA = research_schema(
    "labels",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("horizon", pa.int32()),
        ("entry_at", TIME),
        ("exit_at", TIME),
        ("value", pa.float64()),
    ],
)
SIGNAL_SCHEMA = research_schema(
    "signals",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("score", pa.float64()),
        ("rank", pa.int32()),
        ("direction", pa.int8()),
        ("horizon", pa.int32()),
        ("available_at", TIME),
        ("expires_at", TIME),
        ("pool_id", pa.string()),
    ],
)


@dataclass(frozen=True)
class SnapshotSpec:
    source: str
    source_ref: str
    price_basis: str
    volume_unit: str
    universe_basis: str
    currency: str = "USD"


@dataclass(frozen=True)
class DataSnapshot:
    directory: Path
    snapshot_id: str
    spec: SnapshotSpec
    scope: str
    limitations: tuple[str, ...]
    bars: pa.Table
    universe: pa.Table
    calendar: pa.Table

    def metadata(self, schema: pa.Schema) -> dict[bytes, bytes]:
        return {
            **(schema.metadata or {}),
            b"snapshot_id": self.snapshot_id.encode(),
            b"source": self.spec.source.encode(),
            b"price_basis": self.spec.price_basis.encode(),
            b"scope": self.scope.encode(),
        }


def validate_frame(
    table: pa.Table, schema: pa.Schema, keys: list[str], value_column: str = "value"
) -> None:
    if not table.schema.equals(schema, check_metadata=False):
        raise ValueError("Research frame schema mismatch")
    metadata = table.schema.metadata or {}
    if any(metadata.get(k) != v for k, v in (schema.metadata or {}).items()) or not all(
        metadata.get(k) for k in (b"snapshot_id", b"source", b"price_basis", b"scope")
    ):
        raise ValueError("Research frame requires schema and snapshot provenance")
    frame = table.to_pandas()
    if frame[keys].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("Research frame keys must be non-null and unique")
    if frame[value_column].isin([float("inf"), float("-inf")]).any():
        raise ValueError("Research frame values must be finite or missing")


@dataclass(frozen=True)
class FactorFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, FACTOR_SCHEMA, ["date", "instrument", "factor"])


@dataclass(frozen=True)
class LabelFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, LABEL_SCHEMA, ["date", "instrument", "horizon"])
        for row in self.table.to_pylist():
            if (
                row["horizon"] < 1
                or row["entry_at"] is None
                or row["exit_at"] is None
                or row["entry_at"].date() <= row["date"]
                or row["exit_at"] <= row["entry_at"]
            ):
                raise ValueError("Labels must start after the decision session and end after entry")


@dataclass(frozen=True)
class SignalFrame:
    table: pa.Table

    def __post_init__(self) -> None:
        validate_frame(self.table, SIGNAL_SCHEMA, ["date", "instrument"], "score")
        if any(column.null_count for column in self.table.columns):
            raise ValueError("Signals must have complete values and provenance")
        ranks = set()
        for row in self.table.to_pylist():
            if (
                not -1 <= row["score"] <= 1
                or row["rank"] < 1
                or row["horizon"] < 1
                or row["direction"] not in {0, 1}
                or not row["pool_id"]
                or row["available_at"].date() != row["date"]
                or row["expires_at"] <= row["available_at"]
                or (row["date"], row["rank"]) in ranks
            ):
                raise ValueError("Invalid signal score, rank, direction or validity interval")
            ranks.add((row["date"], row["rank"]))
