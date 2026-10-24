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
