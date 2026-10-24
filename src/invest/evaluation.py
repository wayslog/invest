"""Net performance and exposure metrics, with open positions left marked to market."""

from decimal import Decimal

import numpy as np
import pyarrow as pa

from invest.market import MONEY
from invest.portfolio_types import PortfolioResult

METRIC_SCHEMA = pa.schema(
    [
        ("final_equity", MONEY),
        ("total_return", pa.float64()),
        ("annualized_return", pa.float64()),
        ("max_drawdown", pa.float64()),
        ("annualized_volatility", pa.float64()),
        ("sharpe_zero_rf", pa.float64()),
        ("max_underwater_sessions", pa.int64()),
        ("unrecovered_at_end", pa.bool_()),
        ("two_way_turnover", pa.float64()),
        ("average_exposure", pa.float64()),
        ("max_exposure", pa.float64()),
        ("trade_count", pa.int64()),
        ("commissions", MONEY),
        ("ending_receivables", MONEY),
        ("top3_positive_realized_share", pa.float64()),
        ("status", pa.string()),
    ]
)
PERIOD_SCHEMA = pa.schema(
    [
        ("year", pa.int64()),
        ("total_return", pa.float64()),
        ("market_return", pa.float64()),
        ("market_regime", pa.string()),
        ("observations", pa.int64()),
    ]
)


def evaluate(result: PortfolioResult, initial_cash: Decimal, closed: pa.Table) -> pa.Table:
    equity = np.array(result.equity["equity"].to_pylist(), dtype=float)
    series = np.r_[float(initial_cash), equity]
    returns = series[1:] / series[:-1] - 1
    peaks = np.maximum.accumulate(series)
    drawdown = series / peaks - 1
    underwater = longest = 0
    for value in drawdown[1:]:
        underwater = underwater + 1 if value < 0 else 0
        longest = max(longest, underwater)
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    positive = sorted(
        (float(value) for value in closed["realized_pnl"].to_pylist() if value > 0), reverse=True
    )
    final = result.equity.to_pylist()[-1]
    gross = sum(float(t["quantity"] * t["price"]) for t in result.trades.to_pylist())
    exposure = result.equity["gross_exposure"].to_pylist()
    row = {
        "final_equity": final["equity"],
        "total_return": float(series[-1] / series[0] - 1),
        "annualized_return": float((series[-1] / series[0]) ** (252 / len(equity)) - 1),
        "max_drawdown": float(drawdown.min()),
        "annualized_volatility": volatility * np.sqrt(252),
        "sharpe_zero_rf": float(returns.mean() / volatility * np.sqrt(252))
        if volatility > 0
        else None,
        "max_underwater_sessions": longest,
        "unrecovered_at_end": underwater > 0,
        "two_way_turnover": gross / float(equity.mean()),
        "average_exposure": float(np.mean(exposure)),
        "max_exposure": max(exposure),
        "trade_count": result.trades.num_rows,
        "commissions": sum(result.trades["commission"].to_pylist(), Decimal(0)),
        "ending_receivables": final["receivables"],
        "top3_positive_realized_share": sum(positive[:3]) / sum(positive) if positive else None,
        "status": final["status"],
    }
    return pa.Table.from_pylist([row], schema=METRIC_SCHEMA)


def yearly(result: PortfolioResult, market: PortfolioResult, initial: Decimal) -> pa.Table:
    rows, benchmarks = result.equity.to_pylist(), market.equity.to_pylist()
    if [r["date"] for r in rows] != [r["date"] for r in benchmarks]:
        raise ValueError("Yearly market comparison requires matching sessions")
    output = []
    previous, prior_market = initial, initial
    years = sorted({r["date"].year for r in rows})
    for year in years:
        indices = [i for i, r in enumerate(rows) if r["date"].year == year]
        last = indices[-1]
        gain, market_gain = (
            float(rows[last]["equity"] / previous - 1),
            float(benchmarks[last]["equity"] / prior_market - 1),
        )
        output.append(
            {
                "year": year,
                "total_return": gain,
                "market_return": market_gain,
                "market_regime": "up" if market_gain > 0 else "down_or_flat",
                "observations": len(indices),
            }
        )
        previous, prior_market = rows[last]["equity"], benchmarks[last]["equity"]
    return pa.Table.from_pylist(output, schema=PERIOD_SCHEMA)
