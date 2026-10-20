from dataclasses import replace
from decimal import Decimal

import pytest

from invest.paper import simulate
from tests.helpers import BASE, make_bars


def test_signals_fill_next_open_and_account_reconciles() -> None:
    bars = make_bars([100, 110, 120, 100, 95], [100, 100, 110, 120, 90])
    result = simulate(bars, BASE)
    trades = result.trades.to_pylist()
    dates = bars["date"].to_pylist()
    assert len(trades) == 2
    assert trades[0]["decision_date"] == dates[1]
    assert trades[0]["date"] == dates[2]
    assert trades[0]["quantity"] == 45
    assert trades[1]["date"] == dates[4]
    assert trades[1]["price"] == 90
    assert trades[1]["reason"] == "trend_exit"
    for row in result.equity.to_pylist():
        assert row["equity"] == row["cash"] + row["market_value"] + row["receivables"]
        assert row["cash"] >= 0
    assert result.metrics.to_pylist()[0]["final_equity"] == Decimal("4100")
    prefix = simulate(bars.slice(0, 3), BASE)
    assert prefix.equity.equals(result.equity.slice(0, 3))
    assert prefix.trades.equals(result.trades.slice(0, 1))


def test_last_signal_is_pending_not_filled_at_last_close() -> None:
    result = simulate(make_bars([100, 110]), BASE)
    assert result.trades.num_rows == 0
    assert result.equity.to_pylist()[-1]["pending_side"] == "buy"


def test_opening_gap_reduces_shares_without_borrowing() -> None:
    result = simulate(make_bars([100, 110, 210], [100, 100, 200]), BASE)
    trade = result.trades.to_pylist()[0]
    assert trade["quantity"] == 25
    assert trade["cash_after"] == 0
    assert "order_reduced" in result.events["kind"].to_pylist()


def test_fees_and_slippage_are_charged() -> None:
    config = replace(BASE, commission=Decimal("2"), slippage_bps=Decimal("100"))
    result = simulate(make_bars([100, 110, 120], [100, 100, 100]), config)
    trade = result.trades.to_pylist()[0]
    assert trade["price"] == 101
    assert trade["quantity"] == 44
    assert trade["commission"] == 2
    assert trade["cash_after"] == 554
    assert result.metrics.to_pylist()[0]["commissions"] == 2


@pytest.mark.parametrize(
    ("closes", "opens", "reason", "final_cash"),
    [
        ([100, 110, 120, 80, 90, 120], [100, 100, 110, 120, 75, 90], "warning", 3425),
        ([100, 110, 120, 50, 55, 120], [100, 100, 110, 120, 45, 55], "terminated", 2075),
    ],
)
def test_capital_rules_latch_and_gaps_can_exceed_floor(
    closes: list[int],
    opens: list[int],
    reason: str,
    final_cash: int,
) -> None:
    result = simulate(make_bars(closes, opens), BASE)
    trades = result.trades.to_pylist()
    assert len(trades) == 2
    assert trades[-1]["reason"] == reason
    assert trades[-1]["cash_after"] == final_cash
    assert result.equity.to_pylist()[-1]["status"] == reason
    assert result.equity.to_pylist()[-1]["shares"] == 0
    assert "capital_warning" in result.events["kind"].to_pylist()


@pytest.mark.parametrize(
    ("overrides", "closes", "reason"),
    [
        ({"stop_loss": Decimal(".02")}, [100, 110, 120, 105, 110], "stop_loss"),
        ({"trailing_stop": Decimal(".1")}, [100, 110, 140, 125, 130], "trailing_stop"),
        ({"account_drawdown": Decimal(".1")}, [100, 110, 140, 120, 130], "halted"),
    ],
)
def test_distinct_exit_layers(
    overrides: dict[str, Decimal], closes: list[int], reason: str
) -> None:
    config = replace(
        BASE,
        stop_loss=overrides.get("stop_loss", BASE.stop_loss),
        trailing_stop=overrides.get("trailing_stop", BASE.trailing_stop),
        account_drawdown=overrides.get("account_drawdown", BASE.account_drawdown),
    )
    result = simulate(make_bars(closes), config)
    assert result.trades.to_pylist()[-1]["reason"] == reason


def test_dividends_are_receivable_until_payment_date() -> None:
    bars = make_bars([100, 110, 120, 121, 122, 123])
    payment = bars["date"].to_pylist()[5]
    bars = make_bars(
        [100, 110, 120, 121, 122, 123],
        updates={
            2: {"dividend": Decimal("1"), "dividend_pay_date": payment},
            3: {"dividend": Decimal("1"), "dividend_pay_date": payment},
        },
    )
    result = simulate(bars, BASE)
    equity = result.equity.to_pylist()
    assert equity[2]["receivables"] == 0  # Bought on ex-date: no entitlement.
    assert equity[3]["receivables"] == 45
    assert equity[3]["cash"] == 50
    assert equity[5]["receivables"] == 0
    assert equity[5]["cash"] == 95


def test_forward_split_preserves_account_value_and_adjusts_signals() -> None:
    bars = make_bars([100, 110, 120, 60], [100, 100, 110, 60], {3: {"split_ratio": 2}})
    result = simulate(bars, BASE)
    rows = result.equity.to_pylist()
    assert rows[-1]["shares"] == 90
    assert rows[-1]["equity"] == rows[-2]["equity"]
    assert rows[-1]["status"] == "active"


def test_pending_order_is_adjusted_on_split() -> None:
    bars = make_bars([100, 110, 60], [100, 100, 55], {2: {"split_ratio": 2}})
    result = simulate(bars, BASE)
    assert result.trades.to_pylist()[0]["quantity"] == 90
    assert result.equity.to_pylist()[-1]["cash"] == 50


def test_zero_volume_rejects_history_instead_of_using_future_volume_for_open_fills() -> None:
    bars = make_bars([100, 110, 120, 130], updates={2: {"volume": 0}})
    with pytest.raises(ValueError, match="Zero-volume"):
        simulate(bars, BASE)
