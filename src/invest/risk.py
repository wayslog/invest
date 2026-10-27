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


# 本金阶梯（用户 2026-10-27 决定）：净值低于本金进入警戒，停止新增个股风险；
# 净值不高于本金一半为硬性底线，下一会话清仓并永久终止。高于本金的盈利部分不设回撤锁定。
PRINCIPAL_FLOOR = Decimal("0.5")


def principal_status(previous: str, equity: Decimal, principal: Decimal) -> str:
    """按净值相对本金（累计净入金，USD）分级；警戒可随净值回到本金以上解除，终止不可恢复。"""
    if previous not in {"active", "warning", "terminated"}:
        raise ValueError("Principal ladder accounts cannot carry a peak-drawdown halt")
    if previous == "terminated" or equity <= principal * PRINCIPAL_FLOOR:
        return "terminated"
    return "warning" if equity < principal else "active"


def liquidates(status: str, account_risk: str) -> bool:
    """本金阶梯的警戒只停止新增个股；其余非正常状态沿用清仓退出。"""
    return status != "active" and not (account_risk == "principal_ladder" and status == "warning")


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
