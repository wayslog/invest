"""统一决策接口：整股预算、风险优先级、状态与时点。"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pyarrow as pa
import pytest

from invest.contracts import SIGNAL_SCHEMA, SignalFrame
from invest.quality import regular_sessions

D = Decimal
DAY = date(2024, 1, 3)


def signals(day: date = DAY) -> SignalFrame:
    sessions = regular_sessions(day, day + timedelta(days=14)).to_pylist()
    return SignalFrame(
        pa.Table.from_pylist(
            [
                {
                    "date": day,
                    "instrument": instrument,
                    "score": score,
                    "rank": rank,
                    "direction": 1,
                    "horizon": 3,
                    "available_at": sessions[0]["close_at"],
                    "expires_at": sessions[1]["close_at"],
                    "pool_id": "frozen_pool",
                }
                for instrument, score, rank in (("ALPHA", 1.0, 1), ("BETA", 0.5, 2))
            ],
            schema=SIGNAL_SCHEMA.with_metadata(
                {
                    **(SIGNAL_SCHEMA.metadata or {}),
                    b"snapshot_id": b"snapshot",
                    b"source": b"synthetic",
                    b"price_basis": b"raw",
                    b"scope": b"synthetic",
                    b"pool_id": b"frozen_pool",
                }
            ),
        )
    )


def test_decision_allocates_shared_cash_in_rank_order_without_mutating_inputs() -> None:
    from invest.contracts import AccountSnapshot, Quote, StrategyState
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        account_id="research_account",
        snapshot_id="snapshot",
        source="synthetic",
        as_of=DAY,
        initial_cash=D(1000),
        cash=D(1000),
        quotes=(Quote("ALPHA", D(100)), Quote("BETA", D(100))),
    )
    state = StrategyState(peak_equity=D(1000))
    policy = Policy(
        top_k=2, allocation=D(1), position_cap=D("0.5"), commission=D(1), slippage_bps=D(0)
    )
    plan = decide(signals(), account, state, policy)
    actions = plan.actions.to_pylist()
    assert [(r["instrument"], r["action"], r["quantity"]) for r in actions] == [
        ("ALPHA", "BUY", 5),
        ("BETA", "BUY", 4),
    ]
    assert all(r["effective_at"].date() == date(2024, 1, 4) for r in actions)
    assert account.cash == 1000 and account.holdings == () and state.last_session is None
    assert plan.state.last_session == DAY
    assert decide(signals(), account, state, policy).actions.equals(
        plan.actions, check_metadata=True
    )


@pytest.mark.parametrize(
    ("price", "peak", "holding_limit", "reason"),
    [
        (85, 100, 20, "stop_loss"),
        (125, 125, 20, "take_profit"),
        (110, 130, 20, "trailing_stop"),
        (105, 105, 2, "holding_limit"),
    ],
)
def test_position_exits_override_rank_and_sell_before_reinvestment(
    price: int, peak: int, holding_limit: int, reason: str
) -> None:
    from invest.contracts import AccountSnapshot, Holding, PositionState, Quote, StrategyState
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(price)), Quote("BETA", D(100))),
        holdings=(Holding("ALPHA", 5, D(100)),),
    )
    state = StrategyState(D(1000), positions=(PositionState("ALPHA", date(2024, 1, 2), D(peak)),))
    policy = Policy(
        top_k=1,
        allocation=D(1),
        position_cap=D(1),
        commission=D(0),
        slippage_bps=D(0),
        stop_loss=D(".1"),
        trailing_stop=D(".1"),
        take_profit=D(".2"),
        max_holding_sessions=holding_limit,
        account_drawdown=D(1),
    )
    plan = decide(signals(), account, state, policy)
    actions = plan.actions.to_pylist()
    assert [(r["instrument"], r["action"]) for r in actions] == [("ALPHA", "SELL"), ("BETA", "BUY")]
    assert actions[0]["reason"] == reason and actions[0]["quantity"] == 5
    assert account.holdings[0].shares == 5 and state.positions[0].peak == peak


def test_pending_orders_consume_exposure_and_pauses_preserve_schedule() -> None:
    from invest.contracts import AccountSnapshot, PendingOrder, Quote, StrategyState
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(1000),
        (Quote("ALPHA", D(100)), Quote("BETA", D(100))),
        pending=(PendingOrder("ALPHA", "buy", 5, D(100)),),
    )
    state = StrategyState(D(1000))
    settings = Policy(
        top_k=2, allocation=D(".6"), position_cap=D(".5"), commission=D(0), slippage_bps=D(0)
    )
    plan = decide(signals(), account, state, settings)
    rows = {row["instrument"]: row for row in plan.actions.to_pylist()}
    assert rows["ALPHA"]["action"] == "WAIT"
    assert rows["BETA"]["quantity"] == 1
    paused = decide(signals(), replace(account, operations="paused"), state, settings)
    assert all(row["quantity"] == 0 for row in paused.actions.to_pylist())
    assert paused.state.last_rebalance is None
    assert paused.actions.to_pylist()[0]["cancel_pending"]


def test_invalid_cutoffs_and_stale_held_prices_block_new_risk() -> None:
    from invest.contracts import AccountSnapshot, Holding, PositionState, Quote, StrategyState
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(100), available=False), Quote("BETA", D(100))),
        holdings=(Holding("ALPHA", 5, D(100)),),
    )
    state = StrategyState(D(1000), positions=(PositionState("ALPHA", DAY, D(100)),))
    plan = decide(signals(), account, state, Policy())
    assert all(row["quantity"] == 0 for row in plan.actions.to_pylist())
    assert plan.state.peak_equity == state.peak_equity
    with pytest.raises(ValueError, match="future"):
        decide(signals(), account, replace(state, last_rebalance=date(2024, 1, 4)), Policy())


def test_signal_failure_exits_between_rebalances_and_pending_exit_remains_visible() -> None:
    from invest.contracts import (
        AccountSnapshot,
        Holding,
        PendingOrder,
        PositionState,
        Quote,
        StrategyState,
    )
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(100)), Quote("BETA", D(100))),
        holdings=(Holding("ALPHA", 5, D(100)),),
    )
    state = StrategyState(
        D(1000),
        last_rebalance=date(2024, 1, 2),
        positions=(PositionState("ALPHA", date(2024, 1, 2), D(100)),),
    )
    settings = Policy(rebalance_sessions=10, position_cap=D(".8"))
    rows = signals().table.to_pylist()
    rows[0].update(score=-1.0, direction=0)
    history = SignalFrame(pa.Table.from_pylist(rows, schema=signals().table.schema))
    plan = decide(history, account, state, settings)
    assert plan.actions.to_pylist()[0]["action"] == "SELL"
    assert plan.actions.to_pylist()[0]["exit_reason"] == "signal_exit"
    pending = replace(account, pending=(PendingOrder("ALPHA", "buy", 1, D(100)),))
    waiting = decide(history, pending, state, settings)
    action = next(row for row in waiting.actions.to_pylist() if row["instrument"] == "ALPHA")
    assert action["action"] == "WAIT" and action["cancel_pending"]
    assert action["exit_reason"] == "signal_exit"
    assert waiting.state.positions[0].exit_reason == "signal_exit"


def test_decimal_roundtrip_preserves_action_identity_and_rejects_subunit_quotes() -> None:
    from invest.contracts import AccountSnapshot, Quote, StrategyState
    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(1000),
        (Quote("ALPHA", D(100)), Quote("BETA", D(100))),
    )
    state = StrategyState(D(1000))
    settings = Policy(
        top_k=2, allocation=D(1), position_cap=D(".5"), commission=D(1), slippage_bps=D(0)
    )
    restored_account, restored_state = read_decision_contexts(
        decision_contexts(((account, state),))
    )[0]
    canonical = replace(settings, commission=D("1.000000"), allocation=D("1.000000"))
    assert settings == canonical and settings.policy_id == canonical.policy_id
    assert decide(signals(), account, state, settings).actions.equals(
        decide(signals(), restored_account, restored_state, canonical).actions
    )
    with pytest.raises(ValueError, match="precision"):
        replace(account, quotes=(Quote("ALPHA", D("100.0000001")),))


@pytest.mark.parametrize("scheduled", [False, True])
def test_unavailable_holdings_do_not_drive_portfolio_adjustments(scheduled: bool) -> None:
    from invest.contracts import AccountSnapshot, Holding, PositionState, Quote, StrategyState
    from invest.strategies import decide
    from tests.test_backtest import policy

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(500),
        D(0),
        (Quote("ALPHA", D(20), available=False), Quote("BETA", D(100))),
        (Holding("ALPHA", 5, D(100)), Holding("BETA", 5, D(100))),
    )
    state = StrategyState(
        D(1000),
        last_rebalance=None if scheduled else date(2024, 1, 2),
        positions=tuple(
            PositionState(name, date(2024, 1, 2), D(100)) for name in ("ALPHA", "BETA")
        ),
    )
    settings = policy(position_cap=D(".5"), rebalance_sessions=100, commission=D(0))
    plans = [
        decide(
            signals(),
            replace(account, quotes=(Quote("ALPHA", price, available=False), account.quotes[1])),
            state,
            settings,
        )
        for price in (D(20), D(100))
    ]
    assert plans[0].actions.equals(plans[1].actions)
    assert all(
        row["quantity"] == 0 and row["target_weight"] is None
        for row in plans[0].actions.to_pylist()
    )
    assert plans[0].state.peak_equity == state.peak_equity
    assert plans[0].state.last_rebalance == state.last_rebalance
    # 不依赖组合估值的已确认止损仍然退出，不能因另一持仓缺价而被抑制。
    stopped = replace(account, quotes=(account.quotes[0], Quote("BETA", D(80))))
    actions = decide(
        signals(), stopped, state, replace(settings, stop_loss=D(".1"))
    ).actions.to_pylist()
    beta = next(row for row in actions if row["instrument"] == "BETA")
    assert beta["action"] == "SELL" and beta["quantity"] == 5
    assert beta["exit_reason"] == "stop_loss" and beta["target_weight"] is None


@pytest.mark.parametrize(
    "condition",
    [
        "unpriced_holding",
        "universe_exit",
        "price_unavailable",
        "signal_missing",
        "signal_exit",
        "cooldown",
        "eligible",
    ],
)
def test_pending_buy_orders_recheck_entry_admission(condition: str) -> None:
    from invest.contracts import (
        AccountSnapshot,
        Holding,
        PendingOrder,
        PositionState,
        Quote,
        StrategyState,
    )
    from invest.strategies import decide
    from tests.test_backtest import policy

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(100)), Quote("BETA", D(100))),
        (Holding("ALPHA", 5, D(100)),),
        (PendingOrder("BETA", "buy", 2, D(100)),),
    )
    state = StrategyState(D(1000), positions=(PositionState("ALPHA", DAY, D(100)),))
    frame = signals()
    if condition == "unpriced_holding":
        account = replace(
            account, quotes=(replace(account.quotes[0], available=False), account.quotes[1])
        )
    elif condition in {"universe_exit", "price_unavailable"}:
        account = replace(
            account,
            quotes=(
                account.quotes[0],
                replace(
                    account.quotes[1],
                    active=condition != "universe_exit",
                    available=condition != "price_unavailable",
                ),
            ),
        )
    elif condition == "signal_missing":
        frame = SignalFrame(frame.table.slice(0, 1))
    elif condition == "signal_exit":
        rows = frame.table.to_pylist()
        rows[1].update(score=0.0, direction=0)
        frame = SignalFrame(pa.Table.from_pylist(rows, schema=frame.table.schema))
    elif condition == "cooldown":
        state = replace(state, last_exits=(("BETA", date(2024, 1, 2)),))
    actions = decide(frame, account, state, policy(top_k=2)).actions.to_pylist()
    beta = next(row for row in actions if row["instrument"] == "BETA")
    assert beta["action"] == "WAIT" and beta["quantity"] == 0
    assert beta["cancel_pending"] is (condition != "eligible")
    assert account.pending[0].quantity == 2


def test_risk_action_identity_changes_with_cancellation_and_exit_requirements() -> None:
    from invest.contracts import (
        AccountSnapshot,
        Holding,
        PendingOrder,
        PositionState,
        Quote,
        StrategyState,
    )
    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.strategies import decide
    from tests.test_backtest import policy

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(500),
        (Quote("ALPHA", D(100)),),
        (Holding("ALPHA", 5, D(100)),),
        (PendingOrder("ALPHA", "buy", 1, D(100)),),
    )
    state = StrategyState(D(1000), positions=(PositionState("ALPHA", DAY, D(100)),))
    active = decide(signals(), account, state, policy()).actions.to_pylist()[0]
    halted_state = replace(state, risk_status="halted")
    halted = decide(signals(), account, halted_state, policy()).actions.to_pylist()[0]
    assert active["action"] == halted["action"] == "WAIT"
    assert not active["cancel_pending"] and halted["cancel_pending"]
    assert active["exit_reason"] == "" and halted["exit_reason"] == "halted"
    assert active["action_id"] != halted["action_id"]
    restored = read_decision_contexts(decision_contexts(((account, halted_state),)))[0]
    assert decide(signals(), *restored, policy()).actions.to_pylist()[0] == halted


def test_pending_cancellation_keeps_exposure_reserved_until_confirmation() -> None:
    from invest.contracts import AccountSnapshot, PendingOrder, Quote, StrategyState
    from invest.strategies import Policy, decide

    account = AccountSnapshot(
        "account",
        "snapshot",
        "synthetic",
        DAY,
        D(1000),
        D(1000),
        (Quote("ALPHA", D(20), available=False), Quote("BETA", D(100))),
        pending=(PendingOrder("ALPHA", "buy", 5, D(100)),),
    )
    settings = Policy(
        top_k=2, allocation=D(".6"), position_cap=D(".5"), commission=D(0), slippage_bps=D(0)
    )
    plan = decide(signals(), account, StrategyState(D(1000)), settings)
    rows = {row["instrument"]: row for row in plan.actions.to_pylist()}
    assert rows["ALPHA"]["cancel_pending"] and rows["ALPHA"]["reference_price"] is None
    assert rows["BETA"]["quantity"] == 1
