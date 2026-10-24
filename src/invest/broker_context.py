"""将冻结 IBKR 采集与同会话持久策略状态核对，输出只读决策上下文。"""

import hashlib
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.contracts import Quote
from invest.decision_io import decision_contexts, read_decision_contexts
from invest.ibkr_data import SCHEMAS
from invest.ibkr_models import BrokerSnapshot, decimal
from invest.quality import regular_sessions
from invest.research_data import identity, load_snapshot

# 每股美元均价只容许固定绝对误差，不按价格或股数放宽，也不改写持久成本。
AVERAGE_COST_TOLERANCE = Decimal("0.000001")


def adapt_broker_context(
    capture: Path, state_path: Path, snapshot_path: Path, day: date
) -> pa.Table:
    """只读取采集和状态；未结算现金、分红应收和风险历史不能用缺省值补齐。"""
    bodies = {name: (capture / f"{name}.parquet").read_bytes() for name in SCHEMAS}
    tables = {name: pq.read_table(pa.BufferReader(body)) for name, body in bodies.items()}
    for name, table in tables.items():
        if not table.schema.equals(SCHEMAS[name], check_metadata=False) or any(
            (table.schema.metadata or {}).get(key) != value
            for key, value in (SCHEMAS[name].metadata or {}).items()
        ):
            raise ValueError("Invalid broker capture schema")
    manifests = tables["capture"].to_pylist()
    if len(manifests) != 1:
        raise ValueError("Broker context requires one capture")
    manifest = manifests[0]
    source, broker_account, at = manifest["source"], manifest["account"], manifest["captured_at"]
    if (
        source not in {"ibkr", "synthetic"}
        or manifest["environment"] != "paper"
        or not broker_account
        or not broker_account.startswith("DU")
        or at is None
        or not manifest["complete"]
        or "error" in tables["quality"]["status"].to_pylist()
    ):
        raise ValueError("Broker context requires a complete supported Paper capture")
    sessions = regular_sessions(day, day + timedelta(days=14)).to_pylist()
    if (
        not sessions
        or sessions[0]["date"] != day
        or not sessions[0]["close_at"] <= at < sessions[1]["open_at"]
    ):
        raise ValueError("Broker capture must follow this close and precede the next open")
    for table in tables.values():
        metadata = table.schema.metadata or {}
        if any(
            metadata.get(key) != value.encode()
            for key, value in {
                b"source": source,
                b"account": broker_account,
                b"environment": "paper",
                b"captured_at": at.isoformat(),
            }.items()
        ):
            raise ValueError("Broker tables have inconsistent capture provenance")
    required = {"reqAccountUpdates", "reqPositions", "reqAllOpenOrders", "reqExecutions"}
    queries = [row for row in tables["raw"].to_pylist() if row["method"] in required]
    if {row["method"] for row in queries} != required or any(
        not row["complete"]
        or row["started_at"] is None
        or row["received_at"] is None
        or not sessions[0]["close_at"] <= row["started_at"] <= row["received_at"] <= at
        for row in queries
    ):
        raise ValueError("Broker context requires completed account queries in this capture window")
    if any(
        row["account"] != broker_account
        or row["trade_at"] is None
        or row["trade_at"] > sessions[0]["close_at"]
        for row in tables["executions"].to_pylist()
    ):
        raise ValueError(
            "Broker account changed after the decision close or includes another account"
        )
    state_body = state_path.read_bytes()
    saved = pq.read_table(pa.BufferReader(state_body))
    metadata = saved.schema.metadata or {}
    if (
        metadata.get(b"context_kind") != b"account_state"
        or metadata.get(b"broker_account") != broker_account.encode()
        or metadata.get(b"environment") != b"paper"
        or not metadata.get(b"source_ref")
    ):
        raise ValueError(
            "Broker context requires identified persistent account state, not a preview"
        )
    contexts = read_decision_contexts(saved)
    if len(contexts) != 1 or contexts[0][0].as_of != day:
        raise ValueError("Persistent state must cover exactly the broker decision session")
    account, state = contexts[0]
    snapshot = load_snapshot(snapshot_path)
    if (
        account.source != source
        or snapshot.spec.source != source
        or snapshot.spec.price_basis != "raw"
    ):
        raise ValueError("Broker context requires matching source and raw research quotes")
    positions = tables["positions"].to_pylist()
    orders = tables["orders"].to_pylist()
    values = tables["account_values"].to_pylist()
    if any(row["account"] != broker_account for row in [*positions, *orders, *values]):
        raise ValueError("Broker capture contains another account")
    if any(row.get("model_code") for row in values):
        raise ValueError("Model account balances cannot be mixed with whole-account state")
    if any(
        row["currency"] not in {"", "USD", "BASE"}
        and row["tag"]
        in {"TotalCashValue", "CashBalance", "TotalCashBalance", "SettledCash", "AccruedDividend"}
        and decimal(row["value"]) != 0
        for row in values
    ):
        raise ValueError("Foreign cash balances are unsupported")
    broker = BrokerSnapshot(
        source, broker_account, at, account_values=values, positions=positions, orders=orders
    )
    cash, settled, dividends = (
        broker.cash(tag) for tag in ("TotalCashValue", "SettledCash", "AccruedDividend")
    )
    if cash is None or settled is None or dividends is None or not 0 <= settled <= cash:
        raise ValueError("Broker cash, settlement and dividend evidence is incomplete")
    if (
        account.cash != cash
        or account.unsettled_cash != cash - settled
        or account.receivables != dividends
    ):
        raise ValueError("Persistent cash, settlement or dividends disagree with broker capture")
    contracts = tables["contracts"].to_pylist()
    mapping = {row["con_id"]: row for row in contracts}
    if len(mapping) != len(contracts):
        raise ValueError("Duplicate broker contracts")

    def instrument(row: dict[str, Any]) -> str:
        contract = mapping.get(row["con_id"])
        if (
            contract is None
            or contract["security_type"] != "STK"
            or contract["currency"] != "USD"
            or row["currency"] != "USD"
            or row["symbol"] != contract["symbol"]
            or row["con_id"] <= 0
        ):
            raise ValueError("Broker holdings and orders require qualified USD stock identities")
        return f"IBKR{row['con_id']}"

    holdings = {item.instrument: item for item in account.holdings}
    observed = {}
    for row in positions:
        key = instrument(row)
        quantity = decimal(row["quantity"])
        if quantity < 0 or quantity != quantity.to_integral_value() or key in observed:
            raise ValueError("Short, fractional or duplicate broker positions are unsupported")
        if quantity == 0:
            continue
        observed[key] = quantity
        held = holdings.get(key)
        average_cost = decimal(row["average_cost"])
        if (
            held is None
            or held.shares != quantity
            or average_cost <= 0
            or abs(held.entry - average_cost) > AVERAGE_COST_TOLERANCE
        ):
            raise ValueError("Persistent holdings or cost anchors disagree with broker capture")
    if set(observed) != set(holdings):
        raise ValueError("Persistent holdings disagree with complete broker positions")
    pending: dict[str, tuple[str, int, Decimal]] = {}
    order_keys = set()
    for row in orders:
        order_key = (row["client_id"], row["order_id"])
        if order_key in order_keys:
            raise ValueError("Duplicate broker order identity")
        order_keys.add(order_key)
        if row["status"] in {"Cancelled", "ApiCancelled", "Filled"}:
            if row["status"] == "Filled" and decimal(row["remaining"]) != 0:
                raise ValueError("Filled broker order has remaining quantity")
            continue
        key = instrument(row)
        if (
            row["status"]
            not in {"Submitted", "PreSubmitted", "PendingSubmit", "PendingCancel", "ApiPending"}
            or row["rejected"]
            or row["order_type"] != "LMT"
            or row["side"] not in {"BUY", "SELL"}
        ):
            raise ValueError("Unsupported or unresolved broker order")
        quantity, filled, remaining = (
            decimal(row[name]) for name in ("quantity", "filled", "remaining")
        )
        if (
            remaining <= 0
            or filled < 0
            or filled + remaining != quantity
            or any(value != value.to_integral_value() for value in (quantity, filled, remaining))
            or key in pending
            or decimal(row["limit_price"]) <= 0
        ):
            raise ValueError("Fractional, conflicting or inconsistent broker pending orders")
        pending[key] = (row["side"].lower(), int(remaining), decimal(row["limit_price"]))
    if pending != {
        item.instrument: (item.side, item.quantity, item.reference_price)
        for item in account.pending
    }:
        raise ValueError("Persistent pending orders disagree with broker capture")
    current = {row["instrument"]: row for row in snapshot.bars.to_pylist() if row["date"] == day}
    if not (set(holdings) | set(pending)) <= current.keys():
        raise ValueError("Broker holdings or orders lack a raw research quote")
    quotes = []
    for key, row in sorted(current.items()):
        matching = [item for item in snapshot.universe.to_pylist() if item["instrument"] == key]
        contract = next((item for con_id, item in mapping.items() if key == f"IBKR{con_id}"), None)
        if contract is None or any(item["symbol"] != contract["symbol"] for item in matching):
            raise ValueError("Research universe differs from broker contract identity")
        quotes.append(
            Quote(
                key,
                row["close"].quantize(Decimal(".000001")),
                active=any(item["start"] <= day <= item["end"] for item in matching),
            )
        )
    if (
        len(state.positions) != len(holdings)
        or {p.instrument for p in state.positions} != set(holdings)
        or any(
            p.entered_on is None or p.entered_on > day or not p.peak.is_finite() or p.peak <= 0
            for p in state.positions
        )
        or state.last_session != day
        or (state.last_rebalance is not None and state.last_rebalance > day)
        or len({key for key, _ in state.last_exits}) != len(state.last_exits)
        or any(exited > day for _, exited in state.last_exits)
        or not state.peak_equity.is_finite()
        or state.peak_equity < account.initial_cash
        or state.risk_status not in {"active", "warning", "halted", "terminated"}
    ):
        raise ValueError("Persistent strategy history is incomplete or invalid")
    adapted = replace(account, snapshot_id=snapshot.snapshot_id, quotes=tuple(quotes))
    capture_id = identity({name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()})
    return decision_contexts(((adapted, state),)).replace_schema_metadata(
        {
            **(saved.schema.metadata or {}),
            b"context_kind": b"broker_capture",
            b"price_basis": b"raw",
            b"broker_capture_id": capture_id.encode(),
            b"broker_captured_at": at.isoformat().encode(),
            b"source_ref": (
                f"{source}:{capture_id}:state:{hashlib.sha256(state_body).hexdigest()}".encode()
            ),
            b"state_source_ref": metadata[b"source_ref"],
        }
    )
