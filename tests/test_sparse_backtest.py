"""上市前不补价格，缺少持仓价格时停止，不重置连续账户。"""

from decimal import Decimal

import pyarrow as pa
import pytest

from invest.backtest import simulate_signals
from invest.contracts import SignalFrame
from invest.portfolio_audit import audit_backtest
from tests.test_backtest import policy
from tests.test_cash_sweep import contexts
from tests.test_decisions import signals
from tests.test_portfolio import bars


def test_sparse_listing_has_no_prelisting_fills_and_reconciles() -> None:
    complete = bars("ALPHA", [100] * 8)
    days = complete["date"].to_pylist()
    inputs = {
        "ALPHA": complete.slice(2),
        "SPY": bars("SPY", [100] * 8),
        "QQQ": bars("QQQ", [100] * 8),
    }
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    choices = contexts(days)
    settings = policy(
        allocation=Decimal(".75"), position_cap=Decimal(".25"), sale_proceeds="next_session"
    )
    with pytest.raises(ValueError, match="identical XNYS"):
        simulate_signals(
            inputs, frame, settings, days[1], days[-1], selections=choices, cash_sweep="QQQ"
        )
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=Decimal(1000),
        selections=choices,
        cash_sweep="QQQ",
        allow_sparse_inputs=True,
    )
    stock = [row for row in result.portfolio.trades.to_pylist() if row["symbol"] == "ALPHA"]
    assert stock and min(row["date"] for row in stock) > days[2]
    checks = audit_backtest(
        inputs,
        result.portfolio,
        settings,
        Decimal(1000),
        cash_sweep="QQQ",
        decision_times={day: choice.decision_at for day, choice in choices.items()},
        allow_sparse_inputs=True,
    )[0]
    assert set(checks["status"].to_pylist()) == {"pass"}


def test_sparse_held_gap_stops_instead_of_imputing_price() -> None:
    complete = bars("ALPHA", [100] * 5)
    days = complete["date"].to_pylist()
    sparse = complete.filter(pa.array([True, True, False, True, True]))
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    with pytest.raises(ValueError, match="Missing held execution price: ALPHA"):
        simulate_signals(
            {"ALPHA": sparse, "QQQ": bars("QQQ", [100] * 5)},
            frame,
            policy(),
            days[1],
            days[-1],
            initial_cash=Decimal(1000),
            selections=contexts(days, 0),
            cash_sweep="QQQ",
            allow_sparse_inputs=True,
        )


def test_sparse_missing_order_session_cancels_without_fill() -> None:
    complete = bars("ALPHA", [100] * 5)
    days = complete["date"].to_pylist()
    sparse = complete.filter(pa.array([True, False, True, True, True]))
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    inputs = {"ALPHA": sparse, "SPY": bars("SPY", [100] * 5), "QQQ": bars("QQQ", [100] * 5)}
    settings = policy()
    choices = contexts(days, 0)
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=Decimal(1000),
        selections=choices,
        cash_sweep="QQQ",
        allow_sparse_inputs=True,
    )
    assert any(row["reason"] == "missing_execution_price" for row in result.outcomes.to_pylist())
    assert not any(
        row["symbol"] == "ALPHA" and row["date"] == days[1]
        for row in result.portfolio.trades.to_pylist()
    )
    checks = audit_backtest(
        inputs,
        result.portfolio,
        settings,
        Decimal(1000),
        cash_sweep="QQQ",
        decision_times={day: choice.decision_at for day, choice in choices.items()},
        allow_sparse_inputs=True,
    )[0]
    assert set(checks["status"].to_pylist()) == {"pass"}


def test_empty_stock_signals_allow_only_benchmark_cash_sweep() -> None:
    inputs = {symbol: bars(symbol, [100] * 5) for symbol in ("SPY", "QQQ")}
    days = inputs["QQQ"]["date"].to_pylist()
    frame = SignalFrame(signals(days[0]).table.slice(0, 0))
    result = simulate_signals(
        inputs,
        frame,
        policy(),
        days[1],
        days[-1],
        initial_cash=Decimal(1000),
        selections=contexts(days, 99),
        cash_sweep="QQQ",
    )
    assert result.portfolio.trades.num_rows > 0
    assert set(result.portfolio.trades["symbol"].to_pylist()) == {"QQQ"}
