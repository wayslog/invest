"""Explicit, versioned research parameters for the local paper account."""

import tomllib
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class PaperConfig:
    symbol: str = "DEMO"
    initial_cash: Decimal = Decimal("5000")
    lookback: int = 20
    allocation: Decimal = Decimal("0.8")
    commission: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("5")
    stop_loss: Decimal = Decimal("0.08")
    trailing_stop: Decimal = Decimal("0.12")
    account_drawdown: Decimal = Decimal("0.15")

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if type(self.lookback) is not int or self.lookback < 2:
            raise ValueError("lookback must be an integer >= 2")
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name not in {"symbol", "lookback"}:
                if not isinstance(value, Decimal) or not value.is_finite():
                    raise ValueError(f"{field.name} must be a finite decimal")
                if int(value.as_tuple().exponent) < -6:
                    raise ValueError(f"{field.name} supports at most six decimal places")
        if not Decimal("0") < self.initial_cash <= Decimal("1000000000"):
            raise ValueError("initial_cash must be positive and <= 1 billion USD")
        for name in ["allocation", "stop_loss", "trailing_stop", "account_drawdown"]:
            if not Decimal("0") < getattr(self, name) <= Decimal("1"):
                raise ValueError(f"{name} must be in (0, 1]")
        if not Decimal("0") <= self.commission < self.initial_cash:
            raise ValueError("commission must be non-negative and below initial_cash")
        if not Decimal("0") <= self.slippage_bps < Decimal("10000"):
            raise ValueError("slippage_bps must be in [0, 10000)")


def load_config(path: Path) -> PaperConfig:
    with path.open("rb") as source:
        values = tomllib.load(source)
    unknown = values.keys() - {field.name for field in fields(PaperConfig)}
    if unknown:
        raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}")
    defaults = PaperConfig()
    parsed: dict[str, object] = {}
    for field in fields(defaults):
        value = values.get(field.name, getattr(defaults, field.name))
        if field.name == "symbol":
            if not isinstance(value, str):
                raise ValueError("symbol must be a string")
            parsed[field.name] = value
        elif field.name == "lookback":
            parsed[field.name] = value
        else:
            try:
                parsed[field.name] = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError(f"{field.name} must be a decimal") from exc
    return PaperConfig(**parsed)  # type: ignore[arg-type]
