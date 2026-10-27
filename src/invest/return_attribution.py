"""用期初持仓和实际成交归因；分析浮点数不回写 Decimal 账户。"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from math import isclose, isfinite, prod
from typing import Any

import pyarrow as pa

EFFECTS = ("allocation", "selection", "trading", "cost")
DAILY_SCHEMA = pa.schema(
    [("date", pa.date32())]
    + [
        (key, pa.float64())
        for key in (
            "portfolio_return",
            "benchmark_return",
            "portfolio_weight",
            "benchmark_weight",
            *EFFECTS,
            "link_weight",
            *[f"linked_{key}" for key in EFFECTS],
        )
    ]
)


def link_effects(rows: list[dict[str, Any]]) -> pa.Table:
    """对称望远镜恒等式连接日贡献，精确加总至两条复利收益之差。"""
    if not rows or [r["date"] for r in rows] != sorted({r["date"] for r in rows}):
        raise ValueError("Attribution dates must be nonempty, unique and sorted")
    for row in rows:
        if any(not isfinite(row[k]) for k in ("portfolio_return", "benchmark_return", *EFFECTS)):
            raise ValueError("Attribution returns and effects must be finite")
        if min(row["portfolio_return"], row["benchmark_return"]) <= -1:
            raise ValueError("Attribution requires positive account equity")
        if not isclose(
            sum(row[k] for k in EFFECTS),
            row["portfolio_return"] - row["benchmark_return"],
            abs_tol=1e-10,
        ):
            raise ValueError("Daily attribution does not reconcile")
    result = []
    portfolio_prefix = benchmark_prefix = 1.0
    for index, row in enumerate(rows):
        later = rows[index + 1 :]
        weight = 0.5 * (
            portfolio_prefix * prod(1 + r["benchmark_return"] for r in later)
            + benchmark_prefix * prod(1 + r["portfolio_return"] for r in later)
        )
        result.append(
            {**row, "link_weight": weight, **{f"linked_{k}": row[k] * weight for k in EFFECTS}}
        )
        portfolio_prefix *= 1 + row["portfolio_return"]
        benchmark_prefix *= 1 + row["benchmark_return"]
    if not isclose(
        sum(r[f"linked_{k}"] for r in result for k in EFFECTS),
        portfolio_prefix - benchmark_prefix,
        abs_tol=1e-10,
    ):
        raise ValueError("Linked attribution does not reconcile")
    return pa.Table.from_pylist(result, schema=DAILY_SCHEMA)


def portfolio_attribution(
    inputs: dict[str, pa.Table],
    equity: pa.Table,
    positions: pa.Table,
    fills: pa.Table,
    benchmark_equity: pa.Table,
    benchmark_positions: pa.Table,
    benchmark_fills: pa.Table,
    initial_cash: Decimal,
    benchmark: str = "QQQ",
) -> pa.Table:
    """现金收益为零；分红按除息日计应收，拆股按生效日调整期初股数。

    配置贡献以两账户期初股票权重差乘 QQQ 含息收益计算；选股贡献比较期初
    所持股票与等额 QQQ。交易贡献保留日内进出和再配置交互，不伪称纯选股。
    成本只加回实际路径的佣金和滑点，不将其当作重新模拟的零成本策略。
    """
    if not initial_cash.is_finite() or initial_cash <= 0 or benchmark not in inputs:
        raise ValueError("Attribution requires positive capital and benchmark prices")
    bars = {}
    for symbol, table in inputs.items():
        rows = table.to_pylist()
        mapping = {r["date"]: r for r in rows}
        if len(mapping) != len(rows):
            raise ValueError("Duplicate attribution price")
        bars[symbol] = mapping
    accounts = [equity.to_pylist(), benchmark_equity.to_pylist()]
    dates = [r["date"] for r in accounts[0]]
    if not dates or dates != sorted(set(dates)) or dates != [r["date"] for r in accounts[1]]:
        raise ValueError("Attribution requires matching account sessions")
    reference_days = sorted(bars[benchmark])
    if dates != [d for d in reference_days if dates[0] <= d <= dates[-1]]:
        raise ValueError("Attribution account sessions are incomplete")
    holdings = []
    costs = []
    for table, trades in ((positions, fills), (benchmark_positions, benchmark_fills)):
        mapping = {(r["date"], r["symbol"]): r for r in table.to_pylist()}
        if len(mapping) != table.num_rows or any(d not in dates for d, _ in mapping):
            raise ValueError("Invalid attribution position sessions")
        holdings.append(mapping)
        daily: dict[date, Decimal] = defaultdict(Decimal)
        for fill in trades.to_pylist():
            if fill["date"] not in dates:
                raise ValueError("Attribution fill outside account sessions")
            charge = fill["commission"] + abs(fill["price"] - fill["base_price"]) * fill["quantity"]
            if charge < 0:
                raise ValueError("Attribution trading cost must be nonnegative")
            daily[fill["date"]] += charge
        costs.append(daily)
    output = []
    for index, day in enumerate(dates):
        rates, weights, passive, charges = [], [], [], []
        prior = dates[index - 1] if index else None
        q_return = 0.0
        if prior:
            row = bars[benchmark][day]
            q_return = float(
                row["split_ratio"]
                * (row["close"] + row["dividend"])
                / bars[benchmark][prior]["close"]
                - 1
            )
        for account_index, account in enumerate(accounts):
            previous = account[index - 1]["equity"] if index else initial_cash
            if previous <= 0 or account[index]["equity"] <= 0:
                raise ValueError("Attribution requires positive account equity")
            market, gain = Decimal(0), Decimal(0)
            if prior:
                for (position_day, symbol), position in holdings[account_index].items():
                    if position_day != prior or not position["shares"]:
                        continue
                    if symbol not in bars or prior not in bars[symbol] or day not in bars[symbol]:
                        raise ValueError("Held security lacks attribution prices")
                    if account_index == 1 and symbol != benchmark:
                        raise ValueError("Benchmark holds an unexpected security")
                    row = bars[symbol][day]
                    value = position["shares"] * bars[symbol][prior]["close"]
                    market += value
                    gain += (
                        position["shares"] * row["split_ratio"] * (row["close"] + row["dividend"])
                        - value
                    )
                if abs(market - account[index - 1]["market_value"]) > Decimal(".000001"):
                    raise ValueError("Attribution positions do not reconcile to market value")
            rates.append(float(account[index]["equity"] / previous - 1))
            weights.append(float(market / previous))
            passive.append(float(gain / previous))
            charges.append(float(costs[account_index][day] / previous))
        output.append(
            {
                "date": day,
                "portfolio_return": rates[0],
                "benchmark_return": rates[1],
                "portfolio_weight": weights[0],
                "benchmark_weight": weights[1],
                "allocation": (weights[0] - weights[1]) * q_return,
                "selection": passive[0] - weights[0] * q_return,
                "trading": rates[0]
                + charges[0]
                - passive[0]
                - (rates[1] + charges[1] - passive[1]),
                "cost": charges[1] - charges[0],
            }
        )
    return link_effects(output)


def forward_holding_return(rows: list[dict[str, Any]]) -> float:
    """下一会话开盘买入，末会话收盘计价；不含成本，分红不再投资。

    调用方须提供连续会话并核验复杂公司行动；首日除息不享有该次股息。
    返回仅用于事后因子标签，不能作为当期决策输入。
    """
    if not rows or [r["date"] for r in rows] != sorted({r["date"] for r in rows}):
        raise ValueError("Forward return requires unique sorted price rows")
    shares, income = Decimal(1), Decimal(0)
    entry = rows[0]["open"]
    if entry <= 0:
        raise ValueError("Forward entry price must be positive")
    for row in rows[1:]:
        if row["split_ratio"] <= 0 or row["close"] <= 0 or row["dividend"] < 0:
            raise ValueError("Invalid forward price or corporate action")
        shares *= row["split_ratio"]
        income += shares * row["dividend"]
    return float((shares * rows[-1]["close"] + income) / entry - 1)
