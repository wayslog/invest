"""Independent reconstruction of shared cash, holdings and profit attribution."""

from collections import defaultdict
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import pyarrow as pa

from invest.market import MONEY
from invest.portfolio_types import PortfolioResult
from invest.quality import regular_sessions
from invest.reconcile import RECONCILIATION_SCHEMA
from invest.strategies import Policy
from invest.study_config import StudyConfig

ATTRIBUTION_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("shares", pa.int64()),
        ("realized_pnl", MONEY),
        ("unrealized_pnl", MONEY),
        ("dividend_income", MONEY),
        ("total_pnl", MONEY),
        ("cost_basis", MONEY),
        ("fees", MONEY),
    ]
)
CLOSED_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("quantity", pa.int64()),
        ("realized_pnl", MONEY),
    ]
)
ROUND_TRIP_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("opened_on", pa.date32()),
        ("symbol", pa.string()),
        ("realized_pnl", MONEY),
        ("dividend_income", MONEY),
        ("fees", MONEY),
        ("risk_budget", MONEY),
        ("r_multiple", pa.float64()),
        ("outcome", pa.string()),
    ]
)


def audit_portfolio(
    inputs: dict[str, pa.Table],
    result: PortfolioResult,
    config: StudyConfig,
    *,
    cost_multiplier: int = 1,
    gap_bps: int = 0,
) -> tuple[pa.Table, pa.Table, pa.Table]:
    return _reconstruct(
        inputs,
        result,
        config.initial_cash,
        config.commission * cost_multiplier,
        config.slippage_bps * cost_multiplier,
        gap_bps=gap_bps,
    )


def audit_backtest(
    inputs: dict[str, pa.Table],
    result: PortfolioResult,
    policy: Policy,
    initial_cash: Decimal,
    *,
    availability: pa.Table | None = None,
) -> tuple[pa.Table, pa.Table, pa.Table]:
    """从原始企业行动和成交独立重建，不调用 Account 或策略决策。"""
    return _reconstruct(
        inputs,
        result,
        initial_cash,
        policy.commission,
        policy.slippage_bps,
        policy=policy,
        availability=availability,
    )


def _reconstruct(
    inputs: dict[str, pa.Table],
    result: PortfolioResult,
    initial_cash: Decimal,
    commission: Decimal,
    slippage_bps: Decimal,
    *,
    gap_bps: int = 0,
    policy: Policy | None = None,
    availability: pa.Table | None = None,
) -> tuple[pa.Table, pa.Table, pa.Table]:
    unit, zero = Decimal(".000001"), Decimal(0)
    symbols = sorted(inputs)
    bars = {s: {r["date"]: r for r in inputs[s].to_pylist()} for s in symbols}
    all_dates = inputs[symbols[0]]["date"].to_pylist()
    closes = (
        {
            row["date"]: row["close_at"]
            for row in regular_sessions(all_dates[0], all_dates[-1]).to_pylist()
        }
        if availability is not None
        else {}
    )
    known = (
        {(row["date"], row["instrument"]): row["available_at"] for row in availability.to_pylist()}
        if availability is not None
        else {}
    )
    previous = dict(zip(all_dates[1:], all_dates[:-1], strict=True))
    nav = result.equity.to_pylist()
    dates = [r["date"] for r in nav]
    if not dates or dates != all_dates[all_dates.index(dates[0]) : all_dates.index(dates[-1]) + 1]:
        raise ValueError("Portfolio audit requires exactly one snapshot per evaluation session")
    positions = {(r["date"], r["symbol"]): r for r in result.positions.to_pylist()}
    if len(positions) != len(dates) * len(symbols) or result.positions.num_rows != len(positions):
        raise ValueError("Portfolio position rows are incomplete or duplicated")
    executions: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in result.trades.to_pylist():
        executions[trade["date"]].append(trade)
    if set(executions) - set(dates):
        raise ValueError("Execution outside evaluation range")
    intents = {
        (r["order_id"] if policy else (r["decision_date"], r["symbol"])): r
        for r in result.orders.to_pylist()
    }
    if len(intents) != result.orders.num_rows:
        raise ValueError("Multiple conflicting orders for the same symbol/session")
    cash = initial_cash
    shares = dict.fromkeys(symbols, 0)
    basis = dict.fromkeys(symbols, zero)
    realized, income, fees = (dict.fromkeys(symbols, zero) for _ in range(3))
    receivables: list[tuple[str, date, Decimal]] = []
    checks: list[dict[str, object]] = []
    attribution: list[dict[str, object]] = []
    closed: list[dict[str, object]] = []
    entry, position_income, peaks = (dict.fromkeys(symbols, zero) for _ in range(3))
    cycles: dict[str, dict[str, Any]] = {}
    seen_orders: set[str] = set()
    unsettled = zero

    def check(session: date, label: str, expected: Decimal, actual: Decimal) -> None:
        expected, actual = expected.quantize(unit), actual.quantize(unit)
        checks.append(
            {
                "account": "portfolio",
                "date": session,
                "check": label,
                "expected": expected,
                "actual": actual,
                "status": "pass" if expected == actual else "error",
            }
        )

    for snapshot in nav:
        session = snapshot["date"]
        for s in symbols:
            row = bars[s][session]
            shares[s] *= row["split_ratio"]
            entry[s] /= row["split_ratio"]
            position_income[s] /= row["split_ratio"]
            peaks[s] /= row["split_ratio"]
            entitlement = (shares[s] * row["dividend"]).quantize(unit)
            if entitlement:
                income[s] += entitlement
                receivables.append((s, row["dividend_pay_date"], entitlement))
                position_income[s] += row["dividend"]
                if s in cycles:
                    cycles[s]["dividend_income"] += entitlement
                    cycles[s]["realized_pnl"] += entitlement
        cash += sum((amount for _, payment, amount in receivables if payment <= session), zero)
        receivables = [
            (s, payment, amount) for s, payment, amount in receivables if payment > session
        ]
        if policy is None:
            sequence = [(0 if t["side"] == "sell" else 1, t["symbol"]) for t in executions[session]]
            check(
                session,
                "sell_then_buy_symbol_order",
                Decimal(1),
                Decimal(
                    sequence == sorted(sequence)
                    and len(sequence) == len(set(s for _, s in sequence))
                ),
            )
        else:
            phase_order = [
                0
                if t["phase"] == "open" and t["side"] == "sell"
                else 1
                if t["phase"] == "protective_open"
                else 2
                if t["phase"] == "open"
                else 3
                for t in executions[session]
            ]
            check(
                session,
                "execution_phase_order",
                Decimal(1),
                Decimal(phase_order == sorted(phase_order)),
            )
        volume_used = dict.fromkeys(symbols, 0)
        unsettled = zero
        for trade in executions[session]:
            s, quantity = trade["symbol"], trade["quantity"]
            if s not in shares or quantity <= 0 or trade["side"] not in {"buy", "sell"}:
                raise ValueError("Invalid portfolio execution identity/quantity")
            intent = intents.get(trade["order_id"] if policy else (previous[session], s))
            valid = (
                trade["decision_date"] == previous[session]
                and intent is not None
                and intent["symbol"] == s
                and intent["side"] == trade["side"]
                and quantity
                <= intent["quantity"]
                * (
                    1
                    if policy and intent["kind"] == "protective"
                    else bars[s][session]["split_ratio"]
                )
                and intent["decision_date"] == trade["decision_date"]
                and intent["reason"] == trade["reason"]
            )
            check(session, f"{s}:order_timing_quantity", Decimal(1), Decimal(valid))
            direction = 1 if trade["side"] == "buy" else -1
            base = bars[s][session]["open"]
            if policy:
                check(
                    session,
                    f"{s}:order_kind",
                    Decimal(1),
                    Decimal(
                        intent is not None
                        and (
                            (trade["phase"] == "open" and intent["kind"] == "market")
                            or (
                                trade["phase"] in {"protective_open", "protective_intraday"}
                                and intent["kind"] == "protective"
                            )
                        )
                    ),
                )
                check(
                    session,
                    f"{s}:unique_order_fill",
                    Decimal(1),
                    Decimal(trade["order_id"] not in seen_orders),
                )
                seen_orders.add(trade["order_id"])
                limit = int(
                    (
                        Decimal(
                            bars[s][previous[session]]["volume"] * bars[s][session]["split_ratio"]
                        )
                        * policy.participation
                    ).to_integral_value(rounding=ROUND_FLOOR)
                )
                if bars[s][session]["volume"] == 0:
                    limit = 0
                volume_used[s] += quantity
                check(
                    session,
                    f"{s}:liquidity_limit",
                    Decimal(1),
                    Decimal(volume_used[s] <= limit and trade["volume_limit"] == limit),
                )
                if trade["phase"] != "open":
                    levels = []
                    if policy.stop_loss:
                        levels.append(
                            (entry[s] * (1 - policy.stop_loss) - position_income[s], "stop_loss")
                        )
                    if policy.trailing_stop:
                        levels.append(
                            (
                                peaks[s] * (1 - policy.trailing_stop) - position_income[s],
                                "trailing_stop",
                            )
                        )
                    stop, reason = max(levels, key=lambda item: item[0]) if levels else (zero, "")
                    profit = (
                        entry[s] * (1 + policy.take_profit) - position_income[s]
                        if policy.take_profit
                        else None
                    )
                    bar = bars[s][session]
                    triggered = True
                    if stop > 0 and bar["open"] <= stop:
                        pass
                    elif profit is not None and bar["open"] >= profit:
                        reason = "take_profit"
                    elif (
                        trade["phase"] == "protective_intraday" and stop > 0 and bar["low"] <= stop
                    ):
                        base = stop
                    elif (
                        trade["phase"] == "protective_intraday"
                        and profit is not None
                        and bar["high"] >= profit
                    ):
                        base, reason = profit, "take_profit"
                    else:
                        triggered = False
                    check(
                        session,
                        f"{s}:protective_trigger",
                        Decimal(1),
                        Decimal(
                            triggered
                            and policy.exit_mode == "protective"
                            and direction == -1
                            and trade["reason"] == reason
                            and intent is not None
                            and intent["kind"] == "protective"
                        ),
                    )
                    check(
                        session,
                        f"{s}:protective_levels",
                        Decimal(1),
                        Decimal(
                            trade["stop_price"] == (stop.quantize(unit) if stop > 0 else None)
                            and trade["take_profit_price"]
                            == (profit.quantize(unit) if profit is not None else None)
                        ),
                    )
                check(session, f"{s}:base_price", base, trade["base_price"])
                if direction == 1:
                    value = sum((shares[key] * bars[key][session]["open"] for key in symbols), zero)
                    nav_open = cash + value + sum((amount for _, _, amount in receivables), zero)
                    budget = max(
                        zero,
                        min(
                            cash - unsettled,
                            nav_open * policy.allocation - value,
                            nav_open * policy.position_cap - shares[s] * bars[s][session]["open"],
                        ),
                    )
                    check(
                        session,
                        f"{s}:opening_budget",
                        Decimal(1),
                        Decimal(quantity * trade["price"] + trade["commission"] <= budget),
                    )
            expected_price = (
                base
                * (1 + Decimal(direction * gap_bps) / 10000)
                * (1 + direction * slippage_bps / 10000)
            ).quantize(unit)
            check(session, f"{s}:fill_price", expected_price, trade["price"])
            check(session, f"{s}:commission", commission, trade["commission"])
            amount = quantity * trade["price"]
            fee = trade["commission"]
            cash = (cash - direction * amount - fee).quantize(unit)
            fees[s] += fee
            if direction == 1:
                if not shares[s]:
                    cycles[s] = {
                        "opened_on": session,
                        "symbol": s,
                        "realized_pnl": zero,
                        "dividend_income": zero,
                        "fees": zero,
                        "risk_budget": zero,
                    }
                old_income = position_income[s]
                entry[s] = (shares[s] * entry[s] + amount + fee) / (shares[s] + quantity)
                position_income[s] = old_income * shares[s] / (shares[s] + quantity)
                peaks[s] = (
                    max(
                        peaks[s] - old_income + position_income[s],
                        trade["price"] + position_income[s],
                    )
                    if shares[s]
                    else trade["price"]
                )
                basis[s] += amount + fee
                cycles[s]["realized_pnl"] -= amount + fee
                if policy:
                    # R 的分母累计每次加仓时的固定止损风险；禁用固定止损时不报告 R。
                    cycles[s]["risk_budget"] += quantity * trade["price"] * policy.stop_loss
            else:
                if quantity > shares[s]:
                    raise ValueError("Audit detected a short position")
                cost = (basis[s] * quantity / shares[s]).quantize(unit)
                profit = amount - fee - cost
                basis[s] -= cost
                realized[s] += profit
                if policy is None:
                    closed.append(
                        {"date": session, "symbol": s, "quantity": quantity, "realized_pnl": profit}
                    )
                cycles[s]["realized_pnl"] += amount - fee
                if policy and policy.sale_proceeds == "next_session":
                    unsettled += max(zero, amount - fee)
            cycles[s]["fees"] += fee
            shares[s] += direction * quantity
            if not shares[s]:
                cycle = cycles.pop(s)
                if policy:
                    cycle["risk_budget"] = cycle["risk_budget"].quantize(unit)
                    net, risk = cycle["realized_pnl"], cycle["risk_budget"]
                    closed.append(
                        {
                            **cycle,
                            "date": session,
                            "r_multiple": float(net / risk) if risk else None,
                            "outcome": "win" if net > 0 else "loss" if net < 0 else "flat",
                        }
                    )
                entry[s] = position_income[s] = peaks[s] = zero
            check(session, f"{s}:cash_after", cash, trade["cash_after"])
            check(session, "cash_not_borrowed", Decimal(1), Decimal(cash >= 0))
        total_market, outstanding, total_profit = zero, zero, zero
        for s in symbols:
            value = (shares[s] * bars[s][session]["close"]).quantize(unit)
            unpaid = sum((a for symbol, _, a in receivables if symbol == s), zero)
            position = positions[session, s]
            check(session, f"{s}:shares", Decimal(shares[s]), Decimal(position["shares"]))
            check(session, f"{s}:market_value", value, position["market_value"])
            check(session, f"{s}:receivables", unpaid, position["receivables"])
            profit = realized[s] + value - basis[s] + income[s]
            attribution.append(
                {
                    "date": session,
                    "symbol": s,
                    "shares": shares[s],
                    "realized_pnl": realized[s],
                    "unrealized_pnl": value - basis[s],
                    "dividend_income": income[s],
                    "total_pnl": profit,
                    "cost_basis": basis[s],
                    "fees": fees[s],
                }
            )
            total_market += value
            outstanding += unpaid
            total_profit += profit
            # 独立按行情时点重建高点；缺少记录与明确允许探索的未知时间不可混为一谈。
            available = availability is None or (
                (session, s) in known
                and (
                    (known[session, s] is None and policy is not None and policy.allow_exploratory)
                    or (known[session, s] is not None and known[session, s] <= closes[session])
                )
            )
            if shares[s] and available:
                peaks[s] = max(peaks[s], bars[s][session]["close"] + position_income[s])
        equity = cash + total_market + outstanding
        for label, expected in [
            ("cash", cash),
            ("market_value", total_market),
            ("receivables", outstanding),
            ("equity", equity),
        ]:
            check(session, label, expected, snapshot[label])
        check(session, "profit_attribution", equity - initial_cash, total_profit)
    return (
        pa.Table.from_pylist(checks, schema=RECONCILIATION_SCHEMA),
        pa.Table.from_pylist(attribution, schema=ATTRIBUTION_SCHEMA),
        pa.Table.from_pylist(closed, schema=ROUND_TRIP_SCHEMA if policy else CLOSED_SCHEMA),
    )
