"""Offline analysis of a single asset's adjusted daily closing prices."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PriceSummary:
    """Returns are fractions; drawdown is zero or negative."""

    observations: int
    start: str
    end: str
    total_return: float
    max_drawdown: float


def analyze_prices(path: str | Path) -> PriceSummary:
    """Validate and summarize a CSV with date and adjusted_close columns.

    Dates must be unique ISO calendar dates in ascending order. At least two
    observations and finite, strictly positive prices are required. Each row
    represents one trading session; missing sessions are not filled in.
    """
    try:
        frame = pd.read_csv(path, dtype=str)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError("Unable to read a valid price CSV.") from exc

    if not {"date", "adjusted_close"}.issubset(frame.columns):
        raise ValueError("CSV must contain date and adjusted_close columns.")
    if len(frame) < 2:
        raise ValueError("At least two price observations are required.")
    if not frame["date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").fillna(False).all():
        raise ValueError("Dates must use YYYY-MM-DD format.")

    try:
        dates = pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
    except ValueError as exc:
        raise ValueError("Dates must be valid calendar dates.") from exc
    if dates.duplicated().any():
        raise ValueError("Dates must be unique.")
    if not dates.is_monotonic_increasing:
        raise ValueError("Dates must be in ascending order.")

    try:
        prices = pd.to_numeric(frame["adjusted_close"], errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("Adjusted prices must be numeric.") from exc
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("Adjusted prices must be finite and greater than zero.")

    with np.errstate(over="raise", invalid="raise", divide="raise"):
        try:
            total_return = float(prices[-1] / prices[0] - 1)
            max_drawdown = float(np.min(prices / np.maximum.accumulate(prices) - 1))
        except FloatingPointError as exc:
            raise ValueError("Price range is too large to calculate finite returns.") from exc

    return PriceSummary(
        observations=len(frame),
        start=dates.iloc[0].date().isoformat(),
        end=dates.iloc[-1].date().isoformat(),
        total_return=total_return,
        max_drawdown=max_drawdown,
    )
