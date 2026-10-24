"""共享的 Decimal 组合结果与表模式，不包含策略或撮合逻辑。"""

from dataclasses import dataclass

import pyarrow as pa

from invest.market import MONEY

NAV_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("cash", MONEY),
        ("market_value", MONEY),
        ("receivables", MONEY),
        ("equity", MONEY),
        ("drawdown", pa.float64()),
        ("gross_exposure", pa.float64()),
        ("status", pa.string()),
    ]
)
POSITION_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("shares", pa.int64()),
        ("market_value", MONEY),
        ("receivables", MONEY),
        ("weight", pa.float64()),
        ("risk_group", pa.string()),
    ]
)
ORDER_SCHEMA = pa.schema(
    [
        ("decision_date", pa.date32()),
        ("symbol", pa.string()),
        ("side", pa.string()),
        ("quantity", pa.int64()),
        ("target_weight", MONEY),
        ("reason", pa.string()),
    ]
)
PORTFOLIO_EVENT_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("kind", pa.string()),
        ("detail", pa.string()),
        ("amount", MONEY),
    ]
)
CORRELATION_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("symbol", pa.string()),
        ("other", pa.string()),
        ("correlation", pa.float64()),
        ("accepted", pa.bool_()),
    ]
)


@dataclass
class PortfolioResult:
    equity: pa.Table
    positions: pa.Table
    trades: pa.Table
    orders: pa.Table
    events: pa.Table
    correlations: pa.Table
