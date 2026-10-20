"""Create deterministic synthetic ETF bars for the offline M2 workflow."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa

from invest.market import BAR_SCHEMA
from invest.quality import regular_sessions
from invest.research_registry import write_table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dates = regular_sessions(date(2021, 1, 4), date(2026, 6, 30))["date"].to_pylist()
    rng = np.random.default_rng(20261020)
    common = rng.normal(0.00015, 0.007, len(dates))
    for symbol in ["SPY", "XLF", "XLK"]:
        changes = common + rng.normal(0.00005, 0.004, len(dates))
        close = Decimal(100)
        rows = []
        for session, change in zip(dates, changes, strict=True):
            opening = close
            close = (close * Decimal(str(1 + change))).quantize(Decimal(".000001"))
            rows.append(
                {
                    "date": session,
                    "symbol": symbol,
                    "open": opening,
                    "high": max(opening, close) + 1,
                    "low": min(opening, close) - 1,
                    "close": close,
                    "volume": 1000000,
                    "split_ratio": 1,
                    "dividend": Decimal(0),
                    "dividend_pay_date": None,
                }
            )
        write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}
                ),
            ),
            args.output / f"{symbol}.parquet",
        )


if __name__ == "__main__":
    main()
