"""Offline analysis of a single asset's adjusted daily closing prices."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class PriceSummary:
    """Returns are fractions; drawdown is zero or negative."""

    observations: int
    start: str
    end: str
    total_return: float
    max_drawdown: float


def analyze_prices(path: str | Path) -> PriceSummary:
    """Summarize a Parquet series with Arrow date32 and numeric prices."""
    path = Path(path)
    if path.suffix.lower() != ".parquet":
        raise ValueError("Prices must be a .parquet file")
    table = pq.read_table(path)
    if not {"date", "adjusted_close"}.issubset(table.column_names):
        raise ValueError("Parquet must contain date and adjusted_close columns")
    if table.schema.field("date").type != pa.date32():
        raise ValueError("date must use the Arrow date32 type")
    if table.num_rows < 2:
        raise ValueError("At least two price observations are required")
    if table["date"].null_count or table["adjusted_close"].null_count:
        raise ValueError("Dates and prices must not be null")
    dates = table["date"].to_pylist()
    if any(right <= left for left, right in zip(dates, dates[1:], strict=False)):
        raise ValueError("Dates must be unique and in ascending order")
    price_type = table.schema.field("adjusted_close").type
    if not (
        pa.types.is_floating(price_type)
        or pa.types.is_integer(price_type)
        or pa.types.is_decimal(price_type)
    ):
        raise ValueError("Adjusted prices must use a numeric Arrow type")
    prices = np.asarray(table["adjusted_close"].to_pylist(), dtype=np.float64)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("Adjusted prices must be finite and greater than zero")

    with np.errstate(over="raise", invalid="raise", divide="raise"):
        try:
            total_return = float(prices[-1] / prices[0] - 1)
            max_drawdown = float(np.min(prices / np.maximum.accumulate(prices) - 1))
        except FloatingPointError as exc:
            raise ValueError("Price range is too large to calculate finite returns.") from exc

    return PriceSummary(
        observations=len(dates),
        start=dates[0].isoformat(),
        end=dates[-1].isoformat(),
        total_return=total_return,
        max_drawdown=max_drawdown,
    )
