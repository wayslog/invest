"""归因必须解释完整超额收益，并区分持仓、成交、成本和复利交互。"""

from datetime import date
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pytest

from invest.return_attribution import (
    EFFECTS,
    forward_holding_return,
    link_effects,
    portfolio_attribution,
)

D = Decimal


def test_linked_effects_reconcile_compounded_returns_and_are_symmetric() -> None:
    rows: list[dict[str, Any]] = [
        {
            "date": date(2025, 1, 2),
            "portfolio_return": 0.1,
            "benchmark_return": 0.05,
            "allocation": 0.03,
            "selection": 0.03,
            "trading": 0.0,
            "cost": -0.01,
        },
        {
            "date": date(2025, 1, 3),
            "portfolio_return": -0.05,
            "benchmark_return": 0.02,
            "allocation": -0.04,
            "selection": -0.03,
            "trading": 0.01,
            "cost": -0.01,
        },
    ]
    result = link_effects(rows).to_pylist()
    assert sum(r[f"linked_{k}"] for r in result for k in EFFECTS) == pytest.approx(
        1.1 * 0.95 - 1.05 * 1.02
    )
    swapped = [
        {
            **r,
            "portfolio_return": r["benchmark_return"],
            "benchmark_return": r["portfolio_return"],
            **{k: -r[k] for k in EFFECTS},
        }
        for r in rows
    ]
    reverse = link_effects(swapped).to_pylist()
    for a, b in zip(result, reverse, strict=True):
        for key in EFFECTS:
            assert a[f"linked_{key}"] == pytest.approx(-b[f"linked_{key}"])
    with pytest.raises(ValueError, match="reconcile"):
        link_effects([{**rows[0], "selection": 0.9}])
    with pytest.raises(ValueError, match="unique"):
        link_effects([rows[0], rows[0]])


def sample_tables() -> tuple[dict[str, pa.Table], pa.Table, pa.Table, pa.Table]:
    days = [date(2025, 1, 2), date(2025, 1, 3)]
    prices = {
        symbol: pa.Table.from_pylist(
            [
                {"date": days[0], "close": D(100), "dividend": D(0), "split_ratio": 1},
                {"date": days[1], "close": D(close), "dividend": D(dividend), "split_ratio": split},
            ]
        )
        for symbol, close, dividend, split in (("STOCK", 54, 1, 2), ("QQQ", 110, 0, 1))
    }
    equity = pa.Table.from_pylist(
        [
            {"date": days[0], "equity": D(999), "market_value": D(500)},
            {"date": days[1], "equity": D(1049), "market_value": D(540)},
        ]
    )
    positions = pa.Table.from_pylist(
        [
            {"date": days[0], "symbol": "STOCK", "shares": 5},
            {"date": days[1], "symbol": "STOCK", "shares": 10},
        ]
    )
    fills = pa.Table.from_pylist(
        [
            {
                "date": days[0],
                "commission": D(1),
                "price": D(100),
                "base_price": D(100),
                "quantity": 5,
            }
        ]
    )
    return prices, equity, positions, fills


def test_cash_cost_split_and_dividend_effects_reconcile_without_false_selection() -> None:
    prices, equity, positions, fills = sample_tables()
    days = equity["date"].to_pylist()
    reference = pa.Table.from_pylist(
        [
            {"date": days[0], "equity": D(1000), "market_value": D(1000)},
            {"date": days[1], "equity": D(1100), "market_value": D(1100)},
        ]
    )
    reference_positions = pa.Table.from_pylist(
        [{"date": day, "symbol": "QQQ", "shares": 10} for day in days]
    )
    result = portfolio_attribution(
        prices, equity, positions, fills, reference, reference_positions, fills.slice(0, 0), D(1000)
    ).to_pylist()
    assert result[1]["selection"] == pytest.approx(0)
    assert result[1]["trading"] == pytest.approx(0)
    assert result[1]["allocation"] < 0
    assert result[0]["cost"] == pytest.approx(-0.001)
    assert sum(r[f"linked_{k}"] for r in result for k in EFFECTS) == pytest.approx(-0.051)
    with pytest.raises(ValueError, match="market value"):
        portfolio_attribution(
            prices,
            equity,
            positions.slice(1),
            fills,
            reference,
            reference_positions,
            fills.slice(0, 0),
            D(1000),
        )
    with pytest.raises(ValueError, match="matching"):
        portfolio_attribution(
            prices,
            equity,
            positions,
            fills,
            reference.slice(1),
            reference_positions,
            fills.slice(0, 0),
            D(1000),
        )


def test_intraday_entry_gain_is_trading_not_previous_close_selection() -> None:
    prices, equity, positions, fills = sample_tables()
    equity = equity.set_column(1, "equity", pa.array([D(1009), D(1059)]))
    result = portfolio_attribution(
        prices, equity, positions, fills, equity, positions, fills, D(1000), benchmark="STOCK"
    ).to_pylist()
    assert all(abs(r[f"linked_{k}"]) < 1e-12 for r in result for k in EFFECTS)


def test_forward_label_excludes_entry_dividend_and_handles_later_split() -> None:
    rows = [
        {
            "date": date(2025, 1, 2),
            "open": D(100),
            "close": D(102),
            "split_ratio": 1,
            "dividend": D(9),
        },
        {
            "date": date(2025, 1, 3),
            "open": D(51),
            "close": D(54),
            "split_ratio": 2,
            "dividend": D(1),
        },
    ]
    assert forward_holding_return(rows) == pytest.approx(0.10)
    assert forward_holding_return(rows[:1]) == pytest.approx(0.02)
    with pytest.raises(ValueError, match="unique"):
        forward_holding_return(rows[::-1])
