"""Paper execution drills: durable intents, positive broker evidence and restart idempotency.

This journal has no initial capital/NAV and never replaces the M3 capital account.
Only confirmed fills contribute to execution cash/position deltas.
"""

import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa

from invest.engine import engine_digest
from invest.ibkr_data import AMOUNT, SCHEMAS, TIME, snapshot_from_payload, snapshot_payload
from invest.ibkr_models import BrokerSnapshot, IBKRConfig, Intent, PaperBroker, decimal, timestamp
from invest.ibkr_store import EventStore, encode, publish

TERMINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
CANCELED = {"Cancelled", "ApiCancelled"}
ACKNOWLEDGED = {"PreSubmitted", "Submitted", "PendingCancel", "Filled"}


def _now(source: str, at: datetime | None) -> datetime:
    if at is not None and source != "synthetic":
        raise ValueError(
            "Historical/injected execution times are allowed only for synthetic drills"
        )
    return timestamp(at or datetime.now(UTC))


def _identity(store: EventStore, broker: PaperBroker | None = None) -> dict[str, Any]:
    events = store.read()
    if not events or events[0]["kind"] != "register":
        raise ValueError("Initialize an IBKR execution journal first")
    registration: dict[str, Any] = events[0]["payload"]
    if registration["purpose"] != "paper_execution_drill":
        raise ValueError("Not an M4 Paper execution drill journal")
    if broker and (registration["source"], registration["account"], registration["client_id"]) != (
        broker.source,
        broker.account,
        broker.client_id,
    ):
        raise ValueError("Broker source/account/client differs from the registered journal")
    return registration


def initialize(
    store: EventStore,
    broker: PaperBroker,
    config: IBKRConfig,
    *,
    at: datetime | None = None,
) -> None:
    with store.locked():
        if store.read():
            registration = _identity(store, broker)
            if (
                decimal(registration["max_order_notional"]),
                decimal(registration["max_total_notional"]),
            ) != (config.max_order_notional, config.max_total_notional):
                raise ValueError("Execution journal limits cannot be reset on restart")
            return
        if any(path.name not in {".writer.lock", "events"} for path in store.directory.iterdir()):
            raise ValueError("Use a separate empty execution journal directory; preserve M3")
        snapshot = broker.snapshot()
        if (
            snapshot.source != broker.source
            or snapshot.account != broker.account
            or (
                snapshot.source not in {"ibkr", "synthetic"}
                or not snapshot.account.startswith("DU")
            )
        ):
            raise ValueError("Explicit, consistent IBKR Paper source required")
        if not snapshot.complete or snapshot.cash() is None:
            raise ValueError("A complete Paper cash/position baseline is required")
        now = _now(broker.source, at)
        store.append(
            "register",
            "register",
            {
                "purpose": "paper_execution_drill",
                "source": broker.source,
                "account": broker.account,
                "client_id": broker.client_id,
                "max_order_notional": config.max_order_notional,
                "max_total_notional": config.max_total_notional,
                "baseline": snapshot_payload(snapshot),
                "capital_account_modified": False,
                "engine_sha256": engine_digest(),
            },
            now,
        )


@dataclass
class OrderView:
    intent: Intent
    order_id: int | None = None
    perm_id: int = 0
    status: str = "CREATED"
    broker_status: str = ""
    reported_filled: Decimal = Decimal(0)
    filled: Decimal = Decimal(0)
    cancel_requested: bool = False
    commissions_pending: bool = False


@dataclass
class Projection:
    registration: dict[str, Any]
    orders: dict[str, OrderView] = field(default_factory=dict)
    fills: dict[str, dict[str, Any]] = field(default_factory=dict)
    commissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[int, Decimal] = field(default_factory=dict)
    position_cost: dict[int, Decimal] = field(default_factory=dict)
    cash_delta: Decimal = Decimal(0)
    issues: list[str] = field(default_factory=list)
    snapshot: BrokerSnapshot | None = None

    @property
    def gross_notional(self) -> Decimal:
        pending = sum(
            (Decimal(o.intent.quantity) - o.filled) * o.intent.limit_price
            for o in self.orders.values()
            if o.intent.side == "BUY" and o.status not in TERMINAL
        )
        return sum(self.position_cost.values(), Decimal(0)) + pending


def _match(row: dict[str, Any], view: OrderView) -> bool:
    intent = view.intent
    return (row.get("account"), row.get("client_id"), row.get("order_id")) == (
        intent.account,
        intent.client_id,
        view.order_id,
    )


def _validate_match(row: dict[str, Any], view: OrderView, *, execution: bool) -> None:
    intent = view.intent
    side = {"BOT": "BUY", "SLD": "SELL"}.get(row["side"], row["side"])
    if (row["con_id"], row["symbol"], row["currency"], side) != (
        intent.con_id,
        intent.symbol,
        "USD",
        intent.side,
    ) or row["order_ref"] not in {"", intent.order_ref}:
        raise ValueError("Broker order/execution identity conflicts with durable intent")
    if not execution and (
        decimal(row["quantity"]) != intent.quantity
        or (row["order_type"] != "LMT" or decimal(row["limit_price"]) != intent.limit_price)
    ):
        raise ValueError("Broker order economics differ from durable intent")
    if view.perm_id and row["perm_id"] and row["perm_id"] != view.perm_id:
        raise ValueError("IBKR permanent order identity changed")


def _family(exec_id: str) -> tuple[str, int]:
    """IBKR corrections replace the numeric suffix after the final period."""
    prefix, separator, suffix = exec_id.rpartition(".")
    return (prefix, int(suffix)) if separator and suffix.isdigit() else (exec_id, 0)


def project(store: EventStore) -> Projection:
    registration = _identity(store)
    result = Projection(registration)
    if registration["engine_sha256"] != engine_digest():
        result.issues.append("execution_engine_changed")
    executions: dict[str, dict[str, Any]] = {}
    for event in store.read()[1:]:
        kind, row = event["kind"], event["payload"]
        if kind == "intent":
            intent = Intent.parse(row)
            result.orders[intent.intent_id] = OrderView(intent)
        elif kind == "dispatch":
            view = result.orders[row["intent_id"]]
            view.order_id = int(row["order_id"])
            view.status = "UNKNOWN"
        elif kind == "cancel_request":
            result.orders[row["intent_id"]].cancel_requested = True
        elif kind == "broker_order":
            view = result.orders[row["intent_id"]]
            view.perm_id = int(row["perm_id"]) or view.perm_id
            view.reported_filled = max(view.reported_filled, decimal(row["filled"]))
            if view.broker_status not in CANCELED and view.broker_status != "Rejected":
                view.broker_status = "Rejected" if row["rejected"] else row["status"]
        elif kind == "execution":
            executions[row["exec_id"]] = row
        elif kind == "commission":
            result.commissions[row["exec_id"]] = row
        elif kind == "snapshot":
            result.snapshot = snapshot_from_payload(row)
        elif kind == "conflict":
            result.issues.append(row["reason"])
        elif kind not in {"transport_error", "poll_error"}:
            raise ValueError("Unsupported IBKR execution event kind")
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    for exec_id, row in executions.items():
        family, revision = _family(exec_id)
        if family in latest and latest[family][1]["intent_id"] != row["intent_id"]:
            result.issues.append("execution_correction_identity_conflict")
        if family not in latest or revision > latest[family][0]:
            latest[family] = (revision, row)
    result.fills = {row["exec_id"]: row for _, row in latest.values()}
    for row in sorted(result.fills.values(), key=lambda r: (r["trade_at"], r["exec_id"])):
        view = result.orders[row["intent_id"]]
        qty, price = decimal(row["quantity"]), decimal(row["price"])
        view.filled += qty
        con_id = view.intent.con_id
        old_qty = result.positions.get(con_id, Decimal(0))
        cost = result.position_cost.get(con_id, Decimal(0))
        if view.intent.side == "BUY":
            result.positions[con_id] = old_qty + qty
            result.position_cost[con_id] = cost + qty * price
            result.cash_delta -= qty * price
        else:
            if qty > old_qty:
                result.issues.append("managed_position_would_be_short")
            result.positions[con_id] = old_qty - qty
            result.position_cost[con_id] = (
                (cost * (old_qty - qty) / old_qty).quantize(
                    Decimal("1e-18"), rounding=ROUND_HALF_EVEN
                )
                if old_qty
                else Decimal(0)
            )
            result.cash_delta += qty * price
        fee = result.commissions.get(row["exec_id"])
        if fee is None or fee["commission"] is None or fee["currency"] != "USD":
            view.commissions_pending = True
            result.issues.append("commission_pending_or_non_usd")
        else:
            result.cash_delta -= decimal(fee["commission"])
    for view in result.orders.values():
        if view.filled > view.intent.quantity:
            result.issues.append("execution_quantity_exceeds_intent")
            view.status = "UNKNOWN"
        elif view.filled == view.intent.quantity:
            view.status = "FILLED"
        elif view.reported_filled > view.filled:
            view.status = "UNKNOWN"
        elif view.broker_status in CANCELED:
            view.status = "CANCELED"
        elif view.broker_status == "Rejected" and not view.filled:
            view.status = "REJECTED"
        elif view.broker_status in ACKNOWLEDGED and view.filled:
            view.status = "PARTIALLY_FILLED"
        elif view.broker_status in ACKNOWLEDGED:
            view.status = "ACKNOWLEDGED"
        elif view.order_id is not None:
            view.status = "UNKNOWN"
        if view.cancel_requested and view.status not in TERMINAL:
            view.status = "CANCEL_PENDING"
        if view.order_id is None and store.read()[-1]["recorded_at"] >= view.intent.valid_until:
            view.status = "EXPIRED"
    snapshot = result.snapshot
    if snapshot:
        if not snapshot.complete:
            result.issues.append("broker_snapshot_incomplete")
        baseline = snapshot_from_payload(registration["baseline"])
        original_ids = {r["exec_id"] for r in baseline.executions}
        original_families = {_family(k)[0] for k in original_ids}
        for row in snapshot.executions:
            if row["exec_id"] not in original_ids and row["exec_id"] not in executions:
                result.issues.append("unmanaged_execution_or_baseline_correction")
            if (
                row["exec_id"] not in original_ids
                and _family(row["exec_id"])[0] in original_families
            ):
                result.issues.append("baseline_execution_corrected")
        expected = baseline.position_quantities()
        for con_id, delta in result.positions.items():
            expected[con_id] = expected.get(con_id, Decimal(0)) + delta
        actual = snapshot.position_quantities()
        if {k: v for k, v in expected.items() if v} != {k: v for k, v in actual.items() if v}:
            result.issues.append("broker_position_mismatch")
        initial_cash, actual_cash = baseline.cash(), snapshot.cash()
        if (
            actual_cash is None
            or initial_cash is None
            or abs(actual_cash - initial_cash - result.cash_delta) > Decimal("0.01")
        ):
            result.issues.append("broker_cash_mismatch")
        for row in snapshot.orders:
            if row["status"] not in {*CANCELED, "Filled", "Inactive"} and not any(
                _match(row, view) for view in result.orders.values() if view.order_id is not None
            ):
                result.issues.append("unmanaged_open_order")
        for view in result.orders.values():
            if (
                view.order_id is not None
                and view.status not in TERMINAL
                and not any(_match(r, view) for r in snapshot.orders)
            ):
                view.status = "UNKNOWN"  # An absent order is never proof it was not submitted.
    if any(view.status in {"UNKNOWN", "CANCEL_PENDING"} for view in result.orders.values()):
        result.issues.append("order_status_unresolved")
    result.issues = sorted(set(result.issues))
    return result


def add_intent(store: EventStore, intent: Intent, *, at: datetime | None = None) -> bool:
    with store.locked():
        registration = _identity(store)
        now = _now(registration["source"], at)
        if (intent.account, intent.client_id) != (
            registration["account"],
            registration["client_id"],
        ):
            raise ValueError("Intent account/client differs from execution journal")
        state = project(store)
        existing = state.orders.get(intent.intent_id)
        if existing:
            if encode(existing.intent.payload()) != encode(intent.payload()):
                raise ValueError("Intent idempotency key already has different order economics")
            return False
        if registration["engine_sha256"] != engine_digest():
            raise ValueError("Execution engine changed; reconcile with the registered runtime")
        if (
            not intent.decision_at <= now <= intent.decision_at + timedelta(seconds=5)
            or now >= intent.valid_from
        ):
            raise ValueError(
                "Persist real-time decisions before the next session opens; no backfill"
            )
        if intent.quantity * intent.limit_price > decimal(registration["max_order_notional"]):
            raise ValueError("Intent exceeds the per-order Paper notional limit")
        if (
            intent.side == "BUY"
            and state.gross_notional + intent.quantity * intent.limit_price
            > decimal(registration["max_total_notional"])
        ):
            raise ValueError("Intent exceeds the total Paper notional reservation")
        if intent.side == "SELL":
            reserved = sum(
                (Decimal(v.intent.quantity) - v.filled)
                for v in state.orders.values()
                if v.intent.con_id == intent.con_id
                and v.intent.side == "SELL"
                and v.status not in TERMINAL
            )
            if reserved + intent.quantity > state.positions.get(intent.con_id, Decimal(0)):
                raise ValueError("Cannot reserve unmanaged shares or overbook pending sells")
        return store.append("intent", f"intent:{intent.intent_id}", intent.payload(), now)


def _ingest(store: EventStore, broker: PaperBroker, now: datetime) -> datetime:
    registration = _identity(store, broker)
    snap = broker.snapshot()
    now = now if broker.source == "synthetic" else _now(broker.source, None)
    if (snap.source, snap.account) != (registration["source"], registration["account"]):
        raise ValueError("Broker snapshot identity/source differs from journal")
    store.append("snapshot", "snapshot:" + uuid.uuid4().hex, snapshot_payload(snap), now)
    for row in snap.orders:
        views = project(store).orders
        matches = [v for v in views.values() if v.order_id is not None and _match(row, v)]
        related = [v for v in views.values() if row["order_ref"] == v.intent.order_ref]
        if not matches:
            if related:
                store.append(
                    "conflict",
                    "conflict:" + uuid.uuid4().hex,
                    {"reason": "ambiguous_order_ref_or_client", "broker": row},
                    now,
                )
            continue
        view = matches[0]
        try:
            _validate_match(row, view, execution=False)
            if (
                not 0 <= decimal(row["filled"]) <= view.intent.quantity
                or decimal(row["remaining"]) < 0
            ):
                raise ValueError("Invalid broker cumulative order quantities")
        except ValueError as exc:
            store.append(
                "conflict", "conflict:" + uuid.uuid4().hex, {"reason": str(exc), "broker": row}, now
            )
            continue
        payload = {"intent_id": view.intent.intent_id, **row}
        key = "order:" + hashlib.sha256(encode(payload)).hexdigest()
        store.append("broker_order", key, payload, now)
    for row in snap.executions:
        views = project(store).orders
        matches = [v for v in views.values() if v.order_id is not None and _match(row, v)]
        if not matches:
            continue
        view = matches[0]
        try:
            _validate_match(row, view, execution=True)
            traded = timestamp(row["trade_at"])
            if not view.intent.valid_from <= traded <= view.intent.valid_until or (
                decimal(row["quantity"]) <= 0 or decimal(row["price"]) <= 0
            ):
                raise ValueError(
                    "Execution outside the next-session window or invalid quantity/price"
                )
            if (view.intent.side == "BUY" and decimal(row["price"]) > view.intent.limit_price) or (
                view.intent.side == "SELL" and decimal(row["price"]) < view.intent.limit_price
            ):
                raise ValueError("Execution price violates the limit order")
            payload = {"intent_id": view.intent.intent_id, **row}
            store.append("execution", "execution:" + row["exec_id"], payload, now)
        except ValueError as exc:
            store.append(
                "conflict", "conflict:" + uuid.uuid4().hex, {"reason": str(exc), "broker": row}, now
            )
    for row in snap.commissions:
        if any(
            e["kind"] == "execution" and e["payload"]["exec_id"] == row["exec_id"]
            for e in store.read()
        ):
            previous = project(store).commissions.get(row["exec_id"])
            if previous is None or encode(previous) != encode(row):
                store.append("commission", "commission:" + uuid.uuid4().hex, row, now)
    return now


def reconcile(store: EventStore, broker: PaperBroker, *, at: datetime | None = None) -> Projection:
    with store.locked():
        registration = _identity(store, broker)
        _ingest(store, broker, _now(registration["source"], at))
        return project(store)


def submit(
    store: EventStore,
    broker: PaperBroker,
    intent_id: str,
    *,
    at: datetime | None = None,
) -> Projection:
    with store.locked():
        registration = _identity(store, broker)
        now = _now(registration["source"], at)
        now = _ingest(store, broker, now)
        state = project(store)
        view = state.orders[intent_id]
        if view.order_id is not None:
            return state  # Positive reject/cancel also requires a NEW intent to submit again.
        intent = view.intent
        if not intent.valid_from <= now < intent.valid_until:
            raise ValueError("Paper submission is outside its next-session execution window")
        if state.issues:
            raise ValueError("Paper risk increase blocked: " + ", ".join(state.issues))
        if intent.quantity * intent.limit_price > decimal(registration["max_order_notional"]):
            raise ValueError("Per-order limit exceeded")
        if intent.side == "BUY":
            if state.gross_notional > decimal(registration["max_total_notional"]):
                raise ValueError("Total Paper execution notional limit exceeded")
            assert state.snapshot is not None
            settled = state.snapshot.cash("SettledCash")
            cash = state.snapshot.cash()
            pending = state.gross_notional - sum(state.position_cost.values(), Decimal(0))
            if settled is None or cash is None or min(settled, cash) < pending:
                raise ValueError("Insufficient or missing USD settled cash")
        elif state.positions.get(intent.con_id, Decimal(0)) < intent.quantity:
            raise ValueError("Cannot sell unmanaged holdings or open a short position")
        order_id = broker.reserve_order_id()
        if order_id < 1 or any(v.order_id == order_id for v in state.orders.values()):
            raise ValueError("Invalid/reused broker order id; no order sent")
        # This publication MUST precede the network call. A crash means query, never resend.
        store.append(
            "dispatch", f"dispatch:{intent_id}", {"intent_id": intent_id, "order_id": order_id}, now
        )
        try:
            broker.submit(intent, order_id)
            _ingest(store, broker, now)
        except Exception as exc:
            store.append(
                "transport_error",
                "transport:" + uuid.uuid4().hex,
                {"intent_id": intent_id, "error_type": type(exc).__name__},
                now if broker.source == "synthetic" else _now(broker.source, None),
            )
        return project(store)


def cancel(
    store: EventStore,
    broker: PaperBroker,
    intent_id: str,
    *,
    at: datetime | None = None,
) -> Projection:
    with store.locked():
        registration = _identity(store, broker)
        now = _now(registration["source"], at)
        now = _ingest(store, broker, now)
        state = project(store)
        view = state.orders[intent_id]
        if view.status in TERMINAL:
            return state
        if view.cancel_requested and not any(
            _match(row, view) and row["status"] in {"Submitted", "PreSubmitted"}
            for row in (state.snapshot.orders if state.snapshot else [])
        ):
            return state
        if view.order_id is None:
            raise ValueError("Unsubmitted intent has no broker order to cancel")
        store.append(
            "cancel_request",
            f"cancel:{intent_id}:" + uuid.uuid4().hex,
            {"intent_id": intent_id},
            now,
        )
        try:
            broker.cancel(view.intent, view.order_id)
            _ingest(store, broker, now)
        except Exception as exc:
            store.append(
                "transport_error",
                "transport:" + uuid.uuid4().hex,
                {"intent_id": intent_id, "error_type": type(exc).__name__},
                now if broker.source == "synthetic" else _now(broker.source, None),
            )
        return project(store)


ORDER_VIEW_SCHEMA = pa.schema(
    [
        ("intent_id", pa.string()),
        ("source", pa.string()),
        ("account", pa.string()),
        ("client_id", pa.int64()),
        ("order_id", pa.int64()),
        ("perm_id", pa.int64()),
        ("symbol", pa.string()),
        ("side", pa.string()),
        ("quantity", pa.int64()),
        ("limit_price", AMOUNT),
        ("decision_at", TIME),
        ("valid_from", TIME),
        ("valid_until", TIME),
        ("status", pa.string()),
        ("broker_status", pa.string()),
        ("reported_filled", AMOUNT),
        ("order_ref", pa.string()),
        ("intent_limit_notional_usd", AMOUNT),
        ("filled", AMOUNT),
        ("commissions_pending", pa.bool_()),
    ],
    metadata={b"schema_version": b"invest.ibkr.order-projection.v1"},
)

CHECK_SCHEMA = pa.schema(
    [("check", pa.string()), ("passed", pa.bool_()), ("detail", pa.string())],
    metadata={b"schema_version": b"invest.ibkr.execution-checks.v1"},
)


def summary(state: Projection) -> dict[str, Any]:
    return {
        "source": state.registration["source"],
        "environment": "paper",
        "purpose": "paper_execution_drill",
        "orders": len(state.orders),
        "confirmed_executions": len(state.fills),
        "execution_cash_delta_usd": str(state.cash_delta),
        "issues": state.issues,
        "reconciled": state.snapshot is not None and not state.issues,
        "capital_account_modified": False,
        "engine_matches": "execution_engine_changed" not in state.issues,
        "order_states": {key: v.status for key, v in state.orders.items()},
    }


def _export_report(store: EventStore, output: Path) -> dict[str, Any]:
    with store.locked():
        state = project(store)
        output.mkdir(parents=True, exist_ok=False)
        rows = []
        for key, view in state.orders.items():
            intent = view.intent
            rows.append(
                {
                    "intent_id": key,
                    "source": state.registration["source"],
                    "account": intent.account,
                    "client_id": intent.client_id,
                    "order_id": view.order_id,
                    "perm_id": view.perm_id,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "quantity": intent.quantity,
                    "limit_price": intent.limit_price,
                    "decision_at": intent.decision_at,
                    "valid_from": intent.valid_from,
                    "valid_until": intent.valid_until,
                    "status": view.status,
                    "broker_status": view.broker_status,
                    "reported_filled": view.reported_filled,
                    "order_ref": intent.order_ref,
                    "intent_limit_notional_usd": intent.quantity * intent.limit_price,
                    "filled": view.filled,
                    "commissions_pending": view.commissions_pending,
                }
            )
        publish(pa.Table.from_pylist(rows, schema=ORDER_VIEW_SCHEMA), output / "orders.parquet")
        checks = [{"check": issue, "passed": False, "detail": issue} for issue in state.issues]
        checks.append(
            {
                "check": "capital_account_modified",
                "passed": True,
                "detail": "Execution drill only; M3 funds/risk/history remain untouched",
            }
        )
        publish(pa.Table.from_pylist(checks, schema=CHECK_SCHEMA), output / "checks.parquet")
        fill_schema = SCHEMAS["executions"].append(pa.field("intent_id", pa.string()))
        fills = [
            {
                **row,
                "quantity": decimal(row["quantity"]),
                "price": decimal(row["price"]),
                "trade_at": timestamp(row["trade_at"]),
            }
            for row in state.fills.values()
        ]
        publish(
            pa.Table.from_pylist(fills, schema=fill_schema),
            output / "fills.parquet",
        )
        publish(
            pa.Table.from_pylist(
                [
                    {
                        **row,
                        "commission": decimal(row["commission"])
                        if row["commission"] is not None
                        else None,
                        "active_execution": row["exec_id"] in state.fills,
                    }
                    for row in state.commissions.values()
                ],
                schema=SCHEMAS["commissions"].append(pa.field("active_execution", pa.bool_())),
            ),
            output / "commissions.parquet",
        )
        position_schema = pa.schema(
            [
                ("con_id", pa.int64()),
                ("managed_quantity", AMOUNT),
                ("managed_cost_usd", AMOUNT),
                ("baseline_quantity", AMOUNT),
                ("expected_quantity", AMOUNT),
                ("broker_quantity", AMOUNT),
            ],
            metadata={
                b"schema_version": b"invest.ibkr.position-delta.v1",
                b"cost_allocation": b"pro-rata; 18 decimal places; half-even; cash unchanged",
            },
        )
        baseline = snapshot_from_payload(state.registration["baseline"])
        initial_positions = baseline.position_quantities()
        actual_positions = state.snapshot.position_quantities() if state.snapshot else {}
        positions = []
        for con_id in sorted(set(initial_positions) | set(actual_positions) | set(state.positions)):
            initial = initial_positions.get(con_id, Decimal(0))
            managed = state.positions.get(con_id, Decimal(0))
            positions.append(
                {
                    "con_id": con_id,
                    "managed_quantity": managed,
                    "managed_cost_usd": state.position_cost.get(con_id, Decimal(0)),
                    "baseline_quantity": initial,
                    "expected_quantity": initial + managed,
                    "broker_quantity": actual_positions.get(con_id, Decimal(0)),
                }
            )
        publish(
            pa.Table.from_pylist(positions, schema=position_schema), output / "positions.parquet"
        )
        initial_cash = baseline.cash()
        expected_cash = initial_cash + state.cash_delta if initial_cash is not None else None
        actual_cash = state.snapshot.cash() if state.snapshot else None
        cash_schema = pa.schema(
            [
                ("currency", pa.string()),
                ("baseline", AMOUNT),
                ("confirmed_execution_delta", AMOUNT),
                ("expected", AMOUNT),
                ("broker", AMOUNT),
                ("difference", AMOUNT),
                ("report_precision_tolerance", AMOUNT),
            ],
            metadata={b"schema_version": b"invest.ibkr.cash-delta.v1"},
        )
        publish(
            pa.Table.from_pylist(
                [
                    {
                        "currency": "USD",
                        "baseline": initial_cash,
                        "confirmed_execution_delta": state.cash_delta,
                        "expected": expected_cash,
                        "broker": actual_cash,
                        "difference": actual_cash - expected_cash
                        if actual_cash is not None and expected_cash is not None
                        else None,
                        "report_precision_tolerance": Decimal("0.01"),
                    }
                ],
                schema=cash_schema,
            ),
            output / "cash.parquet",
        )
        return summary(state)


def export_report(store: EventStore, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("IBKR reports are immutable; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name("." + output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        result = _export_report(store, staging)
        if output.exists():
            raise ValueError("IBKR report output already exists")
        staging.rename(output)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)
