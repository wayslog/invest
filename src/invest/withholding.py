"""W-8BEN 美国侧税负：股票与 ETF 价差不征美国税，现金分红在入账前按预扣税率扣除。

用户为中国大陆税务居民，中美协定的股息预扣税率为 10%；未申请协定时为 30%。
实际税率以 IBKR 账单的预扣记录为准。本模块只处理美国侧，不计居住国税负。
"""

from decimal import ROUND_FLOOR, Decimal

import pyarrow as pa

from invest.market import BAR_SCHEMA, validate_bars

CHINA_TREATY_DIVIDEND_RATE = Decimal("0.10")
STATUTORY_DIVIDEND_RATE = Decimal("0.30")
_UNIT = Decimal("0.000001")


def withhold_dividends(bars: pa.Table, symbol: str, rate: Decimal) -> pa.Table:
    """返回每股净分红的执行行情副本；原始行情和元数据不改写。

    净额 = 每股税前分红 × (1 - rate)，按行情表 6 位小数向下取整，USD/股；
    券商按持仓总额计算的预扣可能与此有不超过股数 × 0.000001 USD 的差异。
    除息日、支付日、价格与拆股比例保持不变，账本和独立核账使用同一份净额。
    """
    if not isinstance(rate, Decimal) or not rate.is_finite() or not 0 <= rate < 1:
        raise ValueError("Dividend withholding rate must be a Decimal in [0, 1)")
    validate_bars(bars, symbol)
    metadata = bars.schema.metadata or {}
    if b"dividend_withholding_rate" in metadata:
        raise ValueError("Dividends are already net of withholding")
    rows = bars.to_pylist()
    for row in rows:
        row["dividend"] = (row["dividend"] * (1 - rate)).quantize(_UNIT, rounding=ROUND_FLOOR)
        if not row["dividend"]:
            row["dividend_pay_date"] = None
    table = pa.Table.from_pylist(
        rows,
        schema=BAR_SCHEMA.with_metadata(
            {
                **metadata,
                b"dividend_basis": b"net_of_us_withholding",
                b"dividend_withholding_rate": str(rate.normalize()).encode(),
                b"tax_residency_scope": b"us_side_only_w8ben",
            }
        ),
    )
    validate_bars(table, symbol)
    return table
