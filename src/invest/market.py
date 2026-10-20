"""Parquet contracts for unadjusted daily bars and corporate actions."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

MONEY = pa.decimal128(24, 6)
BAR_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("open", MONEY),
        ("high", MONEY),
        ("low", MONEY),
        ("close", MONEY),
        ("volume", pa.int64()),
        ("split_ratio", pa.int64()),
        ("dividend", MONEY),
        ("dividend_pay_date", pa.date32()),
    ],
    metadata={
        b"schema_version": b"invest.bars.v1",
        b"price_basis": b"raw",
        b"currency": b"USD",
        b"session_timezone": b"America/New_York",
    },
)


def read_bars(path: Path, symbol: str) -> pa.Table:
    if path.suffix.lower() != ".parquet":
        raise ValueError("Daily bars must be a .parquet file")
    table = pq.read_table(path)
    return validate_bars(table, symbol)


def validate_bars(table: pa.Table, symbol: str) -> pa.Table:
    if not table.schema.equals(BAR_SCHEMA, check_metadata=False):
        raise ValueError("Daily bar schema does not match invest.bars.v1; see docs/data.md")
    metadata = table.schema.metadata or {}
    for key, expected in (BAR_SCHEMA.metadata or {}).items():
        if metadata.get(key) != expected:
            raise ValueError(f"Invalid/missing Parquet metadata: {key.decode()}")
    if not metadata.get(b"source", b"").strip():
        raise ValueError("Parquet metadata must declare source (synthetic or actual provider)")
    if not table.num_rows:
        raise ValueError("At least one daily bar is required")
    previous: date | None = None
    for row in table.to_pylist():
        if any(row[name] is None for name in table.column_names if name != "dividend_pay_date"):
            raise ValueError("Daily bars must not contain nulls except dividend_pay_date")
        session = row["date"]
        if previous is not None and session <= previous:
            raise ValueError("Session dates must be unique and strictly increasing")
        if session.weekday() >= 5:
            raise ValueError("US equity sessions cannot fall on weekends")
        previous = session
        if row["symbol"] != symbol:
            raise ValueError("A paper account currently accepts exactly its configured symbol")
        prices = [row[name] for name in ["open", "high", "low", "close"]]
        if any(value <= 0 or value > Decimal("1000000000") for value in prices):
            raise ValueError("Raw OHLC prices must be positive and <= 1 billion USD")
        if (
            not row["low"]
            <= min(row["open"], row["close"])
            <= max(row["open"], row["close"])
            <= row["high"]
        ):
            raise ValueError("OHLC price bounds are inconsistent")
        if row["volume"] < 0 or row["split_ratio"] < 1 or row["dividend"] < 0:
            raise ValueError("Invalid volume, split ratio or dividend")
        pay_date = row["dividend_pay_date"]
        if row["dividend"] > 0 and (pay_date is None or pay_date < session):
            raise ValueError("A dividend needs a payment date on/after its ex-date")
        if row["dividend"] == 0 and pay_date is not None:
            raise ValueError("A zero dividend must have a null payment date")
    return table.combine_chunks()
