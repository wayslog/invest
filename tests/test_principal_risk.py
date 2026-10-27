"""本金阶梯风控、W-8BEN 分红预扣与本金路径指标。"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pytest

from invest.backtest import BacktestResult, simulate_signals
from invest.cash_sweep import cash_sweep_plan
from invest.contracts import (
    AccountSnapshot,
    Holding,
    PendingOrder,
    PositionState,
    Quote,
    SignalFrame,
    StrategyState,
)
from invest.evaluation import principal_summary
from invest.portfolio_audit import audit_backtest
from invest.risk import principal_status
from invest.strategies import Policy
from invest.weekly_selection import WeeklySelection
from invest.withholding import CHINA_TREATY_DIVIDEND_RATE, withhold_dividends
from tests.test_backtest import policy
from tests.test_cash_sweep import contexts
from tests.test_decisions import signals
from tests.test_portfolio import bars

D = Decimal
DAY = date(2024, 1, 3)


def ladder(**changes: object) -> Policy:
    return policy(
        allocation=D(".75"),
        position_cap=D(".25"),
        account_risk="principal_ladder",
        **changes,
    )


@pytest.mark.parametrize(
    ("previous", "equity", "expected"),
    [
        ("active", D(5000), "active"),
        ("active", D("4999.99"), "warning"),
        ("warning", D(5000), "active"),
        ("warning", D("2500.01"), "warning"),
        ("active", D(2500), "terminated"),
        ("warning", D(1), "terminated"),
        ("terminated", D(9000), "terminated"),
    ],
)
def test_principal_ladder_thresholds(previous: str, equity: Decimal, expected: str) -> None:
    assert principal_status(previous, equity, D(5000)) == expected


def test_principal_ladder_rejects_peak_drawdown_state_and_keeps_legacy_identity() -> None:
    with pytest.raises(ValueError, match="peak-drawdown"):
        principal_status("halted", D(6000), D(5000))
    with pytest.raises(ValueError, match="account risk"):
        Policy(account_risk="trailing")
    # 默认规则不进入身份：已冻结结果的 policy_id 与动作身份不变。
    assert Policy().policy_id == (
        "3dea210f2cc7f09d20201072d9b54a4af8d3c280d1fc64d7f9d919ae005ec4c3"
    )
    assert Policy(account_risk="principal_ladder").policy_id != Policy().policy_id
    legacy = Policy()
    assert replace(legacy, account_risk="peak_drawdown").policy_id == legacy.policy_id


def account(cash: Decimal, holdings: dict[str, int], **changes: object) -> AccountSnapshot:
    return AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        cash,
        (Quote("ALPHA", D(100)), Quote("BETA", D(100)), Quote("QQQ", D(100))),
        holdings=tuple(Holding(key, shares, D(100)) for key, shares in holdings.items()),
        **changes,  # type: ignore[arg-type]
    )


def state(holdings: dict[str, int], status: str = "active") -> StrategyState:
    return StrategyState(
        D(1000),
        risk_status=status,
        positions=tuple(PositionState(key, DAY, D(100)) for key in holdings),
    )


def selection() -> WeeklySelection:
    return WeeklySelection(
        ("ALPHA", "BETA"),
        "hold_until_exit",
        signals(DAY).table["available_at"][0].as_py(),
        "warning",
        True,
    )


def test_warning_keeps_stocks_and_qqq_and_sweeps_cash_without_new_stock_risk() -> None:
    # 净值 850 低于本金 1000；ALPHA 目标为 2 股，警戒期间不从 1 股加仓。
    holdings = {"ALPHA": 1, "QQQ": 5}
    plan = cash_sweep_plan(
        signals(DAY), account(D(250), holdings), state(holdings), ladder(), selection()
    )
    rows = {row["instrument"]: row for row in plan.actions.to_pylist()}
    assert plan.state.risk_status == "warning"
    assert (rows["ALPHA"]["action"], rows["ALPHA"]["target_quantity"]) == ("HOLD", 1)
    assert rows["ALPHA"]["reason"] == "principal_warning"
    assert (rows["BETA"]["action"], rows["BETA"]["reason"]) == ("WAIT", "warning")
    assert (rows["QQQ"]["action"], rows["QQQ"]["quantity"]) == ("ADD", 2)
    assert rows["QQQ"]["reason"] == "cash_sweep_invest"

    # 同样的账户在原规则下仍为正常状态：差异来自本金阶梯，而不是净值本身。
    legacy = cash_sweep_plan(
        signals(DAY),
        account(D(250), holdings),
        state(holdings),
        replace(ladder(), account_risk="peak_drawdown"),
        selection(),
    )
    assert legacy.state.risk_status == "active"


def test_warning_cancels_pending_stock_buys_but_keeps_pending_exits() -> None:
    holdings = {"ALPHA": 2, "QQQ": 5}
    pending = (PendingOrder("BETA", "buy", 1, D(100)), PendingOrder("ALPHA", "sell", 1, D(100)))
    plan = cash_sweep_plan(
        signals(DAY),
        account(D(150), holdings, pending=pending),
        state(holdings),
        ladder(),
        selection(),
    )
    rows = {row["instrument"]: row for row in plan.actions.to_pylist()}
    assert plan.state.risk_status == "warning"
    assert rows["BETA"]["cancel_pending"] and not rows["ALPHA"]["cancel_pending"]


def test_hard_line_liquidates_everything_and_never_restarts() -> None:
    holdings = {"ALPHA": 1, "QQQ": 3}
    plan = cash_sweep_plan(
        signals(DAY), account(D(100), holdings), state(holdings), ladder(), selection()
    )
    rows = {row["instrument"]: row for row in plan.actions.to_pylist()}
    assert plan.state.risk_status == "terminated"
    assert {key: (rows[key]["action"], rows[key]["reason"]) for key in holdings} == {
        "ALPHA": ("SELL", "terminated"),
        "QQQ": ("SELL", "terminated"),
    }
    recovered = cash_sweep_plan(
        signals(DAY), account(D(2000), {}), state({}, "terminated"), ladder(), selection()
    )
    assert recovered.state.risk_status == "terminated"
    assert all(row["action"] not in {"BUY", "ADD"} for row in recovered.actions.to_pylist())


def run(qqq: list[int], first_stock_index: int) -> tuple[list[dict[str, Any]], BacktestResult]:
    inputs = {"ALPHA": bars("ALPHA", [100] * len(qqq)), "QQQ": bars("QQQ", qqq)}
    days = inputs["ALPHA"]["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = ladder(sale_proceeds="next_session")
    result = simulate_signals(
        inputs,
        frame,
        settings,
        days[1],
        days[-1],
        initial_cash=D(1000),
        selections=contexts(days, first_stock_index),
        cash_sweep="QQQ",
    )
    checks = audit_backtest(inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ")[0]
    assert set(checks["status"].to_pylist()) == {"pass"}
    return result.portfolio.trades.to_pylist(), result


def test_below_principal_blocks_stock_entries_until_equity_recovers() -> None:
    qqq = [100, 100, 80, 80, 80, 80, 120, 120, 120, 120]
    fills, result = run(qqq, first_stock_index=2)
    days = bars("QQQ", qqq)["date"].to_pylist()
    stock_buys = [f["date"] for f in fills if f["symbol"] == "ALPHA" and f["side"] == "buy"]
    qqq_sales = [f["date"] for f in fills if f["symbol"] == "QQQ" and f["side"] == "sell"]
    # 第 2 至 5 个收盘净值低于本金：不买个股、不卖 QQQ；第 6 个收盘恢复后才腾挪资金入场。
    assert stock_buys and min(stock_buys) > days[6]
    assert qqq_sales and min(qqq_sales) == days[7]
    assert result.final_state.risk_status == "active"


def test_hard_line_breach_in_backtest_liquidates_and_stays_out() -> None:
    qqq = [100, 100, 40, 40, 100, 100, 100]
    fills, result = run(qqq, first_stock_index=4)
    days = bars("QQQ", qqq)["date"].to_pylist()
    assert [(f["date"], f["symbol"], f["side"]) for f in fills] == [
        (days[1], "QQQ", "buy"),
        (days[3], "QQQ", "sell"),
    ]
    assert result.final_state.risk_status == "terminated"
    summary = principal_summary(result.portfolio.equity, D(1000)).to_pylist()[0]
    assert summary["hard_line_breached_on"] == days[2]
    assert summary["min_equity_ratio"] < 0.5


def dividend_bars() -> pa.Table:
    days = bars("QQQ", [100] * 6)["date"].to_pylist()
    return bars(
        "QQQ",
        [100] * 6,
        updates={2: {"dividend": D("0.574321"), "dividend_pay_date": days[4]}},
    )


def test_withholding_nets_dividends_and_keeps_original_table() -> None:
    gross = dividend_bars()
    net = withhold_dividends(gross, "QQQ", CHINA_TREATY_DIVIDEND_RATE)
    assert gross["dividend"][2].as_py() == D("0.574321")
    assert net["dividend"][2].as_py() == D("0.516888")
    assert net["dividend_pay_date"][2].as_py() == gross["dividend_pay_date"][2].as_py()
    assert net.drop(["dividend"]).equals(gross.drop(["dividend"]))
    metadata = net.schema.metadata or {}
    assert metadata[b"dividend_withholding_rate"] == b"0.1"
    assert metadata[b"source"] == b"synthetic"
    with pytest.raises(ValueError, match="already net"):
        withhold_dividends(net, "QQQ", CHINA_TREATY_DIVIDEND_RATE)
    for rate in (D(1), D("-0.1"), D("NaN")):
        with pytest.raises(ValueError, match="withholding rate"):
            withhold_dividends(gross, "QQQ", rate)
    tiny = bars(
        "QQQ",
        [100] * 6,
        updates={2: {"dividend": D("0.000001"), "dividend_pay_date": net["date"][3].as_py()}},
    )
    assert withhold_dividends(tiny, "QQQ", D(".3"))["dividend_pay_date"][2].as_py() is None


def test_withheld_dividend_cash_reconciles_in_backtest_and_audit() -> None:
    gross, alpha = dividend_bars(), bars("ALPHA", [100] * 6)
    days = gross["date"].to_pylist()
    frame = SignalFrame(pa.concat_tables([signals(day).table for day in days]))
    settings = ladder(commission=D(0))
    finals = {}
    for label, table in (
        ("gross", gross),
        ("net", withhold_dividends(gross, "QQQ", CHINA_TREATY_DIVIDEND_RATE)),
    ):
        inputs = {"ALPHA": alpha, "QQQ": table}
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
        checks = audit_backtest(inputs, result.portfolio, settings, D(1000), cash_sweep="QQQ")[0]
        assert set(checks["status"].to_pylist()) == {"pass"}
        finals[label] = result.portfolio.equity["equity"].to_pylist()[-1]
    # 持有 10 股 QQQ：每股税前 0.574321 USD，预扣 10% 后少入账 10 × 0.057433 USD。
    assert finals["gross"] - finals["net"] == D("0.57433")


def test_principal_summary_reports_path_relative_to_principal() -> None:
    days = bars("QQQ", [100] * 5)["date"].to_pylist()
    equity = pa.table(
        {
            "date": days,
            "equity": pa.array(
                [D(5000), D(4800), D(2600), D(5200), D(4900)], type=pa.decimal128(24, 6)
            ),
        }
    )
    row = principal_summary(equity, D(5000)).to_pylist()[0]
    assert row["min_equity"] == D(2600) and row["min_equity_date"] == days[2]
    assert row["min_equity_ratio"] == pytest.approx(0.52)
    assert row["sessions_below_principal"] == 3 and row["share_below_principal"] == 0.6
    assert row["first_below_principal"] == days[1]
    assert row["hard_line_breached_on"] is None and row["final_equity_ratio"] == 0.98
    with pytest.raises(ValueError, match="positive principal"):
        principal_summary(equity, D(0))
