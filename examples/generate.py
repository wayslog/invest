"""Regenerate explicitly synthetic Parquet fixtures from source."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.market import BAR_SCHEMA

output = Path(__file__).resolve().parent
dates = [date(2024, 1, day) for day in [2, 3, 4, 5, 8]]
pq.write_table(
    pa.table(
        {
            "date": pa.array(dates, type=pa.date32()),
            "adjusted_close": [100.0, 102.0, 99.0, 105.0, 103.0],
        },
        metadata={b"source": b"synthetic", b"price_basis": b"adjusted"},
    ),
    output / "prices.parquet",
    compression="zstd",
)
closes = [
    100,
    101,
    102,
    103,
    104,
    106,
    108,
    110,
    112,
    114,
    111,
    108,
    104,
    100,
    98,
    96,
    97,
    99,
    102,
    105,
    108,
    110,
    113,
    116,
    118,
    115,
    112,
    109,
    106,
    103,
]
rows = []
session = date(2024, 1, 2)
for i, value in enumerate(closes):
    while session.weekday() >= 5 or session == date(2024, 1, 15):
        session += timedelta(days=1)
    opening = Decimal(closes[max(0, i - 1)])
    closing = Decimal(value)
    rows.append(
        {
            "date": session,
            "symbol": "DEMO",
            "open": opening,
            "high": max(opening, closing) + 1,
            "low": min(opening, closing) - 1,
            "close": closing,
            "volume": 1000000,
            "split_ratio": 1,
            "dividend": Decimal("0"),
            "dividend_pay_date": None,
        }
    )
    session += timedelta(days=1)
schema = BAR_SCHEMA.with_metadata({**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"})
pq.write_table(
    pa.Table.from_pylist(rows, schema=schema), output / "paper_bars.parquet", compression="zstd"
)
