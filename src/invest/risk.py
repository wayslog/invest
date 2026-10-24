"""Shared account and position exit policy, independent of trading signals."""

from decimal import Decimal


def risk_status(
    previous: str, equity: Decimal, peak: Decimal, initial: Decimal, drawdown: Decimal
) -> str:
    if equity <= initial * Decimal("0.5"):
        return "terminated"
    if previous != "terminated" and equity <= peak * (1 - drawdown):
        return "halted"
    if previous == "active" and equity < initial * Decimal("0.8"):
        return "warning"
    return previous


def position_exit(
    economic_price: Decimal, entry: Decimal, peak: Decimal, stop: Decimal, trailing: Decimal
) -> str:
    if economic_price <= entry * (1 - stop):
        return "stop_loss"
    if economic_price <= peak * (1 - trailing):
        return "trailing_stop"
    return ""


def exit_levels(
    entry: Decimal,
    income: Decimal,
    peak: Decimal,
    stop_loss: Decimal,
    trailing_stop: Decimal,
    take_profit: Decimal,
) -> tuple[Decimal | None, Decimal | None, str]:
    """将含累计分红的经济价格阈值还原为原始美元价；零参数表示禁用。"""
    levels = []
    if stop_loss:
        levels.append((entry * (1 - stop_loss) - income, "stop_loss"))
    if trailing_stop:
        levels.append((peak * (1 - trailing_stop) - income, "trailing_stop"))
    stop, reason = max(levels, key=lambda item: item[0]) if levels else (None, "")
    profit = entry * (1 + take_profit) - income if take_profit else None
    return stop if stop is not None and stop > 0 else None, profit, reason
