"""QQQ 承接方案必须遵守个股预算、账户风控和真实交收。"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest

from invest.backtest import simulate_signals
from invest.cash_sweep import cash_sweep_plan
from invest.contracts import (
    AccountSnapshot,
    Holding,
    PositionState,
    Quote,
    SignalFrame,
    StrategyState,
)
from invest.portfolio_audit import audit_backtest
from invest.weekly_selection import WeeklySelection
from tests.test_backtest import policy
from tests.test_decisions import signals
from tests.test_portfolio import bars

D = Decimal


def contexts(days: list[date], first_stock_index: int = 2) -> dict[date, WeeklySelection]:
    return {
        day: WeeklySelection(
            () if index < first_stock_index else ("ALPHA",),
            "hold_until_exit",
            signals(day).table["available_at"][0].as_py(),
            str(index),
            False,
            resize_existing=False,
            enforce_exposure=False,
        )
        for index, day in enumerate(days)
    }


def test_cash_sweep_sells_etf_then_waits_for_settlement_and_reconciles() -> None:
    inputs = {symbol: bars(symbol, [100] * 8) for symbol in ("ALPHA", "QQQ")}
    days = inputs["ALPHA"]["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(allocation=D(".75"), position_cap=D(".25"), sale_proceeds="next_session")
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts(days),
        cash_sweep="QQQ",
    )
    fills = result.portfolio.trades.to_pylist()
    assert [(r["date"], r["symbol"], r["side"], r["quantity"]) for r in fills[:3]] == [
        (days[1], "QQQ", "buy", 9),
        (days[3], "QQQ", "sell", 2),
        (days[4], "ALPHA", "buy", 2),
    ]
    assert not any(
        r["symbol"] == "ALPHA" and r["side"] == "buy" and r["date"] == days[3] for r in fills
    )
    assert not any(
        r["symbol"] == "QQQ" and r["side"] == "sell" and r["date"] == days[4] for r in fills
    )
    checks = audit_backtest(inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ")[0]
    assert set(checks["status"].to_pylist()) == {"pass"}
    assert min(result.portfolio.equity["cash"].to_pylist()) >= 0


def test_cash_sweep_is_not_subject_to_stock_take_profit() -> None:
    inputs = {
        "ALPHA": bars("ALPHA", [100] * 5),
        "QQQ": bars("QQQ", [100, 100, 150, 150, 150]),
    }
    days = inputs["ALPHA"]["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(take_profit=D(".2"), exit_mode="protective")
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts(days, first_stock_index=99),
        cash_sweep="QQQ",
    )
    fills = result.portfolio.trades.to_pylist()
    assert [(f["symbol"], f["side"]) for f in fills] == [("QQQ", "buy")]
    assert set(
        audit_backtest(inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ")[0][
            "status"
        ].to_pylist()
    ) == {"pass"}


def test_point_in_time_risk_cap_reduces_entry_without_changing_cash_accounting() -> None:
    inputs = {symbol: bars(symbol, [100] * 5) for symbol in ("ALPHA", "QQQ")}
    days = inputs["ALPHA"]["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(allocation=D(".75"), position_cap=D(".25"))
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts(days, first_stock_index=0),
        cash_sweep="QQQ",
        risk_caps={day: {"ALPHA": D(".1")} for day in days},
    )
    fills = result.portfolio.trades.to_pylist()
    assert [(f["symbol"], f["side"], f["quantity"]) for f in fills] == [
        ("ALPHA", "buy", 1),
        ("QQQ", "buy", 8),
    ]
    assert set(
        audit_backtest(inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ")[0][
            "status"
        ].to_pylist()
    ) == {"pass"}


def test_halted_state_liquidates_etf_and_never_restarts_or_buys_stock() -> None:
    day = date(2024, 1, 3)
    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        day,
        D(1000),
        D(100),
        (Quote("ALPHA", D(100)), Quote("QQQ", D(100))),
        holdings=(Holding("QQQ", 9, D(100)),),
    )
    state = StrategyState(
        D(1200), risk_status="halted", positions=(PositionState("QQQ", day, D(100)),)
    )
    plan = cash_sweep_plan(signals(day), account, state, policy(), contexts([day], 0)[day])
    q = next(row for row in plan.actions.to_pylist() if row["instrument"] == "QQQ")
    assert (q["action"], q["quantity"], q["reason"]) == ("SELL", 9, "halted")
    assert all(row["action"] not in {"BUY", "ADD"} for row in plan.actions.to_pylist())
    assert plan.state.risk_status == "halted"
    with pytest.raises(ValueError, match="available benchmark"):
        cash_sweep_plan(
            signals(day),
            replace(
                account, quotes=(Quote("ALPHA", D(100)), Quote("QQQ", D(100), available=False))
            ),
            state,
            policy(),
            contexts([day], 0)[day],
        )


def test_atr_stop_uses_previous_session_distance_adjusted_for_split() -> None:
    alpha = bars(
        "ALPHA",
        [100] * 5,
        updates={2: {"split_ratio": 2, "open": D(50), "high": D(50), "low": D(44), "close": D(48)}},
    )
    inputs = {"ALPHA": alpha, "QQQ": bars("QQQ", [100] * 5)}
    days = alpha["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = policy(
        allocation=D(".75"),
        position_cap=D(".25"),
        commission=D(0),
        exit_mode="protective",
        cooldown_sessions=5,
    )
    distances = {day: {"ALPHA": D(10)} for day in days}
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts(days, first_stock_index=0),
        cash_sweep="QQQ",
        risk_caps={day: {"ALPHA": D(".1")} for day in days},
        atr_stops=distances,
    )
    fills = result.portfolio.trades.to_pylist()
    sale = next(f for f in fills if f["symbol"] == "ALPHA" and f["side"] == "sell")
    assert (sale["quantity"], sale["price"], sale["reason"], sale["stop_price"]) == (
        2,
        D(45),
        "atr_stop",
        D(45),
    )
    checks = audit_backtest(
        inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ", atr_stops=distances
    )[0]
    assert set(checks["status"].to_pylist()) == {"pass"}
