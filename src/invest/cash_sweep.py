"""离线研究用的现金承接：ETF 与个股使用同一账户及交收时序。"""

from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pyarrow as pa

from invest.contracts import AccountSnapshot, DecisionPlan, SignalFrame, StrategyState
from invest.research_data import identity
from invest.risk import exit_levels
from invest.strategies import Policy, decide
from invest.weekly_selection import WeeklySelection


def cash_sweep_plan(
    signals: SignalFrame,
    account: AccountSnapshot,
    state: StrategyState,
    policy: Policy,
    selection: WeeklySelection,
    *,
    instrument: str = "QQQ",
    risk_caps: dict[str, Decimal] | None = None,
    atr_stops: dict[str, Decimal] | None = None,
) -> DecisionPlan:
    """个股先规划，ETF 只承接余额；卖出资金仍须等实际交收后才能使用。"""
    quotes = {q.instrument: q for q in account.quotes}
    holdings = {h.instrument: h for h in account.holdings}
    anchors = {p.instrument: p for p in state.positions}
    if instrument not in quotes or instrument in selection.candidates:
        raise ValueError("Cash sweep instrument must be quoted and outside the stock selection")
    if any(p.instrument == instrument for p in account.pending):
        raise ValueError("Cash sweep cannot plan over a pending sweep order")
    quote, holding = quotes[instrument], holdings.get(instrument)
    if not quote.available:
        raise ValueError("Cash sweep requires an available benchmark price")
    if (holding is None) != (instrument not in anchors):
        raise ValueError("Cash sweep position state does not match its holding")
    shares = holding.shares if holding else 0
    virtual_cash = account.cash + shares * quote.close
    stock_account = replace(
        account,
        cash=virtual_cash,
        quotes=tuple(q for q in account.quotes if q.instrument != instrument),
        holdings=tuple(h for h in account.holdings if h.instrument != instrument),
    )
    stock_state = replace(
        state,
        positions=tuple(p for p in state.positions if p.instrument != instrument),
        last_exits=tuple((key, day) for key, day in state.last_exits if key != instrument),
    )
    stock_signals = SignalFrame(
        signals.table.filter(
            pa.array(
                [s != instrument for s in signals.table["instrument"].to_pylist()], type=pa.bool_()
            )
        )
    )
    plan = decide(stock_signals, stock_account, stock_state, policy, selection=selection)
    actions = plan.actions.to_pylist()
    if not actions:
        raise ValueError("Cash sweep requires stock or reference quotes")
    if holding:
        anchor = anchors[instrument]
        restored = replace(anchor, peak=max(anchor.peak, quote.close + holding.income))
        plan = replace(plan, state=replace(plan.state, positions=(*plan.state.positions, restored)))

    nav = (
        virtual_cash
        + account.receivables
        + sum(
            (
                h.shares * quotes[h.instrument].close
                for h in account.holdings
                if h.instrument != instrument
            ),
            Decimal(0),
        )
    )
    if risk_caps is not None:
        for row in actions:
            if row["action"] not in {"BUY", "ADD"}:
                continue
            key = row["instrument"]
            cap = risk_caps.get(key)
            if cap is None or not cap.is_finite() or not 0 <= cap <= policy.position_cap:
                raise ValueError("Volatility budget requires a valid point-in-time stock cap")
            current = row["current_quantity"]
            target = int(
                (nav * cap / row["reference_price"]).to_integral_value(rounding=ROUND_FLOOR)
            )
            quantity = min(row["quantity"], max(0, target - current))
            if quantity == row["quantity"]:
                continue
            desired = current + quantity
            row.update(
                quantity=quantity,
                target_quantity=desired,
                target_weight=(desired * row["reference_price"] / nav).quantize(Decimal(".000001")),
                action=("ADD" if current else "BUY")
                if quantity
                else ("HOLD" if current else "WAIT"),
                reason="volatility_budget",
            )
            if quantity:
                stock = holdings.get(key)
                entry = (
                    (current * stock.entry if stock else Decimal(0))
                    + quantity * row["reference_price"] * (1 + policy.slippage_bps / 10000)
                    + policy.commission
                ) / desired
                income = stock.income * current / desired if stock else Decimal(0)
                peak = max(entry, anchors[key].peak) if current else entry
                stop, profit, _ = exit_levels(
                    entry, income, peak, policy.stop_loss, policy.trailing_stop, policy.take_profit
                )
                row["stop_price"] = stop.quantize(Decimal(".000001")) if stop is not None else None
                row["take_profit_price"] = (
                    profit.quantize(Decimal(".000001")) if profit is not None else None
                )
            elif not current:
                row["stop_price"] = None
                row["take_profit_price"] = None
            row["action_id"] = identity(
                {"parent": row["action_id"], "risk_cap": str(cap), "quantity": quantity}
            )
    if atr_stops is not None:
        for row in actions:
            current = row["current_quantity"]
            increasing = row["action"] in {"BUY", "ADD"}
            if not current and not increasing:
                continue
            key = row["instrument"]
            distance = atr_stops.get(key)
            if distance is None or not distance.is_finite() or distance <= 0:
                raise ValueError("ATR stop requires a point-in-time risk distance")
            stock = holdings.get(key)
            if increasing:
                desired = row["target_quantity"]
                entry = (
                    (current * stock.entry if stock else Decimal(0))
                    + row["quantity"] * row["reference_price"] * (1 + policy.slippage_bps / 10000)
                    + policy.commission
                ) / desired
                income = stock.income * current / desired if stock else Decimal(0)
            else:
                assert stock is not None
                entry, income = stock.entry, stock.income
            atr_stop = entry - distance - income
            if atr_stop > 0 and (row["stop_price"] is None or atr_stop > row["stop_price"]):
                row["stop_price"] = atr_stop.quantize(Decimal(".000001"))
                row["action_id"] = identity(
                    {"parent": row["action_id"], "atr_distance": str(distance)}
                )
    free_cash = max(Decimal(0), account.cash - account.unsettled_cash)
    stock_buys = sum(
        (
            row["quantity"] * row["reference_price"] * (1 + policy.slippage_bps / 10000)
            + policy.commission
            for row in actions
            if row["action"] in {"BUY", "ADD"}
        ),
        Decimal(0),
    )
    unpriced = any(not quotes[h.instrument].available for h in account.holdings)
    quantity, side, reason = 0, "HOLD" if shares else "WAIT", "cash_sweep_idle"
    if account.operations == "active" and not unpriced:
        if shares and (plan.state.risk_status != "active" or not quote.active):
            quantity, side = shares, "SELL"
            reason = (
                plan.state.risk_status if plan.state.risk_status != "active" else "universe_exit"
            )
        elif plan.state.risk_status == "active" and quote.active:
            if stock_buys > account.cash and shares:
                price = quote.close * (1 - policy.slippage_bps / 10000)
                needed = (stock_buys - account.cash + policy.commission) / price
                quantity = min(shares, int(needed.to_integral_value(rounding=ROUND_CEILING)))
                side = "SELL" if quantity == shares else "TRIM"
                reason = "cash_sweep_release"
            elif stock_buys <= free_cash:
                price = quote.close * (1 + policy.slippage_bps / 10000)
                quantity = max(
                    0,
                    int(
                        ((free_cash - stock_buys - policy.commission) / price).to_integral_value(
                            rounding=ROUND_FLOOR
                        )
                    ),
                )
                if quantity:
                    side = "ADD" if shares else "BUY"
                    reason = "cash_sweep_invest"
    desired = shares + quantity if side in {"BUY", "ADD"} else shares - quantity
    row = {
        **actions[0],
        "instrument": instrument,
        "action": side,
        "current_quantity": shares,
        "target_quantity": desired,
        "quantity": quantity,
        "reference_price": quote.close,
        "target_weight": (desired * quote.close / nav).quantize(Decimal(".000001")),
        "stop_price": None,
        "take_profit_price": None,
        "score": None,
        "reason": reason,
        "exit_reason": reason if side == "SELL" else "",
        "cancel_pending": False,
        "max_holding_sessions": 0,
    }
    row["action_id"] = identity(
        {
            "kind": "cash_sweep",
            "account": account.account_id,
            "selection": selection.selection_id,
            "action": {k: str(v) for k, v in row.items() if k != "action_id"},
        }
    )
    return DecisionPlan(
        pa.Table.from_pylist([*actions, row], schema=plan.actions.schema), plan.state
    )
