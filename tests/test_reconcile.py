from dataclasses import replace
from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest

from invest.paper import Account, Order, simulate
from invest.reconcile import reconcile
from tests.helpers import BASE, make_bars


def test_dividend_does_not_create_false_stop_or_trend_exit() -> None:
    bars = make_bars(
        [100, 110, 120, 101, 102],
        [100, 100, 110, 100, 101],
        {3: {"dividend": Decimal(20), "dividend_pay_date": date(2024, 1, 8)}},
    )
    config = replace(BASE, stop_loss=Decimal(".05"), trailing_stop=Decimal(".05"))
    result = simulate(bars, config)
    assert result.trades.num_rows == 1
    assert result.equity["pending_side"].to_pylist()[-2:] == [None, None]
    assert result.equity["receivables"].to_pylist()[3] == 900
    assert result.equity["cash"].to_pylist()[-1] == 950
    assert "error" not in reconcile(bars, result, config)["status"].to_pylist()


def test_real_loss_after_dividend_still_exits() -> None:
    bars = make_bars(
        [100, 110, 120, 80, 81],
        [100, 100, 110, 80, 81],
        {3: {"dividend": Decimal(20), "dividend_pay_date": date(2024, 1, 8)}},
    )
    config = replace(BASE, stop_loss=Decimal(".05"))
    result = simulate(bars, config)
    assert result.trades["reason"].to_pylist()[-1] == "stop_loss"
    assert "error" not in reconcile(bars, result, config)["status"].to_pylist()


def test_split_dividend_cash_flows_and_rounding_reconcile() -> None:
    bars = make_bars(
        [100, 110, 120, 61, 62, 63],
        [100, 100, 110, 60, 61, 62],
        {
            3: {"split_ratio": 2},
            4: {"dividend": Decimal(".123456"), "dividend_pay_date": date(2024, 1, 9)},
        },
    )
    config = replace(BASE, commission=Decimal("1.234567"), slippage_bps=Decimal("5"))
    result = simulate(bars, config)
    checks = reconcile(bars, result, config)
    assert set(checks["account"].to_pylist()) == {"strategy", "benchmark"}
    assert "error" not in checks["status"].to_pylist()
    assert result.equity["receivables"].to_pylist()[4] > 0
    assert result.equity["receivables"].to_pylist()[5] == 0


@pytest.mark.parametrize("field", ["cash", "shares", "receivables", "equity", "benchmark_equity"])
def test_independent_reconciliation_detects_corrupted_balances(field: str) -> None:
    bars = make_bars([100, 110, 120, 121])
    result = simulate(bars, BASE)
    rows = result.equity.to_pylist()
    rows[-1][field] += 1
    altered = replace(result, equity=pa.Table.from_pylist(rows, schema=result.equity.schema))
    assert "error" in reconcile(bars, altered, BASE)["status"].to_pylist()


def test_reconciliation_detects_missing_and_backdated_fills() -> None:
    bars = make_bars([100, 110, 120, 121])
    result = simulate(bars, BASE)
    missing = replace(result, trades=result.trades.slice(0, 0))
    assert "error" in reconcile(bars, missing, BASE)["status"].to_pylist()
    trades = result.trades.to_pylist()
    trades[0]["decision_date"] = trades[0]["date"]
    backdated = replace(result, trades=pa.Table.from_pylist(trades, schema=result.trades.schema))
    failed = [
        row for row in reconcile(bars, backdated, BASE).to_pylist() if row["status"] == "error"
    ]
    assert any(row["check"] == "order_timing_and_identity" for row in failed)


def test_order_expires_after_its_next_session_but_holidays_do_not_count() -> None:
    account = Account(cash=Decimal(5000))
    account.pending = Order(date(2024, 1, 12), "buy", 10, "test")
    account.execute(date(2024, 1, 16), Decimal(100), BASE)
    assert len(account.trades) == 1  # Monday is MLK Day.
    stale = Account(cash=Decimal(5000))
    stale.pending = Order(date(2024, 1, 12), "buy", 10, "test")
    stale.execute(date(2024, 1, 17), Decimal(100), BASE)
    assert stale.pending is None and stale.shares == 0
    assert stale.events[-1]["kind"] == "order_expired"


def test_missing_session_blocks_simulation_instead_of_late_fill() -> None:
    bars = make_bars([100, 110, 120, 130]).take([0, 1, 3])
    with pytest.raises(ValueError, match="complete XNYS"):
        simulate(bars, BASE)


def test_open_proxy_does_not_change_with_positive_end_of_day_volume() -> None:
    bars = make_bars([100, 110, 120, 130])
    other = make_bars([100, 110, 120, 130], updates={2: {"volume": 1}, 3: {"volume": 999999}})
    assert simulate(bars, BASE).trades.equals(simulate(other, BASE).trades)
