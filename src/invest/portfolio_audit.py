"""Independent reconstruction of shared cash, holdings and profit attribution."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

import pyarrow as pa

from invest.market import MONEY
from invest.portfolio import PortfolioResult
from invest.reconcile import RECONCILIATION_SCHEMA
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


def audit_portfolio(
    inputs: dict[str, pa.Table],
    result: PortfolioResult,
    config: StudyConfig,
    *,
    cost_multiplier: int = 1,
    gap_bps: int = 0,
) -> tuple[pa.Table, pa.Table, pa.Table]:
    unit, zero = Decimal(".000001"), Decimal(0)
    symbols = sorted(inputs)
    bars = {s: {r["date"]: r for r in inputs[s].to_pylist()} for s in symbols}
    all_dates = inputs[symbols[0]]["date"].to_pylist()
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
    intents = {(r["decision_date"], r["symbol"]): r for r in result.orders.to_pylist()}
    if len(intents) != result.orders.num_rows:
        raise ValueError("Multiple conflicting orders for the same symbol/session")
    cash = config.initial_cash
    shares = dict.fromkeys(symbols, 0)
    basis = dict.fromkeys(symbols, zero)
    realized, income, fees = (dict.fromkeys(symbols, zero) for _ in range(3))
    receivables: list[tuple[str, date, Decimal]] = []
    checks: list[dict[str, object]] = []
    attribution: list[dict[str, object]] = []
    closed: list[dict[str, object]] = []

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
            entitlement = (shares[s] * row["dividend"]).quantize(unit)
            if entitlement:
                income[s] += entitlement
                receivables.append((s, row["dividend_pay_date"], entitlement))
        cash += sum((amount for _, payment, amount in receivables if payment <= session), zero)
        receivables = [
            (s, payment, amount) for s, payment, amount in receivables if payment > session
        ]
        sequence = [(0 if t["side"] == "sell" else 1, t["symbol"]) for t in executions[session]]
        check(
            session,
            "sell_then_buy_symbol_order",
            Decimal(1),
            Decimal(
                sequence == sorted(sequence) and len(sequence) == len(set(s for _, s in sequence))
            ),
        )
        for trade in executions[session]:
            s, quantity = trade["symbol"], trade["quantity"]
            if s not in shares or quantity <= 0 or trade["side"] not in {"buy", "sell"}:
                raise ValueError("Invalid portfolio execution identity/quantity")
            intent = intents.get((previous[session], s))
            valid = (
                trade["decision_date"] == previous[session]
                and intent is not None
                and intent["side"] == trade["side"]
                and quantity <= intent["quantity"] * bars[s][session]["split_ratio"]
            )
            check(session, f"{s}:order_timing_quantity", Decimal(1), Decimal(valid))
            direction = 1 if trade["side"] == "buy" else -1
            expected_price = (
                bars[s][session]["open"]
                * (1 + Decimal(direction * gap_bps) / 10000)
                * (1 + direction * config.slippage_bps * cost_multiplier / 10000)
            ).quantize(unit)
            check(session, f"{s}:fill_price", expected_price, trade["price"])
            check(
                session, f"{s}:commission", config.commission * cost_multiplier, trade["commission"]
            )
            amount = quantity * trade["price"]
            fee = trade["commission"]
            cash = (cash - direction * amount - fee).quantize(unit)
            fees[s] += fee
            if direction == 1:
                basis[s] += amount + fee
            else:
                if quantity > shares[s]:
                    raise ValueError("Audit detected a short position")
                cost = (basis[s] * quantity / shares[s]).quantize(unit)
                profit = amount - fee - cost
                basis[s] -= cost
                realized[s] += profit
                closed.append(
                    {"date": session, "symbol": s, "quantity": quantity, "realized_pnl": profit}
                )
            shares[s] += direction * quantity
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
        equity = cash + total_market + outstanding
        for label, expected in [
            ("cash", cash),
            ("market_value", total_market),
            ("receivables", outstanding),
            ("equity", equity),
        ]:
            check(session, label, expected, snapshot[label])
        check(session, "profit_attribution", equity - config.initial_cash, total_profit)
    return (
        pa.Table.from_pylist(checks, schema=RECONCILIATION_SCHEMA),
        pa.Table.from_pylist(attribution, schema=ATTRIBUTION_SCHEMA),
        pa.Table.from_pylist(closed, schema=CLOSED_SCHEMA),
    )
