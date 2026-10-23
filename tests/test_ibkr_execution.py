"""Restart safety and confirmed-fill accounting independent of any broker service."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from invest import ibkr_execution as ex
from invest.ibkr_models import IBKRConfig, Intent, create_intent, number, timestamp
from invest.ibkr_store import EventStore
from invest.ibkr_synthetic import SyntheticBroker, run_demo

D = Decimal


def prepared(
    tmp_path: Path, *, quantity: int = 2, cash: str = "5000"
) -> tuple[EventStore, SyntheticBroker, Intent]:
    store, broker = EventStore(tmp_path / "journal"), SyntheticBroker(D(cash))
    ex.initialize(store, broker, IBKRConfig(), at=broker.now)
    intent = create_intent(
        "buy",
        broker.account,
        broker.client_id,
        1,
        "SPY",
        "BUY",
        quantity,
        D("100"),
        date(2024, 1, 2),
        broker.now,
    )
    ex.add_intent(store, intent, at=broker.now)
    return store, broker, intent


def dispatch(store: EventStore, broker: SyntheticBroker, intent: Intent) -> ex.Projection:
    broker.now = intent.valid_from
    return ex.submit(store, broker, intent.intent_id, at=broker.now)


def test_confirmed_fills_and_fees_replay_once_and_export_typed_deltas(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    assert dispatch(store, broker, intent).orders["buy"].status == "ACKNOWLEDGED"
    broker.fill(1, 2, D("99"), "FILL.01", D("0.4"))
    broker.executions.append(deepcopy(broker.executions[0]))
    state = ex.reconcile(store, broker, at=broker.now)
    assert not state.issues and state.orders["buy"].status == "FILLED"
    assert state.cash_delta == D("-198.4") and state.positions == {1: D(2)}
    ex.submit(EventStore(store.directory), broker, "buy", at=broker.now)
    assert broker.submissions == 1
    assert sum(e["kind"] == "execution" for e in store.read()) == 1
    result = ex.export_report(store, tmp_path / "report")
    assert result["reconciled"] and not result["capital_account_modified"]
    assert pq.read_table(tmp_path / "report/cash.parquet").to_pylist()[0]["expected"] == D("4801.6")
    assert pq.read_table(tmp_path / "report/fills.parquet").to_pylist()[0]["price"] == D("99")
    assert (
        pq.ParquetFile(tmp_path / "report/fills.parquet")
        .metadata.row_group(0)
        .column(0)
        .compression
        == "ZSTD"
    )
    with pytest.raises(ValueError, match="immutable"):
        ex.export_report(store, tmp_path / "report")


@pytest.mark.parametrize("accepted", [True, False])
def test_lost_submit_ack_never_causes_a_second_order(tmp_path: Path, accepted: bool) -> None:
    store, broker, intent = prepared(tmp_path)
    broker.fail_after, broker.fail_before = accepted, not accepted
    state = dispatch(store, broker, intent)
    assert state.orders["buy"].status == "UNKNOWN"
    broker.visible = False
    state = ex.submit(EventStore(store.directory), broker, "buy", at=broker.now)
    assert broker.submissions == 1 and "order_status_unresolved" in state.issues
    broker.visible = True
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.orders["buy"].status == ("ACKNOWLEDGED" if accepted else "UNKNOWN")


def test_process_crash_after_durable_dispatch_is_query_only_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, broker, intent = prepared(tmp_path)

    def crash(intent: Intent, order_id: int) -> None:
        broker.submissions += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(broker, "submit", crash)
    with pytest.raises(KeyboardInterrupt):
        dispatch(store, broker, intent)
    assert any(e["kind"] == "dispatch" for e in store.read())
    state = ex.submit(EventStore(store.directory), broker, "buy", at=broker.now)
    assert state.orders["buy"].status == "UNKNOWN" and broker.submissions == 1


def test_partial_fill_late_fee_and_cancellation_keep_confirmed_position(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D("99.5"), "PART.01")
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.orders["buy"].status == "PARTIALLY_FILLED"
    assert "commission_pending_or_non_usd" in state.issues
    broker.fee("PART.01", D("0.5"))
    state = ex.cancel(store, broker, "buy", at=broker.now)
    assert state.orders["buy"].status == "CANCELED" and state.positions[1] == 1
    assert state.cash_delta == -100 and not state.issues
    ex.cancel(store, broker, "buy", at=broker.now)
    assert broker.cancellations == 1


def test_cancel_with_missing_execution_details_remains_unknown(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    broker.orders[0].update(status="Cancelled", filled=D(1), remaining=D(1))
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.orders["buy"].status == "UNKNOWN"
    assert "order_status_unresolved" in state.issues and not state.fills


def test_cancel_timeout_can_retry_only_after_positive_open_order_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    original = broker.cancel

    def timeout(intent: Intent, order_id: int) -> None:
        broker.cancellations += 1
        raise TimeoutError

    monkeypatch.setattr(broker, "cancel", timeout)
    assert ex.cancel(store, broker, "buy", at=broker.now).orders["buy"].status == "CANCEL_PENDING"
    broker.visible = False
    ex.cancel(store, broker, "buy", at=broker.now)
    assert broker.cancellations == 1
    broker.visible = True
    monkeypatch.setattr(broker, "cancel", original)
    state = ex.cancel(store, broker, "buy", at=broker.now)
    assert broker.cancellations == 2 and state.orders["buy"].status == "CANCELED"


def test_cancel_fill_race_and_stale_ack_cannot_regress_confirmed_fill(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path, quantity=1)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D(99), "RACE.01", D("0.5"))
    state = ex.cancel(store, broker, "buy", at=broker.now)
    assert state.orders["buy"].status == "FILLED" and broker.cancellations == 0
    broker.orders[0]["status"] = "Submitted"
    assert ex.reconcile(store, broker, at=broker.now).orders["buy"].status == "FILLED"


def test_explicit_reject_is_terminal_but_never_resubmitted(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    broker.orders[0].update(status="Inactive", rejected=True)
    assert ex.reconcile(store, broker, at=broker.now).orders["buy"].status == "REJECTED"
    ex.submit(store, broker, "buy", at=broker.now)
    assert broker.submissions == 1


def test_execution_correction_replaces_old_fill_without_double_accounting(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path, quantity=1)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D(99), "CORRECTION.01", D("0.4"))
    ex.reconcile(store, broker, at=broker.now)
    correction = {**broker.executions[0], "exec_id": "CORRECTION.02", "price": D(98)}
    broker.executions.append(correction)
    broker.commissions.append(
        {"exec_id": "CORRECTION.02", "currency": "USD", "commission": D("0.4")}
    )
    broker.cash += 1
    broker.settled = broker.cash
    state = ex.reconcile(store, broker, at=broker.now)
    assert list(state.fills) == ["CORRECTION.02"]
    assert state.cash_delta == D("-98.4") and state.positions[1] == 1 and not state.issues
    assert sum(e["kind"] == "execution" for e in store.read()) == 2


def test_commission_revision_can_return_to_an_earlier_value(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path, quantity=1)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D(99), "FEE.01", D("0.5"))
    ex.reconcile(store, broker, at=broker.now)
    for fee in (D("0.3"), D("0.5")):
        broker.fee("FEE.01", fee)
        state = ex.reconcile(store, broker, at=broker.now)
        assert state.cash_delta == -99 - fee and not state.issues
    assert sum(e["kind"] == "commission" for e in store.read()) == 3


@pytest.mark.parametrize(
    "field,value", [("perm_id", 999), ("con_id", 8), ("limit_price", D(200)), ("client_id", 99)]
)
def test_conflicting_broker_identity_or_economics_halts_new_risk(
    tmp_path: Path, field: str, value: Any
) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    broker.orders[0][field] = value
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.issues
    original = store.read()
    assert any(e["kind"] == "conflict" for e in original)


def test_changed_duplicate_exec_id_preserves_original_and_stops(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path, quantity=1)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D(99), "DUPLICATE.01", D("0.5"))
    ex.reconcile(store, broker, at=broker.now)
    broker.executions[0]["price"] = D(98)
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.issues and state.cash_delta == D("-99.5")
    assert D(state.fills["DUPLICATE.01"]["price"]) == 99


@pytest.mark.parametrize("change", ["cash", "position", "foreign_order", "foreign_execution"])
def test_external_account_activity_is_not_silently_attributed(tmp_path: Path, change: str) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    if change == "cash":
        broker.cash += 100
    elif change == "position":
        broker.positions[1] = D(1)
    elif change == "foreign_order":
        broker.orders.append({**broker.orders[0], "order_id": 9, "order_ref": "manual"})
    else:
        broker.executions.append(
            {
                "exec_id": "MANUAL.01",
                "account": broker.account,
                "client_id": 99,
                "order_id": 99,
                "order_ref": "manual",
            }
        )
    assert ex.reconcile(store, broker, at=broker.now).issues


def test_unsettled_cash_and_overbooked_sell_reservations_are_rejected(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    broker.settled = D(0)
    with pytest.raises(ValueError, match="settled cash"):
        dispatch(store, broker, intent)
    assert broker.submissions == 0
    broker.settled = broker.cash
    ex.submit(store, broker, "buy", at=broker.now)
    broker.fill(1, 2, D(99), "INVENTORY.01", D("0.5"))
    ex.reconcile(store, broker, at=broker.now)
    broker.now = datetime(2024, 1, 3, 22, tzinfo=UTC)
    sell = create_intent(
        "sell",
        broker.account,
        broker.client_id,
        1,
        "SPY",
        "SELL",
        2,
        D(100),
        date(2024, 1, 3),
        broker.now,
    )
    ex.add_intent(store, sell, at=broker.now)
    with pytest.raises(ValueError, match="overbook"):
        ex.add_intent(store, replace(sell, intent_id="sell-again"), at=broker.now)
    broker.now = sell.valid_from
    ex.submit(store, broker, "sell", at=broker.now)
    broker.fill(2, 2, D(101), "SELL.01", D("0.5"))
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.positions[1] == 0 and state.cash_delta == 3 and not state.issues


def test_limits_identity_and_real_clock_cannot_be_reset(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    original = store.read()[0]
    with pytest.raises(ValueError, match="reset"):
        ex.initialize(
            store, broker, replace(IBKRConfig(), max_order_notional=D(999)), at=broker.now
        )
    with pytest.raises(ValueError, match="different order economics"):
        ex.add_intent(store, replace(intent, limit_price=D(101)), at=broker.now)
    with pytest.raises(ValueError, match="per-order"):
        ex.add_intent(store, replace(intent, intent_id="large", quantity=11), at=broker.now)
    with pytest.raises(ValueError, match="before the next session"):
        ex.add_intent(
            store, replace(intent, intent_id="backfill"), at=broker.now + timedelta(minutes=1)
        )
    broker.source = "ibkr"
    with pytest.raises(ValueError, match="differs"):
        ex.reconcile(store, broker)
    with pytest.raises(ValueError, match="synthetic"):
        ex._now("ibkr", broker.now)
    assert store.read()[0] == original


@pytest.mark.parametrize(
    ("session", "at", "expected_open", "expected_close"),
    [
        (
            date(2024, 7, 3),
            datetime(2024, 7, 3, 18, tzinfo=UTC),
            "2024-07-05T13:30:00+00:00",
            "2024-07-05T20:00:00+00:00",
        ),
        (
            date(2024, 11, 27),
            datetime(2024, 11, 27, 22, tzinfo=UTC),
            "2024-11-29T14:30:00+00:00",
            "2024-11-29T18:00:00+00:00",
        ),
        (
            date(2024, 3, 8),
            datetime(2024, 3, 8, 22, tzinfo=UTC),
            "2024-03-11T13:30:00+00:00",
            "2024-03-11T20:00:00+00:00",
        ),
    ],
)
def test_intents_follow_next_session_holidays_half_days_and_dst(
    session: date, at: datetime, expected_open: str, expected_close: str
) -> None:
    intent = create_intent("calendar", "DU_SYNTHETIC", 72, 1, "SPY", "BUY", 1, D(100), session, at)
    assert intent.valid_from == timestamp(expected_open) and intent.valid_until == timestamp(
        expected_close
    )


def test_expired_unsent_intent_and_early_fill_cannot_be_backfilled(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path)
    broker.now = intent.valid_until
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.orders["buy"].status == "EXPIRED"
    with pytest.raises(ValueError, match="outside"):
        ex.submit(store, broker, "buy", at=broker.now)
    assert broker.submissions == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.7976931348623157e308, None])
def test_missing_sdk_numeric_values_are_not_zero(value: Any) -> None:
    assert number(value, optional=True) is None
    with pytest.raises(ValueError):
        number(value)


def test_store_duplicate_keys_partial_files_and_sequence_validation(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "journal")
    with store.locked():
        assert store.append("x", "same", {"cash": D("1.00")})
        assert not store.append("x", "same", {"cash": D(1)})
        with pytest.raises(ValueError, match="Conflicting duplicate"):
            store.append("x", "same", {"cash": D(2)})
    (store.directory / "events/.partial.tmp").write_bytes(b"unfinished")
    assert len(store.read()) == 1
    first = store.directory / "events/00000000.parquet"
    first.rename(first.with_name("00000002.parquet"))
    with pytest.raises(ValueError, match="noncontiguous"):
        store.read()


def test_synthetic_demo_is_explicit_and_restart_does_not_reset_cash(tmp_path: Path) -> None:
    result = run_demo(tmp_path / "demo")
    assert result["source"] == "synthetic" and result["reconciled"]
    assert (
        result["execution_cash_delta_usd"] == "-100.0"
        or D(result["execution_cash_delta_usd"]) == -100
    )
    baseline = (tmp_path / "demo/journal/events/00000000.parquet").read_bytes()
    again = run_demo(tmp_path / "demo")
    assert again["reconciled"]
    assert (tmp_path / "demo/journal/events/00000000.parquet").read_bytes() == baseline


def test_changed_execution_engine_stops_new_risk_but_allows_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, broker, intent = prepared(tmp_path)
    dispatch(store, broker, intent)
    original = store.read()[0]
    monkeypatch.setattr(ex, "engine_digest", lambda: "changed")
    assert "execution_engine_changed" in ex.project(store).issues
    state = ex.cancel(store, broker, "buy", at=broker.now)
    assert state.orders["buy"].status == "CANCELED" and broker.cancellations == 1
    assert store.read()[0] == original


def test_pro_rata_cost_reporting_does_not_round_actual_cash(tmp_path: Path) -> None:
    store, broker, intent = prepared(tmp_path, quantity=3)
    dispatch(store, broker, intent)
    broker.fill(1, 1, D(99), "COST-A.01", D("0.1"))
    broker.fill(1, 2, D(100), "COST-B.01", D("0.1"))
    ex.reconcile(store, broker, at=broker.now)
    broker.now = datetime(2024, 1, 3, 22, tzinfo=UTC)
    sell = create_intent(
        "sell",
        broker.account,
        broker.client_id,
        1,
        "SPY",
        "SELL",
        1,
        D(101),
        date(2024, 1, 3),
        broker.now,
    )
    ex.add_intent(store, sell, at=broker.now)
    broker.now = sell.valid_from
    ex.submit(store, broker, "sell", at=broker.now)
    broker.fill(2, 1, D(102), "COST-SELL.01", D("0.1"))
    state = ex.reconcile(store, broker, at=broker.now)
    assert state.position_cost[1] == D("199.333333333333333333")
    assert state.cash_delta == D("-197.3") and not state.issues
    ex.export_report(store, tmp_path / "report")
