"""Incremental close decisions and delayed open accounting, never historical decisions."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import pyarrow as pa

from invest.forward_config import Observation
from invest.market import MONEY
from invest.paper import TRADE_SCHEMA, ZERO, Account, Order, money
from invest.portfolio import (
    CORRELATION_SCHEMA,
    NAV_SCHEMA,
    ORDER_SCHEMA,
    PORTFOLIO_EVENT_SCHEMA,
    POSITION_SCHEMA,
    PortfolioResult,
)
from invest.quality import regular_sessions
from invest.risk import position_exit, risk_status
from invest.strategies import History, target_weights
from invest.study_config import StudyConfig

STAMP = pa.timestamp("us", tz="UTC")
INTENT_SCHEMA = pa.schema(
    [
        *list(ORDER_SCHEMA),
        ("order_id", pa.string()),
        ("decided_at", STAMP),
        ("effective_at", STAMP),
        ("input_received_at", STAMP),
    ]
)
FILL_SCHEMA = pa.schema(
    [
        *list(TRADE_SCHEMA),
        ("order_id", pa.string()),
        ("decided_at", STAMP),
        ("proxy_at", STAMP),
        ("recorded_at", STAMP),
        ("execution_basis", pa.string()),
    ]
)
OUTCOME_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("recorded_at", STAMP),
        ("status", pa.string()),
        ("detail", pa.string()),
    ]
)
SIGNAL_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("recorded_at", STAMP),
        ("raw_target", MONEY),
        ("reason", pa.string()),
    ]
)
STATE_SCHEMA = pa.schema(
    [
        ("cash", MONEY),
        ("peak", MONEY),
        ("risk_status", pa.string()),
        ("operations", pa.string()),
        ("last_session", pa.date32()),
        ("sessions", pa.int64()),
    ]
)
# Ratios are exact Decimal strings, avoiding rounding average entry/risk anchors on restart.
LEDGER_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("shares", pa.int64()),
        ("entry", pa.string()),
        ("position_peak", pa.string()),
        ("position_income", pa.string()),
        ("signal_income", pa.string()),
        (
            "receivables",
            pa.list_(pa.field("element", pa.struct([("payment", pa.date32()), ("amount", MONEY)]))),
        ),
    ]
)


def next_session(session: date) -> dict[str, Any]:
    return dict(
        regular_sessions(session + timedelta(days=1), session + timedelta(days=14)).to_pylist()[0]
    )


@dataclass
class ForwardState:
    cash: Decimal
    peak: Decimal
    risk_status: str
    operations: str
    last_session: date
    sessions: int
    ledgers: dict[str, Account]
    pending: list[dict[str, Any]] = field(default_factory=list)

    def tables(self) -> dict[str, pa.Table]:
        return {
            "state": pa.Table.from_pylist(
                [{k: getattr(self, k) for k in STATE_SCHEMA.names}], schema=STATE_SCHEMA
            ),
            "ledgers": pa.Table.from_pylist(
                [
                    {
                        "symbol": symbol,
                        "shares": ledger.shares,
                        **{
                            k: str(getattr(ledger, k))
                            for k in ["entry", "position_peak", "position_income", "signal_income"]
                        },
                        "receivables": [{"payment": d, "amount": a} for d, a in ledger.receivables],
                    }
                    for symbol, ledger in sorted(self.ledgers.items())
                ],
                schema=LEDGER_SCHEMA,
            ),
            "pending": pa.Table.from_pylist(self.pending, schema=INTENT_SCHEMA),
        }

    @classmethod
    def load(cls, tables: dict[str, pa.Table]) -> "ForwardState":
        ledgers = {}
        for row in tables["ledgers"].to_pylist():
            ledgers[row["symbol"]] = Account(
                cash=ZERO,
                shares=row["shares"],
                entry=Decimal(row["entry"]),
                position_peak=Decimal(row["position_peak"]),
                position_income=Decimal(row["position_income"]),
                signal_income=Decimal(row["signal_income"]),
                receivables=[(r["payment"], r["amount"]) for r in row["receivables"]],
            )
        return cls(
            **tables["state"].to_pylist()[0], ledgers=ledgers, pending=tables["pending"].to_pylist()
        )


def cancel_future(state: ForwardState, now: datetime, reason: str) -> pa.Table:
    """An order whose proxy open has passed must still be settled, even while paused."""
    cancelled = [p for p in state.pending if p["effective_at"] > now]
    state.pending = [p for p in state.pending if p["effective_at"] <= now]
    return pa.Table.from_pylist(
        [
            {"order_id": p["order_id"], "recorded_at": now, "status": "cancelled", "detail": reason}
            for p in cancelled
        ],
        schema=OUTCOME_SCHEMA,
    )


def advance(
    state: ForwardState,
    inputs: dict[str, pa.Table],
    config: StudyConfig,
    plan: Observation,
    account_id: str,
    now: datetime,
    received_at: datetime,
) -> dict[str, pa.Table]:
    """Account for new bars; only the latest close may produce a decision at actual now."""
    symbols = sorted(inputs)
    rows = {s: inputs[s].to_pylist() for s in symbols}
    dates = inputs[symbols[0]]["date"].to_pylist()
    history: History = {s: [] for s in symbols}
    snapshots: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    intents: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    correlations: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []

    def event(session: date, symbol: str, kind: str, detail: str) -> None:
        events.append(
            {"date": session, "symbol": symbol, "kind": kind, "detail": detail, "amount": ZERO}
        )

    def value(i: int, field: str) -> tuple[Decimal, Decimal, Decimal]:
        market = money(sum((state.ledgers[s].shares * rows[s][i][field] for s in symbols), ZERO))
        unpaid = money(sum((a for s in symbols for _, a in state.ledgers[s].receivables), ZERO))
        return market, unpaid, money(state.cash + market + unpaid)

    for i, session in enumerate(dates):
        for s in symbols:
            values, row = history[s], rows[s][i]
            values.append(
                Decimal(100)
                if not values
                else values[-1]
                * row["split_ratio"]
                * (row["close"] + row["dividend"])
                / rows[s][i - 1]["close"]
            )
        if session <= state.last_session:
            continue
        opening = regular_sessions(session, session).to_pylist()[0]["open_at"]
        for s in symbols:
            ledger = state.ledgers[s]
            pending = next((p for p in state.pending if p["symbol"] == s), None)
            ledger.pending = (
                Order(
                    pending["decision_date"],
                    pending["side"],
                    pending["quantity"],
                    pending["reason"],
                )
                if pending
                else None
            )
            ledger.cash = state.cash
            ledger.events.clear()
            ledger.trades.clear()
            ledger.corporate_actions(rows[s][i])
            state.cash = ledger.cash
            events.extend({**e, "symbol": s} for e in ledger.events)
            ledger.events.clear()
        for intent in sorted(state.pending, key=lambda p: (p["side"] != "sell", p["symbol"])):
            s = intent["symbol"]
            ledger = state.ledgers[s]
            if intent["effective_at"] != opening or not intent["decided_at"] < opening <= now:
                raise ValueError("Persisted intent has invalid execution timing")
            market, _, nav = value(i, "open")
            budget = max(
                ZERO,
                min(
                    state.cash,
                    nav * config.allocation - market,
                    nav * config.position_cap - ledger.shares * rows[s][i]["open"],
                ),
            )
            ledger.cash = state.cash
            ledger.execute(session, rows[s][i]["open"], config.paper(s), capital_budget=budget)
            state.cash = ledger.cash
            fills.extend(
                {
                    **t,
                    "order_id": intent["order_id"],
                    "decided_at": intent["decided_at"],
                    "proxy_at": opening,
                    "recorded_at": now,
                    "execution_basis": "delayed_daily_open_proxy",
                }
                for t in ledger.trades
            )
            events.extend({**e, "symbol": s} for e in ledger.events)
            filled = sum(t["quantity"] for t in ledger.trades if isinstance(t["quantity"], int))
            requested = intent["quantity"] * rows[s][i]["split_ratio"]
            outcomes.append(
                {
                    "order_id": intent["order_id"],
                    "recorded_at": now,
                    "status": "filled"
                    if filled == requested
                    else "reduced"
                    if filled
                    else "rejected",
                    "detail": f"requested={requested}; filled={filled}; residual cancelled",
                }
            )
        state.pending = []
        market, unpaid, nav = value(i, "close")
        if state.cash < 0 or nav <= 0:
            raise ValueError("Forward cash/equity invariant failed")
        state.peak = max(state.peak, nav)
        previous = state.risk_status
        state.risk_status = risk_status(
            previous, nav, state.peak, config.initial_cash, config.account_drawdown
        )
        if previous != state.risk_status:
            event(session, "", "risk_state", f"{previous} -> {state.risk_status}")
        state.sessions += 1
        state.last_session = session
        snapshots.append(
            {
                "date": session,
                "cash": state.cash,
                "market_value": market,
                "receivables": unpaid,
                "equity": nav,
                "drawdown": float(nav / state.peak - 1),
                "gross_exposure": float(market / nav),
                "status": state.risk_status,
            }
        )
        for s in symbols:
            ledger = state.ledgers[s]
            market_value = money(ledger.shares * rows[s][i]["close"])
            ledger.position_peak = (
                max(ledger.position_peak, rows[s][i]["close"] + ledger.position_income)
                if ledger.shares
                else ZERO
            )
            positions.append(
                {
                    "date": session,
                    "symbol": s,
                    "shares": ledger.shares,
                    "market_value": market_value,
                    "receivables": money(sum((a for _, a in ledger.receivables), ZERO)),
                    "weight": float(market_value / nav),
                    "risk_group": "us_equity",
                }
            )
        if i != len(dates) - 1:
            event(session, "", "missed_decision", "Accounting catch-up only; no backdated intent")
            continue
        effective = next_session(session)["open_at"]
        if state.operations != "active" or now >= effective:
            if now >= effective and state.operations == "active":
                state.operations = "paused"
            event(session, "", "decision_skipped", "Paused or next execution open already passed")
            continue
        ending = state.sessions >= plan.sessions
        targets = None
        if (state.sessions - 1) % config.rebalance_sessions == 0:
            targets, checks = target_weights(plan.signal, history, config)
            correlations.extend({"date": session, **check} for check in checks)
        for s in symbols:
            ledger, closing = state.ledgers[s], rows[s][i]["close"]
            weight = targets.get(s, ZERO) if targets is not None else None
            signals.append(
                {
                    "date": session,
                    "symbol": s,
                    "recorded_at": now,
                    "raw_target": money(weight) if weight is not None else None,
                    "reason": "rebalance" if targets is not None else "not_scheduled",
                }
            )
            reason = (
                position_exit(
                    closing + ledger.position_income,
                    ledger.entry,
                    ledger.position_peak,
                    config.stop_loss,
                    config.trailing_stop,
                )
                if ledger.shares
                else ""
            )
            if ending or state.risk_status != "active":
                weight, reason = ZERO, "observation_end" if ending else state.risk_status
            elif reason:
                weight = ZERO
            elif (
                ledger.shares * closing > nav * config.position_cap
                or market > nav * config.allocation
            ):
                weight = min(
                    weight if weight is not None else ledger.shares * closing / nav,
                    config.position_cap,
                    config.allocation * ledger.shares * closing / max(market, Decimal(1)),
                )
                reason = "exposure_reduction"
            if weight is None:
                continue
            desired = max(0, int((nav * weight / closing).to_integral_value(rounding=ROUND_FLOOR)))
            delta = desired - ledger.shares
            if delta:
                intents.append(
                    {
                        "decision_date": session,
                        "symbol": s,
                        "side": "buy" if delta > 0 else "sell",
                        "quantity": abs(delta),
                        "target_weight": money(weight),
                        "reason": reason or "rebalance",
                        "order_id": f"{account_id}:{session}:{s}",
                        "decided_at": now,
                        "effective_at": effective,
                        "input_received_at": received_at,
                    }
                )
        state.pending = intents.copy()
        if ending and not market and not unpaid and not state.pending:
            state.operations = "completed"
    return {
        **state.tables(),
        "equity": pa.Table.from_pylist(snapshots, schema=NAV_SCHEMA),
        "positions": pa.Table.from_pylist(positions, schema=POSITION_SCHEMA),
        "trades": pa.Table.from_pylist(fills, schema=FILL_SCHEMA),
        "orders": pa.Table.from_pylist(intents, schema=INTENT_SCHEMA),
        "events": pa.Table.from_pylist(events, schema=PORTFOLIO_EVENT_SCHEMA),
        "correlations": pa.Table.from_pylist(correlations, schema=CORRELATION_SCHEMA),
        "signals": pa.Table.from_pylist(signals, schema=SIGNAL_SCHEMA),
        "outcomes": pa.Table.from_pylist(outcomes, schema=OUTCOME_SCHEMA),
    }


def as_portfolio(tables: dict[str, pa.Table]) -> PortfolioResult:
    return PortfolioResult(
        equity=tables["equity"],
        positions=tables["positions"],
        trades=tables["trades"].select(TRADE_SCHEMA.names),
        orders=tables["orders"].select(ORDER_SCHEMA.names),
        events=tables["events"],
        correlations=tables["correlations"],
    )
