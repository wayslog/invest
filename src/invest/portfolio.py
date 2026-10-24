"""Shared-cash, whole-share research portfolio using the M1 accounting core."""

from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import pyarrow as pa

from invest.market import validate_bars
from invest.paper import TRADE_SCHEMA, ZERO, Account, Order, money
from invest.portfolio_types import (
    CORRELATION_SCHEMA as CORRELATION_SCHEMA,
)
from invest.portfolio_types import (
    NAV_SCHEMA as NAV_SCHEMA,
)
from invest.portfolio_types import (
    ORDER_SCHEMA as ORDER_SCHEMA,
)
from invest.portfolio_types import (
    PORTFOLIO_EVENT_SCHEMA as PORTFOLIO_EVENT_SCHEMA,
)
from invest.portfolio_types import (
    POSITION_SCHEMA as POSITION_SCHEMA,
)
from invest.portfolio_types import (
    PortfolioResult as PortfolioResult,
)
from invest.quality import regular_sessions
from invest.risk import position_exit, risk_status
from invest.strategies import Candidate, History, target_weights
from invest.study_config import StudyConfig


def simulate_portfolio(
    inputs: dict[str, pa.Table],
    config: StudyConfig,
    candidate: Candidate,
    start: date,
    end: date,
    *,
    cost_multiplier: int = 1,
    gap_bps: int = 0,
) -> PortfolioResult:
    if len(inputs) < 2 or set(inputs) - set(config.symbols):
        raise ValueError("Portfolio requires >= 2 admitted symbols from the registered universe")
    if cost_multiplier < 1 or not 0 <= gap_bps < 10000:
        raise ValueError("Invalid cost/gap scenario")
    symbols = sorted(inputs)
    for symbol, table in inputs.items():
        validate_bars(table, symbol)
        if min(table["volume"].to_pylist()) <= 0:
            raise ValueError("Zero-volume history is not executable")
    dates = inputs[symbols[0]]["date"].to_pylist()
    if dates != regular_sessions(dates[0], dates[-1])["date"].to_pylist() or any(
        inputs[s]["date"].to_pylist() != dates for s in symbols
    ):
        raise ValueError("All portfolio inputs must share complete, identical sessions")
    evaluation = regular_sessions(start, end)["date"].to_pylist()
    if not evaluation or evaluation[0] not in dates or evaluation[-1] not in dates:
        raise ValueError("Requested evaluation range is not covered")
    first, last = dates.index(evaluation[0]), dates.index(evaluation[-1])
    if first < config.warmup:
        raise ValueError("Insufficient common warmup before evaluation")
    rows = {s: inputs[s].to_pylist() for s in symbols}
    ledgers = {s: Account(cash=ZERO) for s in symbols}
    history: History = {s: [] for s in symbols}
    cash, peak, status = config.initial_cash, config.initial_cash, "active"
    snapshots: list[dict[str, object]] = []
    positions: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    correlations: list[dict[str, object]] = []
    total_cap = Decimal(1) if candidate.kind == "market" else config.allocation
    position_cap = config.position_cap if candidate.is_strategy else total_cap

    def valuations(index: int, field: str) -> tuple[Decimal, Decimal, Decimal]:
        market = money(sum((ledgers[s].shares * rows[s][index][field] for s in symbols), ZERO))
        receivable = money(
            sum((amount for s in symbols for _, amount in ledgers[s].receivables), ZERO)
        )
        return market, receivable, money(cash + market + receivable)

    def event(session: date, symbol: str, kind: str, detail: str) -> None:
        events.append(
            {"date": session, "symbol": symbol, "kind": kind, "detail": detail, "amount": ZERO}
        )

    for i in range(first - config.warmup, last + 1):
        session = dates[i]
        current: dict[str, dict[str, Any]] = {s: rows[s][i] for s in symbols}
        for symbol in symbols:
            values, row = history[symbol], current[symbol]
            values.append(
                Decimal(100)
                if not values
                else values[-1]
                * row["split_ratio"]
                * (row["close"] + row["dividend"])
                / rows[symbol][i - 1]["close"]
            )
        if i >= first:
            # All entitlements/payments precede all fills; there is exactly one cash pool.
            for symbol in symbols:
                ledger = ledgers[symbol]
                before = len(ledger.events)
                ledger.cash = cash
                ledger.corporate_actions(current[symbol])
                cash = ledger.cash
                events.extend({**item, "symbol": symbol} for item in ledger.events[before:])
            for side in ["sell", "buy"]:
                for symbol in symbols:
                    ledger = ledgers[symbol]
                    if ledger.pending is None or ledger.pending.side != side:
                        continue
                    market, _, opening_nav = valuations(i, "open")
                    budget = max(
                        ZERO,
                        min(
                            cash,
                            opening_nav * total_cap - market,
                            opening_nav * position_cap - ledger.shares * current[symbol]["open"],
                        ),
                    )
                    ledger.cash = cash
                    before_events, before_trades = len(ledger.events), len(ledger.trades)
                    direction = 1 if side == "buy" else -1
                    stress_open = current[symbol]["open"] * (
                        1 + Decimal(direction * gap_bps) / 10000
                    )
                    ledger.execute(
                        session,
                        stress_open,
                        config.paper(symbol, cost_multiplier),
                        capital_budget=budget,
                    )
                    cash = ledger.cash
                    trades.extend(ledger.trades[before_trades:])
                    events.extend(
                        {**item, "symbol": symbol} for item in ledger.events[before_events:]
                    )
            market, receivable, nav = valuations(i, "close")
            if cash < 0 or nav <= 0:
                raise ValueError("Portfolio cash/equity invariant failed")
            peak = max(peak, nav)
            previous = status
            if candidate.is_strategy:
                status = risk_status(
                    status, nav, peak, config.initial_cash, config.account_drawdown
                )
            if previous != status:
                event(session, "", "risk_state", f"{previous} -> {status}")
            snapshots.append(
                {
                    "date": session,
                    "cash": money(cash),
                    "market_value": market,
                    "receivables": receivable,
                    "equity": nav,
                    "drawdown": float(nav / peak - 1),
                    "gross_exposure": float(market / nav),
                    "status": status,
                }
            )
            for symbol in symbols:
                ledger = ledgers[symbol]
                value = money(ledger.shares * current[symbol]["close"])
                positions.append(
                    {
                        "date": session,
                        "symbol": symbol,
                        "shares": ledger.shares,
                        "market_value": value,
                        "receivables": money(sum((a for _, a in ledger.receivables), ZERO)),
                        "weight": float(value / nav),
                        "risk_group": "us_equity",
                    }
                )
        if i < first - 1:
            continue
        _, _, nav = valuations(i, "close")
        initial = i == first - 1
        scheduled = initial or (
            candidate.kind not in {"buy_hold", "market", "cash"}
            and (i - first + 1) % config.rebalance_sessions == 0
        )
        targets: dict[str, Decimal] | None = None
        if scheduled:
            targets, checks = target_weights(candidate, history, config)
            correlations.extend({"date": session, **item} for item in checks)
        for symbol in symbols:
            ledger, closing = ledgers[symbol], current[symbol]["close"]
            economic = closing + ledger.position_income
            if ledger.shares:
                ledger.position_peak = max(ledger.position_peak, economic)
            reason = (
                position_exit(
                    economic,
                    ledger.entry,
                    ledger.position_peak,
                    config.stop_loss,
                    config.trailing_stop,
                )
                if candidate.is_strategy and ledger.shares
                else ""
            )
            weight = targets.get(symbol, ZERO) if targets is not None else None
            if candidate.is_strategy and status != "active":
                weight, reason = ZERO, status
            elif reason:
                weight = ZERO
            # Passive drift is reported and reduced next open; never call it a hard intraday cap.
            elif candidate.is_strategy and (
                ledger.shares * closing > nav * position_cap
                or sum((ledgers[s].shares * current[s]["close"] for s in symbols), ZERO)
                > nav * total_cap
            ):
                weight = min(
                    weight if weight is not None else Decimal(ledger.shares) * closing / nav,
                    position_cap,
                    total_cap
                    * ledger.shares
                    * closing
                    / max(
                        sum((ledgers[s].shares * current[s]["close"] for s in symbols), ZERO),
                        Decimal(1),
                    ),
                )
                reason = "exposure_reduction"
                event(
                    session,
                    symbol,
                    "passive_exposure_drift",
                    "Reduce at next open; no additional buying",
                )
            if weight is None:
                continue
            desired = max(0, int((nav * weight / closing).to_integral_value(rounding=ROUND_FLOOR)))
            delta = desired - ledger.shares
            if delta:
                side = "buy" if delta > 0 else "sell"
                ledger.pending = Order(session, side, abs(delta), reason or "rebalance")
                orders.append(
                    {
                        "decision_date": session,
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(delta),
                        "target_weight": money(weight),
                        "reason": reason or "rebalance",
                    }
                )
    return PortfolioResult(
        equity=pa.Table.from_pylist(snapshots, schema=NAV_SCHEMA),
        positions=pa.Table.from_pylist(positions, schema=POSITION_SCHEMA),
        trades=pa.Table.from_pylist(trades, schema=TRADE_SCHEMA),
        orders=pa.Table.from_pylist(orders, schema=ORDER_SCHEMA),
        events=pa.Table.from_pylist(events, schema=PORTFOLIO_EVENT_SCHEMA),
        correlations=pa.Table.from_pylist(correlations, schema=CORRELATION_SCHEMA),
    )
