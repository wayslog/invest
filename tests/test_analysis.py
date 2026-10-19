from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.analysis import analyze_prices


def write_prices(tmp_path: Path, prices: list[float | None]) -> Path:
    path = tmp_path / "prices.parquet"
    pq.write_table(
        pa.table(
            {
                "date": pa.array(
                    [date(2024, 1, 2) + timedelta(days=i) for i in range(len(prices))],
                    type=pa.date32(),
                ),
                "adjusted_close": pa.array(prices, type=pa.float64()),
            }
        ),
        path,
    )
    return path


@pytest.mark.parametrize(
    ("prices", "total", "drawdown"),
    [
        ([100, 120, 90, 110], 0.1, -0.25),
        ([100, 110, 120], 0.2, 0),
        ([100, 100, 100], 0, 0),
        ([100, 90, 80], -0.2, -0.2),
    ],
)
def test_price_paths(tmp_path: Path, prices: list[float], total: float, drawdown: float) -> None:
    result = analyze_prices(write_prices(tmp_path, list(prices)))
    assert result.observations == len(prices)
    assert result.start == "2024-01-02"
    assert result.total_return == pytest.approx(total)
    assert result.max_drawdown == pytest.approx(drawdown)


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), None])
def test_invalid_prices(tmp_path: Path, price: float | None) -> None:
    with pytest.raises(ValueError, match="prices must"):
        analyze_prices(write_prices(tmp_path, [100, price]))


def test_dates_need_arrow_date_type(tmp_path: Path) -> None:
    path = tmp_path / "prices.parquet"
    pq.write_table(
        pa.table({"date": ["2024-01-02", "2024-01-03"], "adjusted_close": [100, 101]}), path
    )
    with pytest.raises(ValueError, match="date32"):
        analyze_prices(path)


def test_out_of_order_dates(tmp_path: Path) -> None:
    path = write_prices(tmp_path, [100, 101])
    table = pq.read_table(path)
    pq.write_table(table.take([1, 0]), path)
    with pytest.raises(ValueError, match="ascending"):
        analyze_prices(path)


def test_price_overflow(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="too large"):
        analyze_prices(write_prices(tmp_path, [1e-300, 1e300]))
