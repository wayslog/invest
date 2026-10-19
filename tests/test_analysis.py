from pathlib import Path

import pytest

from invest.analysis import analyze_prices


def write_prices(tmp_path: Path, contents: str) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(contents, encoding="utf-8")
    return path


def test_returns_and_drawdown_use_observed_peaks(tmp_path: Path) -> None:
    path = write_prices(
        tmp_path,
        "date,adjusted_close\n2024-01-02,100\n2024-01-03,120\n2024-01-04,90\n2024-01-05,110\n",
    )
    result = analyze_prices(path)
    assert result.observations == 4
    assert result.start == "2024-01-02"
    assert result.end == "2024-01-05"
    assert result.total_return == pytest.approx(0.1)
    assert result.max_drawdown == pytest.approx(-0.25)


@pytest.mark.parametrize(
    ("prices", "expected_return", "expected_drawdown"),
    [([100, 110, 120], 0.2, 0.0), ([100, 100, 100], 0.0, 0.0), ([100, 90, 80], -0.2, -0.2)],
)
def test_price_paths(
    tmp_path: Path, prices: list[int], expected_return: float, expected_drawdown: float
) -> None:
    rows = "".join(f"2024-01-0{i + 2},{price}\n" for i, price in enumerate(prices))
    result = analyze_prices(write_prices(tmp_path, "date,adjusted_close\n" + rows))
    assert result.total_return == pytest.approx(expected_return)
    assert result.max_drawdown == pytest.approx(expected_drawdown)


@pytest.mark.parametrize("price", ["0", "-1", "nan", "inf", "-inf", "", "unknown"])
def test_rejects_invalid_prices(tmp_path: Path, price: str) -> None:
    path = write_prices(tmp_path, f"date,adjusted_close\n2024-01-02,100\n2024-01-03,{price}\n")
    with pytest.raises(ValueError, match="prices must be"):
        analyze_prices(path)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "valid price CSV"),
        ("date,close\n2024-01-02,100\n2024-01-03,101\n", "must contain"),
        ("date,adjusted_close\n", "At least two"),
        ("date,adjusted_close\n2024-01-02,100\n", "At least two"),
        ("date,adjusted_close\n2024-01-02,100\n2024-01-02,101\n", "unique"),
        ("date,adjusted_close\n2024-01-03,100\n2024-01-02,101\n", "ascending"),
        ("date,adjusted_close\n2024-02-30,100\n2024-03-01,101\n", "calendar"),
        ("date,adjusted_close\n2024-1-2,100\n2024-01-03,101\n", "YYYY-MM-DD"),
        ("date,adjusted_close\n,100\n2024-01-03,101\n", "YYYY-MM-DD"),
        ("date,adjusted_close\n2024-01-02T10:00:00,100\n2024-01-03,101\n", "YYYY-MM-DD"),
        ("date,adjusted_close\n2024-01-02,1e-300\n2024-01-03,1e300\n", "too large"),
    ],
)
def test_rejects_invalid_series(tmp_path: Path, contents: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        analyze_prices(write_prices(tmp_path, contents))
