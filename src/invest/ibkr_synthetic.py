"""Explicitly synthetic broker for offline execution engineering; no external API calls."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from invest import ibkr_execution as execution
from invest.ibkr_data import Capture, save_capture
from invest.ibkr_models import BrokerSnapshot, IBKRConfig, Intent, create_intent
from invest.ibkr_store import EventStore


class SyntheticBroker:
    source = "synthetic"
    account = "DU_SYNTHETIC"
    client_id = 72

    def __init__(self, cash: Decimal = Decimal("5000")) -> None:
        self.cash = cash
        self.settled = cash
        self.positions: dict[int, Decimal] = {}
        self.orders: list[dict[str, Any]] = []
        self.executions: list[dict[str, Any]] = []
        self.commissions: list[dict[str, Any]] = []
        self.now = datetime(2024, 1, 2, 22, tzinfo=UTC)
        self.next_id = 1
        self.submissions = 0
        self.cancellations = 0
        self.fail_before = False
        self.fail_after = False
        self.visible = True

    def snapshot(self) -> BrokerSnapshot:
        return BrokerSnapshot(
            self.source,
            self.account,
            self.now,
            [
                {
                    "account": self.account,
                    "tag": tag,
                    "value": str(amount),
                    "currency": "USD",
                    "model_code": "",
                }
                for tag, amount in (("TotalCashValue", self.cash), ("SettledCash", self.settled))
            ],
            [
                {
                    "account": self.account,
                    "con_id": con_id,
                    "symbol": "SPY" if con_id == 1 else "XLF",
                    "currency": "USD",
                    "quantity": qty,
                    "average_cost": None,
                }
                for con_id, qty in self.positions.items()
                if qty
            ],
            deepcopy(self.orders if self.visible else []),
            deepcopy(self.executions),
            deepcopy(self.commissions),
        )

    def reserve_order_id(self) -> int:
        result = self.next_id
        self.next_id += 1
        return result

    def submit(self, intent: Intent, order_id: int) -> None:
        self.submissions += 1
        if self.fail_before:
            raise TimeoutError("Synthetic disconnect before broker acceptance")
        self.orders.append(
            {
                "account": self.account,
                "client_id": self.client_id,
                "order_id": order_id,
                "perm_id": 1000 + order_id,
                "order_ref": intent.order_ref,
                "con_id": intent.con_id,
                "symbol": intent.symbol,
                "currency": "USD",
                "side": intent.side,
                "quantity": Decimal(intent.quantity),
                "limit_price": intent.limit_price,
                "order_type": "LMT",
                "status": "Submitted",
                "filled": Decimal(0),
                "remaining": Decimal(intent.quantity),
                "rejected": False,
            }
        )
        if self.fail_after:
            raise TimeoutError("Synthetic accepted order, lost acknowledgment")

    def cancel(self, intent: Intent, order_id: int) -> None:
        self.cancellations += 1
        row = next(r for r in self.orders if r["order_id"] == order_id)
        if row["remaining"]:
            row["status"] = "Cancelled"

    def fill(
        self,
        order_id: int,
        quantity: int,
        price: Decimal,
        exec_id: str,
        commission: Decimal | None = None,
    ) -> None:
        row = next(r for r in self.orders if r["order_id"] == order_id)
        row["filled"] += quantity
        row["remaining"] -= quantity
        if not row["remaining"]:
            row["status"] = "Filled"
        direction = 1 if row["side"] == "BUY" else -1
        self.cash -= direction * quantity * price
        self.settled = self.cash
        self.positions[row["con_id"]] = (
            self.positions.get(row["con_id"], Decimal(0)) + direction * quantity
        )
        self.executions.append(
            {
                "exec_id": exec_id,
                "account": self.account,
                "client_id": self.client_id,
                "order_id": order_id,
                "perm_id": row["perm_id"],
                "order_ref": row["order_ref"],
                "con_id": row["con_id"],
                "symbol": row["symbol"],
                "currency": "USD",
                "side": "BOT" if direction == 1 else "SLD",
                "quantity": Decimal(quantity),
                "price": price,
                "trade_at": self.now,
            }
        )
        if commission is not None:
            self.fee(exec_id, commission)

    def fee(self, exec_id: str, amount: Decimal) -> None:
        old = next((r for r in self.commissions if r["exec_id"] == exec_id), None)
        previous = old["commission"] if old else Decimal(0)
        if old:
            self.commissions.remove(old)
        self.commissions.append({"exec_id": exec_id, "currency": "USD", "commission": amount})
        self.cash -= amount - previous
        self.settled = self.cash


def demo_capture(broker: SyntheticBroker, config: IBKRConfig) -> Capture:
    capture = Capture(broker.snapshot(), config)
    for con_id, symbol in enumerate(config.symbols, 1):
        price = Decimal("100") if con_id == 1 else Decimal("50")
        capture.contracts.append(
            {
                "con_id": con_id,
                "symbol": symbol,
                "security_type": "STK",
                "currency": "USD",
                "exchange": "SMART",
                "primary_exchange": "ARCA",
                "min_tick": Decimal("0.01"),
            }
        )
        capture.historical.append(
            {
                "con_id": con_id,
                "symbol": symbol,
                "session": date(2024, 1, 2),
                "bar_at": None,
                "bar_size": "1 day",
                "what_to_show": "TRADES",
                "price_basis": "split_adjusted",
                "use_rth": True,
                "currency": "USD",
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": Decimal(1000),
                "volume_unit": "provider_reported_unverified",
            }
        )
        capture.quotes.append(
            {
                "con_id": con_id,
                "symbol": symbol,
                "currency": "USD",
                "requested_type": 3,
                "actual_type": 3,
                "sdk_updated_at": broker.now,
                "exchange_trade_at": None,
                "received_at": broker.now,
                "bid": price,
                "ask": price,
                "last": price,
                "bid_size": Decimal(100),
                "ask_size": Decimal(100),
                "last_size": Decimal(100),
            }
        )
    return capture


def run_demo(output: Path) -> dict[str, Any]:
    store = EventStore(output / "journal")
    if store.read():
        with store.locked():
            state = execution.project(store)
            if state.registration["source"] != "synthetic":
                raise ValueError("Demo cannot use a real IBKR journal")
            return execution.summary(state)
    broker, config = SyntheticBroker(), IBKRConfig()
    save_capture(demo_capture(broker, config), output / "captures")
    execution.initialize(store, broker, config, at=broker.now)
    intent = create_intent(
        "demo-buy",
        broker.account,
        broker.client_id,
        1,
        "SPY",
        "BUY",
        2,
        Decimal("100"),
        date(2024, 1, 2),
        broker.now,
    )
    execution.add_intent(store, intent, at=broker.now)
    broker.now = intent.valid_from
    broker.fail_after = True
    state = execution.submit(store, broker, intent.intent_id, at=broker.now)
    assert state.orders[intent.intent_id].status == "UNKNOWN"
    broker.now += timedelta(seconds=1)
    execution.submit(store, broker, intent.intent_id, at=broker.now)
    assert broker.submissions == 1
    broker.fill(1, 1, Decimal("99.5"), "DEMO.01")
    state = execution.reconcile(store, broker, at=broker.now)
    assert state.orders[intent.intent_id].commissions_pending
    broker.fee("DEMO.01", Decimal("0.50"))
    state = execution.cancel(store, broker, intent.intent_id, at=broker.now)
    assert state.orders[intent.intent_id].status == "CANCELED"
    assert state.cash_delta == Decimal("-100") and not state.issues
    result = execution.export_report(store, output / "report")
    return {**result, "submissions": broker.submissions, "cancellations": broker.cancellations}
