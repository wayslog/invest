"""调仓频率、纯持有和仅进出场对照的真实交易行为。"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest

from invest.backtest import simulate_signals
from invest.contracts import SignalFrame
from invest.portfolio_audit import audit_backtest
from invest.quality import regular_sessions
from invest.rebalance import buy_hold_inputs, entry_exit_selections, schedule_selections
from invest.weekly_selection import WeeklySelection
from invest.weekly_universe import weekly_schedule
from tests.test_backtest import policy
from tests.test_decisions import signals
from tests.test_portfolio import bars

D = Decimal


def choices(days: list[date]) -> dict[date, WeeklySelection]:
    return {
        day: WeeklySelection(
            ("ALPHA",) if index < 5 else ("BETA",),
            "rank_rotation",
            signals(day).table["available_at"][0].as_py(),
            str(index // 5),
            index % 5 == 0,
            (("ALPHA", "BETA", 0.2),),
        )
        for index, day in enumerate(days)
    }


def test_monthly_schedule_uses_execution_month_and_ignores_future_lists() -> None:
    start, end = date(2025, 7, 7), date(2026, 10, 23)
    weeks = weekly_schedule(start, end)
    decisions = {r["price_as_of"]: r for r in weeks}
    days = regular_sessions(weeks[0]["price_as_of"], end).to_pylist()
    contexts = {
        r["date"]: WeeklySelection(
            ("ALPHA",),
            "rank_rotation",
            decisions[r["date"]]["decision_at"] if r["date"] in decisions else r["close_at"],
            r["date"].isoformat(),
            r["date"] in decisions,
        )
        for r in days
    }
    for frequency, count in (("weekly", 68), ("biweekly", 34), ("monthly", 16), ("quarterly", 6)):
        result = schedule_selections(contexts, frequency, "rank_rotation")
        assert sum(c.rebalance for c in result.values()) == count
        earlier = {d: c for d, c in contexts.items() if d <= date(2025, 10, 15)}
        assert schedule_selections(earlier, frequency, "rank_rotation") == {
            d: c for d, c in result.items() if d in earlier
        }
    monthly = schedule_selections(contexts, "monthly", "rank_rotation")
    # 八月最后一个周五对应九月首个成交会话，不能延后一个周度。
    assert monthly[date(2025, 8, 29)].rebalance
    assert not monthly[date(2025, 9, 5)].rebalance


def test_biweekly_freezes_candidates_and_finishes_settlement_before_next_review() -> None:
    inputs = {s: bars(s, [100] * 16) for s in ("ALPHA", "BETA")}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(d).table for d in days]))
    settings = policy(sale_proceeds="next_session")
    paths = {}
    for frequency in ("weekly", "biweekly"):
        contexts = schedule_selections(choices(days), frequency, "rank_rotation")
        result = simulate_signals(
            inputs, history, settings, days[1], days[-1], initial_cash=D(1000), selections=contexts
        )
        paths[frequency] = result.portfolio.trades.to_pylist()
        assert set(
            audit_backtest(inputs, result.portfolio, settings, D(1000))[0]["status"].to_pylist()
        ) == {"pass"}
    assert paths["weekly"][1]["date"] == days[6]
    assert paths["biweekly"][1]["date"] == days[11]
    assert paths["biweekly"][2]["date"] == days[13]
    assert [r["side"] for r in paths["biweekly"]] == ["buy", "sell", "buy"]
    planned = schedule_selections(choices(days), "biweekly", "rank_rotation")
    assert planned[days[7]].candidates == ("ALPHA",)
    assert not planned[days[7]].allow_entries
    changed = {
        d: replace(c, candidates=("BETA",)) if i >= 10 else c
        for i, (d, c) in enumerate(choices(days).items())
    }
    assert {
        d: c
        for d, c in schedule_selections(changed, "biweekly", "rank_rotation").items()
        if d < days[10]
    } == {d: c for d, c in planned.items() if d < days[10]}


def test_buy_hold_keeps_initial_basket_and_split_dividends_without_trimming() -> None:
    inputs = {
        "ALPHA": bars(
            "ALPHA",
            [100, 100, 200, 100, 100, 100],
            updates={
                3: {"split_ratio": 2, "dividend": D(2), "dividend_pay_date": date(2024, 1, 8)}
            },
        ),
        "BETA": bars("BETA", [100] * 6),
    }
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(d).table for d in days]))
    settings = policy(
        allocation=D(".75"), position_cap=D(".25"), stop_loss=D(".1"), take_profit=D(".2")
    )
    contexts, frame, settings = buy_hold_inputs(choices(days), history, settings)
    result = simulate_signals(
        inputs, frame, settings, days[1], days[-1], initial_cash=D(1000), selections=contexts
    )
    fills = result.portfolio.trades.to_pylist()
    assert len(fills) == 1 and fills[0]["symbol"] == "ALPHA" and fills[0]["quantity"] == 2
    assert result.final_account.holdings[0].shares == 4
    assert result.final_account.cash == D(807)
    assert result.portfolio.equity["equity"][-1].as_py() == D(1207)
    assert set(
        audit_backtest(inputs, result.portfolio, settings, D(1000))[0]["status"].to_pylist()
    ) == {"pass"}
    assert not any(row["action"] in {"ADD", "SELL", "TRIM"} for row in result.actions.to_pylist())


def test_entry_only_does_not_resize_but_keeps_independent_exit() -> None:
    inputs = {
        "ALPHA": bars("ALPHA", [100, 100, 200, 200, 200, 200]),
        "BETA": bars("BETA", [100] * 6),
    }
    days = inputs["ALPHA"]["date"].to_pylist()
    rows = pa.concat_tables([signals(d).table for d in days]).to_pylist()
    for row in rows:
        if row["date"] >= days[3] and row["instrument"] == "ALPHA":
            row.update(direction=0, score=0.0)
    frame = SignalFrame(pa.Table.from_pylist(rows, schema=signals().table.schema))
    contexts = entry_exit_selections(choices(days))
    result = simulate_signals(
        inputs,
        frame,
        policy(allocation=D(".75"), position_cap=D(".25")),
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts,
    )
    fills = result.portfolio.trades.to_pylist()
    assert [(r["side"], r["quantity"], r["reason"]) for r in fills] == [
        ("buy", 2, "rank_selection"),
        ("sell", 2, "signal_exit"),
    ]


def test_entry_window_cannot_reopen_after_risk_exit_and_hold_has_no_delayed_entry() -> None:
    inputs = {"ALPHA": bars("ALPHA", [100, 100, 100, 80, 100, 100, 100, 100])}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(d).table for d in days]))
    contexts = schedule_selections(choices(days), "quarterly", "rank_rotation")
    result = simulate_signals(
        inputs,
        history,
        policy(stop_loss=D(".1"), cooldown_sessions=0),
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts,
    )
    assert [(r["side"], r["date"]) for r in result.portfolio.trades.to_pylist()] == [
        ("buy", days[1]),
        ("sell", days[4]),
    ]
    closed = {d: replace(c, allow_entries=False) for d, c in contexts.items()}
    empty = simulate_signals(
        inputs, history, policy(), days[1], days[-1], initial_cash=D(1000), selections=closed
    )
    assert empty.portfolio.trades.num_rows == 0
    with pytest.raises(ValueError, match="frequency"):
        schedule_selections(choices(days), "daily", "rank_rotation")


def test_initial_empty_basket_stays_cash_and_missing_sessions_are_rejected() -> None:
    inputs = {"ALPHA": bars("ALPHA", [100] * 8)}
    days = inputs["ALPHA"]["date"].to_pylist()
    history = SignalFrame(pa.concat_tables([signals(d).table for d in days]))
    original = choices(days)
    original[days[0]] = replace(original[days[0]], candidates=())
    contexts, frame, settings = buy_hold_inputs(original, history, policy())
    result = simulate_signals(
        inputs, frame, settings, days[1], days[-1], initial_cash=D(1000), selections=contexts
    )
    assert result.portfolio.trades.num_rows == 0
    assert result.final_account.cash == D(1000)
    with pytest.raises(ValueError, match="consecutive"):
        schedule_selections(
            {d: c for d, c in original.items() if d != days[2]}, "weekly", "rank_rotation"
        )


def test_buy_hold_survives_large_drawdown_without_account_risk_liquidation() -> None:
    inputs = {"ALPHA": bars("ALPHA", [100, 100, 40, 40, 120, 120])}
    days = inputs["ALPHA"]["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(d).table for d in days]))
    contexts, frame, settings = buy_hold_inputs(choices(days), frame, policy(), fully_invested=True)
    result = simulate_signals(
        inputs, frame, settings, days[1], days[-1], initial_cash=D(1000), selections=contexts
    )
    assert result.portfolio.trades.num_rows == 1
    assert result.final_account.holdings[0].shares == 9
    assert result.portfolio.equity["equity"][-1].as_py() == D(1179)
