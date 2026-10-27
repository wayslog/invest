"""根据截至决策收盘的原始行情和已生效拆股计算 ATR 风险距离。"""

from collections import deque
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from typing import Any


def atr_distances(
    rows: list[dict[str, Any]], *, lookback: int = 20, multiple: Decimal = Decimal(2)
) -> dict[date, Decimal]:
    """返回可在下一会话使用的原价美元距离；不使用未来行情或未来拆股。"""
    if (
        type(lookback) is not int
        or lookback < 2
        or not isinstance(multiple, Decimal)
        or not multiple.is_finite()
        or multiple <= 0
        or not rows
        or [r["date"] for r in rows] != sorted({r["date"] for r in rows})
    ):
        raise ValueError("Invalid ATR inputs")
    window: deque[Decimal] = deque(maxlen=lookback)
    factor, previous = Decimal(1), None
    output = {}
    for row in rows:
        split = row["split_ratio"]
        high, low, close = row["high"], row["low"], row["close"]
        if (
            type(split) is not int
            or split < 1
            or any(
                not isinstance(v, Decimal) or not v.is_finite() or v <= 0
                for v in (high, low, close)
            )
            or low > high
            or not low <= close <= high
        ):
            raise ValueError("Invalid ATR bar or split")
        factor *= split
        high, low, close = high * factor, low * factor, close * factor
        true_range = (
            max(high - low, abs(high - previous), abs(low - previous)) if previous else high - low
        )
        window.append(true_range)
        previous = close
        if len(window) == lookback:
            distance = multiple * sum(window, Decimal(0)) / lookback / factor
            if distance <= 0:
                raise ValueError("ATR risk distance must be positive")
            output[row["date"]] = distance.quantize(Decimal(".000001"))
    return output


def atr_position_cap(
    close: Decimal, distance: Decimal, risk_budget: Decimal, position_cap: Decimal
) -> Decimal:
    """按下一会话计划价估算损失预算；跳空及费用可能超出该预算。"""
    values = (close, distance, risk_budget, position_cap)
    if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in values):
        raise ValueError("ATR sizing requires positive finite Decimal values")
    if risk_budget > 1 or position_cap > 1:
        raise ValueError("ATR risk and position limits cannot exceed one")
    return min(position_cap, risk_budget * close / distance).quantize(
        Decimal(".000001"), rounding=ROUND_FLOOR
    )
