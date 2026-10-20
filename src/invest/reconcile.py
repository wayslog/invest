"""Independent cash-flow reconciliation; does not reuse the strategy/account engine."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

import pyarrow as pa

from invest.config import PaperConfig
from invest.market import MONEY
from invest.paper import PaperResult

RECONCILIATION_SCHEMA = pa.schema(
    [
        ("account", pa.string()),
        ("date", pa.date32()),
        ("check", pa.string()),
        ("expected", MONEY),
        ("actual", MONEY),
        ("status", pa.string()),
    ],
    metadata={b"schema_version": b"invest.reconciliation.v1"},
)


def reconcile(bars: pa.Table, result: PaperResult, config: PaperConfig) -> pa.Table:
    """Reconstruct balances from raw actions and executions, then compare each day."""
    checks: list[dict[str, object]] = []
    unit = Decimal("0.000001")
    rows, snapshots = bars.to_pylist(), result.equity.to_pylist()
    if [row["date"] for row in rows] != [row["date"] for row in snapshots]:
        raise ValueError("Reconciliation requires exactly one equity row per input session")

    def check(account: str, session: date, label: str, expected: Decimal, actual: Decimal) -> None:
        expected, actual = expected.quantize(unit), actual.quantize(unit)
        checks.append(
            {
                "account": account,
                "date": session,
                "check": label,
                "expected": expected,
                "actual": actual,
                "status": "pass" if expected == actual else "error",
            }
        )

    for name, trades in [("strategy", result.trades), ("benchmark", result.benchmark_trades)]:
        cash, shares = config.initial_cash, 0
        receivables: list[tuple[date, Decimal]] = []
        executions: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for trade in trades.to_pylist():
            executions[trade["date"]].append(trade)
        if set(executions) - {row["date"] for row in rows}:
            raise ValueError("Trade falls outside observed sessions")
        previous: date | None = None
        for row, snapshot in zip(rows, snapshots, strict=True):
            session = row["date"]
            shares *= row["split_ratio"]
            if shares and row["dividend"]:
                receivables.append(
                    (row["dividend_pay_date"], (shares * row["dividend"]).quantize(unit))
                )
            cash += sum(
                (amount for payment, amount in receivables if payment <= session), Decimal(0)
            )
            receivables = [
                (payment, amount) for payment, amount in receivables if payment > session
            ]
            check(
                name,
                session,
                "at_most_one_fill",
                Decimal(1),
                Decimal(len(executions[session]) <= 1),
            )
            for trade in executions[session]:
                quantity = trade["quantity"]
                valid = (
                    trade["symbol"] == config.symbol
                    and quantity > 0
                    and trade["side"] in {"buy", "sell"}
                    and trade["decision_date"] == previous
                )
                check(name, session, "order_timing_and_identity", Decimal(1), Decimal(valid))
                direction = 1 if trade["side"] == "buy" else -1
                expected_price = (
                    row["open"] * (1 + direction * config.slippage_bps / 10000)
                ).quantize(unit)
                check(name, session, "fill_price", expected_price, trade["price"])
                check(name, session, "commission", config.commission, trade["commission"])
                cash = (
                    cash - direction * quantity * trade["price"] - trade["commission"]
                ).quantize(unit)
                shares += direction * quantity
                check(name, session, "trade_cash_after", cash, trade["cash_after"])
                check(name, session, "long_only", Decimal(1), Decimal(shares >= 0))
            market_value = (shares * row["close"]).quantize(unit)
            outstanding = sum((amount for _, amount in receivables), Decimal(0))
            equity = (cash + market_value + outstanding).quantize(unit)
            if name == "strategy":
                for field, expected in [
                    ("cash", cash),
                    ("shares", Decimal(shares)),
                    ("market_value", market_value),
                    ("receivables", outstanding),
                    ("equity", equity),
                ]:
                    check(name, session, field, expected, Decimal(snapshot[field]))
            else:
                check(name, session, "equity", equity, snapshot["benchmark_equity"])
            previous = session
    return pa.Table.from_pylist(checks, schema=RECONCILIATION_SCHEMA)
