from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from invest.evaluation import evaluate
from invest.market import BAR_SCHEMA
from invest.paper import Account, Order
from invest.portfolio import simulate_portfolio
from invest.portfolio_audit import audit_portfolio
from invest.quality import regular_sessions
from invest.strategies import Candidate, RotationSignal, TrendSignal, target_weights
from invest.study_config import StudyConfig, parse_study

D = Decimal


def study_config() -> StudyConfig:
    return replace(
        parse_study(Path("configs/m2.toml").read_bytes()),
        symbols=("SPY", "XLF"),
        lookbacks=(2, 3),
        correlation_window=3,
        rebalance_sessions=3,
        stop_loss=D(1),
        trailing_stop=D(1),
        account_drawdown=D(1),
    )


def bars(
    symbol: str,
    prices: list[int],
    *,
    opens: list[int] | None = None,
    updates: dict[int, dict[str, object]] | None = None,
) -> pa.Table:
    sessions = regular_sessions(date(2024, 1, 2), date(2024, 4, 1))["date"].to_pylist()
    rows = []
    for i, value in enumerate(prices):
        opening, closing = D(opens[i] if opens else value), D(value)
        row = {
            "date": sessions[i],
            "symbol": symbol,
            "open": opening,
            "close": closing,
            "high": max(opening, closing) + 1,
            "low": min(opening, closing) - 1,
            "volume": 1000,
            "split_ratio": 1,
            "dividend": D(0),
            "dividend_pay_date": None,
        }
        row.update((updates or {}).get(i, {}))
        rows.append(row)
    return pa.Table.from_pylist(
        rows,
        schema=BAR_SCHEMA.with_metadata({**(BAR_SCHEMA.metadata or {}), b"source": b"synthetic"}),
    )


def test_shared_cash_and_adverse_open_reduce_whole_share_orders() -> None:
    inputs = {s: bars(s, [100] * 4 + [180] * 4) for s in ["SPY", "XLF"]}
    config = study_config()
    dates = inputs["SPY"]["date"].to_pylist()
    result = simulate_portfolio(inputs, config, Candidate("buy_hold"), dates[4], dates[-1])
    trades = result.trades.to_pylist()
    assert [r["symbol"] for r in trades] == ["SPY", "XLF"]
    assert [r["quantity"] for r in trades] == [20, 2]
    assert trades[1]["cash_after"] == D("1036.020000")
    assert min(result.equity["cash"].to_pylist()) >= 0
    assert max(result.equity["gross_exposure"].to_pylist()) <= 0.8
    audit, _, _ = audit_portfolio(inputs, result, config)
    assert set(audit["status"].to_pylist()) == {"pass"}


def test_next_session_no_future_price_leakage_and_missing_sessions_fail() -> None:
    config = study_config()
    inputs = {
        "SPY": bars("SPY", [100, 101, 103, 102, 105, 104, 107, 108, 110, 109]),
        "XLF": bars("XLF", [90, 93, 91, 94, 92, 95, 93, 96, 94, 97]),
    }
    dates = inputs["SPY"]["date"].to_pylist()
    full = simulate_portfolio(inputs, config, Candidate("rotation", 3), dates[4], dates[-1])
    short = simulate_portfolio(
        {s: t.slice(0, 7) for s, t in inputs.items()},
        config,
        Candidate("rotation", 3),
        dates[4],
        dates[6],
    )
    assert full.equity.slice(0, 3).equals(short.equity)
    assert all(r["decision_date"] < r["date"] for r in full.trades.to_pylist())
    assert full.orders.filter(
        pa.array([d <= dates[6] for d in full.orders["decision_date"].to_pylist()])
    ).equals(short.orders)
    with pytest.raises(ValueError, match="identical sessions"):
        simulate_portfolio(
            {**inputs, "XLF": inputs["XLF"].slice(1)},
            config,
            Candidate("buy_hold"),
            dates[4],
            dates[-1],
        )
    with pytest.raises(ValueError, match="warmup"):
        simulate_portfolio(inputs, config, Candidate("buy_hold"), dates[3], dates[-1])


def test_identical_exposures_are_screened_and_signals_can_choose_cash() -> None:
    config = study_config()
    increasing = [D(v) for v in [100, 101, 104, 108]]
    target, checks = target_weights(
        Candidate("trend", 3), {"SPY": increasing, "XLF": increasing}, config
    )
    assert target == {"SPY": D(".4")}
    assert checks[0]["accepted"] is False
    assert (
        target_weights(
            Candidate("rotation", 3),
            {"SPY": list(reversed(increasing)), "XLF": list(reversed(increasing))},
            config,
        )[0]
        == {}
    )
    assert TrendSignal().rank({"SPY": increasing}, 3) == ["SPY"]
    assert RotationSignal().rank({"XLF": increasing, "SPY": increasing}, 3) == ["SPY", "XLF"]


def test_partial_sales_topups_and_split_preserve_cost_and_entitlement() -> None:
    config = study_config().paper("SPY")
    config = replace(config, allocation=D(1), commission=D(0), slippage_bps=D(0))
    account = Account(cash=D(5000), pending=Order(date(2024, 1, 2), "buy", 10, "test"))
    account.execute(date(2024, 1, 3), D(100), config)
    account.pending = Order(date(2024, 1, 3), "buy", 10, "test")
    account.execute(date(2024, 1, 4), D(200), config)
    assert account.entry == 150
    account.pending = Order(date(2024, 1, 4), "sell", 5, "test")
    account.corporate_actions(
        {
            "date": date(2024, 1, 5),
            "split_ratio": 2,
            "dividend": D(1),
            "dividend_pay_date": date(2024, 1, 8),
        }
    )
    account.execute(date(2024, 1, 5), D(100), config)
    assert account.shares == 30 and account.entry == 75
    assert account.receivables == [(date(2024, 1, 8), D(40))]
    assert account.cash == 3000


def test_dividend_receivable_and_split_valuation_independently_reconcile() -> None:
    config = replace(study_config(), commission=D(0), slippage_bps=D(0))
    sessions = regular_sessions(date(2024, 1, 2), date(2024, 2, 1))["date"].to_pylist()
    inputs = {
        "SPY": bars(
            "SPY",
            [100] * 5 + [49] * 4,
            updates={5: {"split_ratio": 2, "dividend": D(1), "dividend_pay_date": sessions[8]}},
        ),
        "XLF": bars("XLF", [100] * 9),
    }
    result = simulate_portfolio(inputs, config, Candidate("buy_hold"), sessions[4], sessions[8])
    assert result.equity["equity"].to_pylist() == [D(5000)] * 5
    assert result.equity["receivables"].to_pylist() == [D(0), D(40), D(40), D(40), D(0)]
    audit, attribution, _ = audit_portfolio(inputs, result, config)
    assert set(audit["status"].to_pylist()) == {"pass"}
    assert sum(r["total_pnl"] for r in attribution.to_pylist() if r["date"] == sessions[8]) == 0
    nav = result.equity.to_pylist()
    nav[-1]["cash"] += 1
    corrupt = replace(result, equity=pa.Table.from_pylist(nav, schema=result.equity.schema))
    assert "error" in audit_portfolio(inputs, corrupt, config)[0]["status"].to_pylist()


def test_rotation_sells_before_reallocating_shared_cash() -> None:
    config = replace(
        study_config(), rotation_count=1, rebalance_sessions=1, commission=D(0), slippage_bps=D(0)
    )
    inputs = {
        "SPY": bars("SPY", [100, 105, 110, 115, 120, 100, 90, 80]),
        "XLF": bars("XLF", [100, 99, 98, 97, 96, 105, 115, 120]),
    }
    dates = inputs["SPY"]["date"].to_pylist()
    result = simulate_portfolio(inputs, config, Candidate("rotation", 3), dates[4], dates[-1])
    same_day = [r for r in result.trades.to_pylist() if r["date"] == dates[6]]
    assert [(r["symbol"], r["side"]) for r in same_day] == [("SPY", "sell"), ("XLF", "buy")]
    audit, attribution, closed = audit_portfolio(inputs, result, config)
    assert set(audit["status"].to_pylist()) == {"pass"}
    assert closed.num_rows > 0
    assert (
        sum(r["total_pnl"] for r in attribution.to_pylist() if r["date"] == dates[-1])
        == result.equity["equity"][-1].as_py() - 5000
    )


def test_risk_halt_latches_and_open_losses_are_included_in_metrics() -> None:
    config = replace(study_config(), account_drawdown=D(".05"), rebalance_sessions=1)
    inputs = {
        "SPY": bars("SPY", [90, 95, 100, 105, 110, 50, 40, 150, 160]),
        "XLF": bars("XLF", [100, 99, 98, 97, 96, 95, 94, 93, 92]),
    }
    dates = inputs["SPY"]["date"].to_pylist()
    result = simulate_portfolio(inputs, config, Candidate("trend", 3), dates[4], dates[-1])
    assert result.equity["status"][-1].as_py() in {"halted", "warning"}
    after = [r for r in result.trades.to_pylist() if r["date"] >= dates[6]]
    assert after and all(r["side"] == "sell" for r in after)
    _, _, closed = audit_portfolio(inputs, result, config)
    metrics = evaluate(result, config.initial_cash, closed).to_pylist()[0]
    assert metrics["total_return"] < 0 and metrics["max_drawdown"] < -0.05
    assert metrics["unrecovered_at_end"]
    assert metrics["max_underwater_sessions"] > 0


def test_strategy_buy_caps_and_gap_stress_and_open_profit() -> None:
    config = study_config()
    inputs = {
        "SPY": bars("SPY", [90, 91, 94, 95, 96, 98, 100]),
        "XLF": bars("XLF", [90, 94, 91, 95, 92, 96, 94]),
    }
    dates = inputs["SPY"]["date"].to_pylist()
    result = simulate_portfolio(
        inputs, config, Candidate("trend", 3), dates[4], dates[-1], cost_multiplier=2, gap_bps=500
    )
    assert max(result.positions["weight"].to_pylist()) < 0.41
    audit, attribution, closed = audit_portfolio(
        inputs, result, config, cost_multiplier=2, gap_bps=500
    )
    assert set(audit["status"].to_pylist()) == {"pass"}
    final = [r for r in attribution.to_pylist() if r["date"] == dates[-1]]
    assert any(r["unrealized_pnl"] != 0 for r in final)
    assert (
        evaluate(result, config.initial_cash, closed)["commissions"][0].as_py()
        == result.trades.num_rows * 2
    )


def test_split_and_dividend_alone_do_not_create_momentum() -> None:
    config = study_config()
    dates = regular_sessions(date(2024, 1, 2), date(2024, 2, 1))["date"].to_pylist()
    inputs = {
        "SPY": bars(
            "SPY",
            [100] * 4 + [45] * 5,
            updates={4: {"split_ratio": 2, "dividend": D(5), "dividend_pay_date": dates[8]}},
        ),
        "XLF": bars("XLF", [100] * 9),
    }
    for kind in ["trend", "rotation"]:
        result = simulate_portfolio(inputs, config, Candidate(kind, 3), dates[4], dates[8])
        assert result.trades.num_rows == 0
        assert result.equity["equity"].to_pylist() == [D(5000)] * 5
