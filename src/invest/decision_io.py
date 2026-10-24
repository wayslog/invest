"""以 Parquet 保存可重复决策的账户与状态；成本锚点保留完整 Decimal 精度。"""

from dataclasses import asdict
from decimal import Decimal

import pyarrow as pa

from invest.contracts import (
    AccountSnapshot,
    Holding,
    PendingOrder,
    PositionState,
    Quote,
    StrategyState,
    research_schema,
)
from invest.market import MONEY

CONTEXT_SCHEMA = research_schema(
    "decision_contexts",
    [
        ("date", pa.date32()),
        ("account_id", pa.string()),
        ("snapshot_id", pa.string()),
        ("source", pa.string()),
        ("initial_cash", MONEY),
        ("cash", MONEY),
        ("receivables", MONEY),
        ("unsettled_cash", MONEY),
        ("operations", pa.string()),
        (
            "quotes",
            pa.list_(
                pa.struct(
                    [
                        ("instrument", pa.string()),
                        ("close", MONEY),
                        ("active", pa.bool_()),
                        ("available", pa.bool_()),
                    ]
                )
            ),
        ),
        (
            "holdings",
            pa.list_(
                pa.struct(
                    [
                        ("instrument", pa.string()),
                        ("shares", pa.int64()),
                        ("entry", pa.string()),
                        ("income", pa.string()),
                    ]
                )
            ),
        ),
        (
            "pending",
            pa.list_(
                pa.struct(
                    [
                        ("instrument", pa.string()),
                        ("side", pa.string()),
                        ("quantity", pa.int64()),
                        ("reference_price", MONEY),
                    ]
                )
            ),
        ),
        ("peak_equity", MONEY),
        ("risk_status", pa.string()),
        ("last_session", pa.date32()),
        ("last_rebalance", pa.date32()),
        (
            "positions",
            pa.list_(
                pa.struct(
                    [
                        ("instrument", pa.string()),
                        ("entered_on", pa.date32()),
                        ("peak", pa.string()),
                        ("exit_reason", pa.string()),
                    ]
                )
            ),
        ),
        ("last_exits", pa.list_(pa.struct([("instrument", pa.string()), ("date", pa.date32())]))),
    ],
)


def decision_contexts(contexts: tuple[tuple[AccountSnapshot, StrategyState], ...]) -> pa.Table:
    rows = []
    for account, state in contexts:
        row = {**asdict(account), **asdict(state), "date": account.as_of}
        row.pop("as_of")
        # 均价和经济价格高点可能是循环小数；记录 Decimal 字面值，不经过浮点或金额舍入。
        row["holdings"] = [
            {**asdict(item), "entry": str(item.entry), "income": str(item.income)}
            for item in account.holdings
        ]
        row["positions"] = [{**asdict(item), "peak": str(item.peak)} for item in state.positions]
        row["last_exits"] = [
            {"instrument": instrument, "date": day} for instrument, day in state.last_exits
        ]
        rows.append(row)
    return pa.Table.from_pylist(rows, schema=CONTEXT_SCHEMA)


def read_decision_contexts(table: pa.Table) -> tuple[tuple[AccountSnapshot, StrategyState], ...]:
    if not table.schema.equals(CONTEXT_SCHEMA, check_metadata=False):
        raise ValueError("Invalid decision context schema")
    contexts = []
    for row in table.to_pylist():
        account = AccountSnapshot(
            row["account_id"],
            row["snapshot_id"],
            row["source"],
            row["date"],
            row["initial_cash"],
            row["cash"],
            tuple(Quote(**quote) for quote in row["quotes"]),
            tuple(
                Holding(
                    **{**item, "entry": Decimal(item["entry"]), "income": Decimal(item["income"])}
                )
                for item in row["holdings"]
            ),
            tuple(PendingOrder(**order) for order in row["pending"]),
            row["receivables"],
            row["unsettled_cash"],
            row["operations"],
        )
        state = StrategyState(
            row["peak_equity"],
            row["risk_status"],
            row["last_session"],
            row["last_rebalance"],
            tuple(
                PositionState(**{**item, "peak": Decimal(item["peak"])})
                for item in row["positions"]
            ),
            tuple((item["instrument"], item["date"]) for item in row["last_exits"]),
        )
        contexts.append((account, state))
    return tuple(contexts)
