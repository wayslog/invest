"""信号驱动的共享现金回测；复用 Decimal 会计，当前决策使用同一纯函数。"""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any, cast

import pyarrow as pa

from invest.config import PaperConfig
from invest.contracts import (
    AccountSnapshot,
    Holding,
    PendingOrder,
    PositionState,
    Quote,
    SignalFrame,
    StrategyState,
    research_schema,
)
from invest.market import MONEY, validate_bars
from invest.paper import TRADE_SCHEMA, ZERO, Account, Order, money
from invest.portfolio_types import (
    CORRELATION_SCHEMA,
    NAV_SCHEMA,
    ORDER_SCHEMA,
    PORTFOLIO_EVENT_SCHEMA,
    POSITION_SCHEMA,
    PortfolioResult,
)
from invest.quality import regular_sessions
from invest.research_data import identity
from invest.risk import exit_levels
from invest.strategies import Policy, decide

FILL_SCHEMA = research_schema(
    "portfolio_fills",
    [
        *[(field.name, field.type) for field in TRADE_SCHEMA],
        ("order_id", pa.string()),
        ("phase", pa.string()),
        ("base_price", MONEY),
        ("requested_quantity", pa.int64()),
        ("volume_limit", pa.int64()),
        ("stop_price", MONEY),
        ("take_profit_price", MONEY),
        ("stop_reason", pa.string()),
    ],
)
SIM_ORDER_SCHEMA = research_schema(
    "portfolio_orders",
    [
        *[(field.name, field.type) for field in ORDER_SCHEMA],
        ("order_id", pa.string()),
        ("kind", pa.string()),
    ],
)
OUTCOME_SCHEMA = research_schema(
    "order_outcomes",
    [
        ("date", pa.date32()),
        ("order_id", pa.string()),
        ("requested", pa.int64()),
        ("filled", pa.int64()),
        ("status", pa.string()),
        ("reason", pa.string()),
    ],
)


@dataclass
class BacktestResult:
    portfolio: PortfolioResult
    actions: pa.Table
    outcomes: pa.Table
    contexts: tuple[tuple[AccountSnapshot, StrategyState], ...]
    final_account: AccountSnapshot
    final_state: StrategyState


def simulate_signals(
    inputs: dict[str, pa.Table],
    signals: SignalFrame,
    policy: Policy,
    start: date,
    end: date,
    *,
    initial_cash: Decimal = Decimal(5000),
    account_id: str = "research_account",
    universe: pa.Table | None = None,
    availability: pa.Table | None = None,
) -> BacktestResult:
    """日线开盘代理成交；单标的与多标的共用此实现，最后收盘只产生待执行计划。"""
    if not inputs:
        raise ValueError("Backtest requires at least one execution instrument")
    symbols = sorted(inputs)
    metadata = signals.table.schema.metadata or {}
    for symbol, table in inputs.items():
        validate_bars(table, symbol)
        if (table.schema.metadata or {})[b"source"] != metadata[b"source"]:
            raise ValueError("Execution and signal sources must match")
    dates = inputs[symbols[0]]["date"].to_pylist()
    if dates != regular_sessions(dates[0], dates[-1])["date"].to_pylist() or any(
        inputs[s]["date"].to_pylist() != dates for s in symbols
    ):
        raise ValueError("Execution inputs require complete identical XNYS sessions")
    if start not in dates or end not in dates or start > end or dates.index(start) < 1:
        raise ValueError("Backtest needs a preceding decision session and covered evaluation range")
    first, last = dates.index(start), dates.index(end)
    rows = {symbol: table.to_pylist() for symbol, table in inputs.items()}
    calendars = regular_sessions(dates[0], end + timedelta(days=14)).to_pylist()
    next_days = {
        left["date"]: right["date"]
        for left, right in zip(calendars[:-1], calendars[1:], strict=True)
    }
    members = universe.to_pylist() if universe is not None else []
    close_times = {item["date"]: item["close_at"] for item in calendars}
    known = (
        {
            (item["date"], item["instrument"]): item["available_at"]
            for item in availability.to_pylist()
        }
        if availability is not None
        else {}
    )
    ledgers = {symbol: Account(cash=ZERO) for symbol in symbols}
    configs = {
        symbol: PaperConfig(
            symbol=symbol,
            initial_cash=initial_cash,
            allocation=policy.allocation,
            commission=policy.commission,
            slippage_bps=policy.slippage_bps,
        )
        for symbol in symbols
    }
    cash = money(initial_cash)
    state = StrategyState(peak_equity=cash)
    unsettled: list[tuple[date, Decimal]] = []
    pending: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    actions = []
    contexts = []

    def valuation(index: int, field: str) -> tuple[Decimal, Decimal, Decimal]:
        market = money(sum((ledgers[s].shares * rows[s][index][field] for s in symbols), ZERO))
        unpaid = money(sum((amount for s in symbols for _, amount in ledgers[s].receivables), ZERO))
        return market, unpaid, money(cash + market + unpaid)

    def event(day: date, symbol: str, kind: str, detail: str) -> None:
        events.append(
            {"date": day, "symbol": symbol, "kind": kind, "detail": detail, "amount": money(ZERO)}
        )

    def fill(
        symbol: str,
        order_id: str,
        base_price: Decimal,
        phase: str = "open",
        stop: Decimal | None = None,
        profit: Decimal | None = None,
        stop_reason: str = "",
    ) -> None:
        nonlocal cash, state
        ledger = ledgers[symbol]
        assert ledger.pending is not None
        requested, side, reason = (
            ledger.pending.quantity,
            ledger.pending.side,
            ledger.pending.reason,
        )
        limit = int(
            (
                Decimal(rows[symbol][index - 1]["volume"] * rows[symbol][index]["split_ratio"])
                * policy.participation
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
        if rows[symbol][index]["volume"] == 0:
            limit = 0
        quantity = min(requested, max(0, limit - spent_volume[symbol]))
        if quantity < requested:
            event(
                day,
                symbol,
                "liquidity_reduction",
                "Previous-session volume limits fill; residual cancelled",
            )
        prior_shares, prior_cash = ledger.shares, cash
        if quantity and (
            side != "sell"
            or cash + min(quantity, ledger.shares) * base_price * (1 - policy.slippage_bps / 10000)
            >= policy.commission
        ):
            ledger.pending.quantity = quantity
            market, _, nav = valuation(index, "open")
            available = cash - sum((amount for _, amount in unsettled), ZERO)
            budget = max(
                ZERO,
                min(
                    available,
                    nav * policy.allocation - market,
                    nav * policy.position_cap - ledger.shares * rows[symbol][index]["open"],
                ),
            )
            ledger.cash = cash
            ledger.execute(day, base_price, configs[symbol], capital_budget=budget)
            cash = ledger.cash
        else:
            ledger.pending = None
        filled = sum(cast(int, trade["quantity"]) for trade in ledger.trades)
        spent_volume[symbol] += filled
        trades.extend(
            {
                **trade,
                "order_id": order_id,
                "phase": phase,
                "base_price": money(base_price),
                "requested_quantity": requested,
                "volume_limit": limit,
                "stop_price": money(stop) if stop is not None else None,
                "take_profit_price": money(profit) if profit is not None else None,
                "stop_reason": stop_reason,
            }
            for trade in ledger.trades
        )
        events.extend({**item, "symbol": symbol} for item in ledger.events)
        ledger.events.clear()
        ledger.trades.clear()
        outcomes.append(
            {
                "date": day,
                "order_id": order_id,
                "requested": requested,
                "filled": filled,
                "status": "filled" if filled == requested else "reduced" if filled else "rejected",
                "reason": "residual_cancelled" if filled != requested else reason,
            }
        )
        if filled:
            anchors = {position.instrument: position for position in state.positions}
            exits = dict(state.last_exits)
            if ledger.shares:
                anchors[symbol] = PositionState(
                    symbol,
                    anchors[symbol].entered_on if prior_shares else day,
                    ledger.position_peak,
                    anchors[symbol].exit_reason if symbol in anchors else "",
                )
            else:
                anchors.pop(symbol, None)
                exits[symbol] = day
            state = replace(
                state, positions=tuple(anchors.values()), last_exits=tuple(sorted(exits.items()))
            )
            if side == "sell" and policy.sale_proceeds == "next_session":
                unsettled.append((next_days[day], max(ZERO, cash - prior_cash)))

    def protect(gap_only: bool) -> None:
        nonlocal state
        if policy.exit_mode != "protective":
            return
        for symbol in symbols:
            ledger, bar = ledgers[symbol], rows[symbol][index]
            if not ledger.shares or symbol in protected:
                continue
            stop, profit, stop_reason = exit_levels(
                ledger.entry,
                ledger.position_income,
                ledger.position_peak,
                policy.stop_loss,
                policy.trailing_stop,
                policy.take_profit,
            )
            price, reason = None, ""
            if stop is not None and bar["open"] <= stop:
                price, reason = bar["open"], stop_reason
            elif profit is not None and bar["open"] >= profit:
                price, reason = bar["open"], "take_profit"
            elif not gap_only:
                # 同一日线内先后未知时，先处理不利的止损；不追踪当日高点抬升止损。
                if stop is not None and bar["low"] <= stop:
                    price, reason = stop, stop_reason
                elif profit is not None and bar["high"] >= profit:
                    price, reason = profit, "take_profit"
            if price is None:
                continue
            protected.add(symbol)
            phase = "protective_open" if gap_only else "protective_intraday"
            order_id = identity(
                {
                    "account": account_id,
                    "date": day.isoformat(),
                    "instrument": symbol,
                    "policy": policy.policy_id,
                    "phase": phase,
                }
            )
            orders.append(
                {
                    "decision_date": dates[index - 1],
                    "symbol": symbol,
                    "side": "sell",
                    "quantity": ledger.shares,
                    "target_weight": money(ZERO),
                    "reason": reason,
                    "order_id": order_id,
                    "kind": "protective",
                }
            )
            ledger.pending = Order(dates[index - 1], "sell", ledger.shares, reason)
            fill(symbol, order_id, price, phase, stop, profit, stop_reason)
            if ledger.shares:
                state = replace(
                    state,
                    positions=tuple(
                        replace(position, exit_reason=reason)
                        if position.instrument == symbol
                        else position
                        for position in state.positions
                    ),
                )

    for index in range(first - 1, last + 1):
        day = dates[index]
        spent_volume = dict.fromkeys(symbols, 0)
        unsettled = [(payment, amount) for payment, amount in unsettled if payment > day]
        if index >= first:
            anchors = {position.instrument: position for position in state.positions}
            for symbol in symbols:
                ledger, bar = ledgers[symbol], rows[symbol][index]
                item = next((item for item in pending if item["instrument"] == symbol), None)
                ledger.pending = (
                    Order(
                        item["date"],
                        "buy" if item["action"] in {"BUY", "ADD"} else "sell",
                        item["quantity"],
                        item["reason"],
                    )
                    if item
                    else None
                )
                ledger.cash = cash
                ledger.corporate_actions(bar)
                cash = ledger.cash
                events.extend({**item, "symbol": symbol} for item in ledger.events)
                ledger.events.clear()
                if symbol in anchors:
                    anchors[symbol] = replace(
                        anchors[symbol], peak=anchors[symbol].peak / bar["split_ratio"]
                    )
            state = replace(state, positions=tuple(anchors.values()))

            protected: set[str] = set()

            for item in (item for item in pending if item["action"] in {"SELL", "TRIM"}):
                symbol = item["instrument"]
                fill(symbol, item["action_id"], rows[symbol][index]["open"])
            protect(True)
            for item in (item for item in pending if item["action"] in {"BUY", "ADD"}):
                symbol = item["instrument"]
                if symbol in protected:
                    ledgers[symbol].pending = None
                    outcomes.append(
                        {
                            "date": day,
                            "order_id": item["action_id"],
                            "requested": item["quantity"] * rows[symbol][index]["split_ratio"],
                            "filled": 0,
                            "status": "cancelled",
                            "reason": "protective_exit",
                        }
                    )
                else:
                    fill(symbol, item["action_id"], rows[symbol][index]["open"])
            protect(False)
        market, unpaid, nav = valuation(index, "close")
        if cash < 0 or nav <= 0:
            raise ValueError("Shared portfolio cash or equity invariant failed")
        account = AccountSnapshot(
            account_id,
            metadata[b"snapshot_id"].decode(),
            metadata[b"source"].decode(),
            day,
            initial_cash,
            cash,
            tuple(
                Quote(
                    symbol,
                    rows[symbol][index]["close"],
                    not members
                    or any(
                        member["instrument"] == symbol
                        and member["start"] <= day <= member["end"]
                        and (
                            (member["available_at"] is None and policy.allow_exploratory)
                            or (
                                member["available_at"] is not None
                                and member["available_at"] <= close_times[day]
                            )
                        )
                        for member in members
                    ),
                    availability is None
                    or (
                        (known.get((day, symbol)) is None and policy.allow_exploratory)
                        or (
                            known.get((day, symbol)) is not None
                            and known[day, symbol] <= close_times[day]
                        )
                    ),
                )
                for symbol in symbols
            ),
            tuple(
                Holding(symbol, ledger.shares, ledger.entry, ledger.position_income)
                for symbol, ledger in ledgers.items()
                if ledger.shares
            ),
            receivables=unpaid,
            unsettled_cash=sum((amount for _, amount in unsettled), ZERO),
        )
        contexts.append((account, state))
        plan = decide(signals, account, state, policy)
        actions.append(plan.actions)
        prior_status = state.risk_status
        state = plan.state
        if state.risk_status != prior_status:
            event(day, "", "risk_state", f"{prior_status} -> {state.risk_status}")
        for position in state.positions:
            ledgers[position.instrument].position_peak = position.peak
        pending = [item for item in plan.actions.to_pylist() if item["quantity"]]
        orders.extend(
            {
                "decision_date": day,
                "symbol": item["instrument"],
                "side": "buy" if item["action"] in {"BUY", "ADD"} else "sell",
                "quantity": item["quantity"],
                "target_weight": item["target_weight"],
                "reason": item["reason"],
                "order_id": item["action_id"],
                "kind": "market",
            }
            for item in pending
        )
        if index >= first:
            equity.append(
                {
                    "date": day,
                    "cash": cash,
                    "market_value": market,
                    "receivables": unpaid,
                    "equity": nav,
                    "drawdown": float(nav / max(state.peak_equity, nav) - 1),
                    "gross_exposure": float(market / nav),
                    "status": state.risk_status,
                }
            )
            positions.extend(
                {
                    "date": day,
                    "symbol": symbol,
                    "shares": ledger.shares,
                    "market_value": money(ledger.shares * rows[symbol][index]["close"]),
                    "receivables": money(sum((amount for _, amount in ledger.receivables), ZERO)),
                    "weight": float(ledger.shares * rows[symbol][index]["close"] / nav),
                    "risk_group": "us_equity",
                }
                for symbol, ledger in ledgers.items()
            )
    final = replace(
        account,
        pending=tuple(
            PendingOrder(
                item["instrument"],
                "buy" if item["action"] in {"BUY", "ADD"} else "sell",
                item["quantity"],
                item["reference_price"],
            )
            for item in pending
        ),
    )
    return BacktestResult(
        PortfolioResult(
            pa.Table.from_pylist(equity, schema=NAV_SCHEMA),
            pa.Table.from_pylist(positions, schema=POSITION_SCHEMA),
            pa.Table.from_pylist(trades, schema=FILL_SCHEMA),
            pa.Table.from_pylist(orders, schema=SIM_ORDER_SCHEMA),
            pa.Table.from_pylist(events, schema=PORTFOLIO_EVENT_SCHEMA),
            pa.Table.from_pylist([], schema=CORRELATION_SCHEMA),
        ),
        pa.concat_tables(actions),
        pa.Table.from_pylist(outcomes, schema=OUTCOME_SCHEMA),
        tuple(contexts),
        final,
        state,
    )
