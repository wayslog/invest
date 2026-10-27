"""连续账户的半年分段和滚动年比较；不在窗口边界重置资金或风险状态。"""

from datetime import date
from decimal import Decimal
from typing import Any

import pyarrow as pa


def window_metrics(
    equity: pa.Table,
    benchmark: pa.Table,
    fills: pa.Table,
    initial_cash: Decimal,
    *,
    rolling_sessions: int = 252,
) -> pa.Table:
    """金额单位 USD；窗口首日收益使用前一会话净值，回撤也包括该起点。"""
    rows, reference = equity.to_pylist(), benchmark.to_pylist()
    dates = [row["date"] for row in rows]
    if (
        not dates
        or dates != sorted(set(dates))
        or dates != [row["date"] for row in reference]
        or initial_cash <= 0
        or rolling_sessions < 2
        or any(row["equity"] <= 0 for row in [*rows, *reference])
    ):
        raise ValueError("Window metrics require aligned positive continuous equity histories")
    groups: dict[tuple[int, int], list[int]] = {}
    for index, day in enumerate(dates):
        groups.setdefault((day.year, 1 if day.month <= 6 else 2), []).append(index)
    spans = [("half_year", indices[0], indices[-1]) for indices in groups.values()]
    spans.extend(
        ("rolling_year", end - rolling_sessions + 1, end)
        for end in range(rolling_sessions - 1, len(rows))
    )
    trades: dict[date, list[dict[str, Any]]] = {}
    for fill in fills.to_pylist():
        if fill["date"] not in set(dates):
            raise ValueError("Fill outside window equity history")
        trades.setdefault(fill["date"], []).append(fill)
    records = []
    for kind, start, end in spans:
        opening = rows[start - 1]["equity"] if start else initial_cash
        benchmark_open = reference[start - 1]["equity"] if start else initial_cash
        total = float(rows[end]["equity"] / opening - 1)
        baseline = float(reference[end]["equity"] / benchmark_open - 1)
        peak, drawdown = opening, Decimal(0)
        peak_reference, reference_drawdown = benchmark_open, Decimal(0)
        executions = []
        for index in range(start, end + 1):
            value, ref = rows[index]["equity"], reference[index]["equity"]
            peak, peak_reference = max(peak, value), max(peak_reference, ref)
            drawdown = min(drawdown, value / peak - 1)
            reference_drawdown = min(reference_drawdown, ref / peak_reference - 1)
            executions.extend(trades.get(dates[index], []))
        commission = sum((row["commission"] for row in executions), Decimal(0))
        slippage = sum(
            (abs(row["price"] - row["base_price"]) * row["quantity"] for row in executions),
            Decimal(0),
        )
        records.append(
            {
                "window_kind": kind,
                "start": dates[start],
                "end": dates[end],
                "sessions": end - start + 1,
                "opening_equity": opening,
                "closing_equity": rows[end]["equity"],
                "total_return": total,
                "benchmark_return": baseline,
                "excess_return": total - baseline,
                "max_drawdown": float(drawdown),
                "benchmark_drawdown": float(reference_drawdown),
                "commissions": commission,
                "slippage": slippage,
                "trade_count": len(executions),
                "ending_status": rows[end]["status"],
                "account_reset": False,
            }
        )
    return pa.Table.from_pylist(
        records,
        schema=pa.schema(
            [
                ("window_kind", pa.string()),
                ("start", pa.date32()),
                ("end", pa.date32()),
                ("sessions", pa.int64()),
                ("opening_equity", pa.decimal128(24, 6)),
                ("closing_equity", pa.decimal128(24, 6)),
                ("total_return", pa.float64()),
                ("benchmark_return", pa.float64()),
                ("excess_return", pa.float64()),
                ("max_drawdown", pa.float64()),
                ("benchmark_drawdown", pa.float64()),
                ("commissions", pa.decimal128(24, 6)),
                ("slippage", pa.decimal128(24, 6)),
                ("trade_count", pa.int64()),
                ("ending_status", pa.string()),
                ("account_reset", pa.bool_()),
            ]
        ),
    )
