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
