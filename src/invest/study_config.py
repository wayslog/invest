"""Frozen research design; all searches are enumerated before execution."""

import math
import re
import tomllib
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation

from invest.config import PaperConfig


@dataclass(frozen=True)
class StudyConfig:
    study_id: str
    symbols: tuple[str, ...]
    initial_cash: Decimal
    allocation: Decimal
    position_cap: Decimal
    commission: Decimal
    slippage_bps: Decimal
    stop_loss: Decimal
    trailing_stop: Decimal
    account_drawdown: Decimal
    lookbacks: tuple[int, ...]
    rebalance_sessions: int
    rotation_count: int
    correlation_window: int
    correlation_limit: float
    cost_multipliers: tuple[int, ...]
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    reused_start: date
    reused_end: date
    holdout_start: date
    holdout_end: date
    walk_forward_years: tuple[int, ...]
    candidate_kinds: tuple[str, ...] = ("trend", "rotation")

    def __post_init__(self) -> None:
        if (
            not self.study_id
            or len(self.symbols) < 2
            or len(set(self.symbols)) != len(self.symbols)
        ):
            raise ValueError("A study needs an identity and at least two distinct symbols")
        for symbol in self.symbols:
            if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
                raise ValueError("Invalid research symbol")
            self.paper(symbol)
        if not self.position_cap.is_finite() or not 0 < self.position_cap <= self.allocation:
            raise ValueError("Position cap must be positive and <= allocation")
        for value in [
            *self.lookbacks,
            self.rebalance_sessions,
            self.rotation_count,
            self.correlation_window,
        ]:
            if type(value) is not int or value < 1:
                raise ValueError("Research windows/counts must be positive integers")
        if not self.lookbacks or min(self.lookbacks) < 2 or self.correlation_window < 2:
            raise ValueError("Signal/correlation windows must be >= 2")
        if (
            not self.candidate_kinds
            or len(set(self.candidate_kinds)) != len(self.candidate_kinds)
            or set(self.candidate_kinds) - {"trend", "rotation"}
        ):
            raise ValueError("Candidate families must be unique trend/rotation names")
        if len(set(self.lookbacks)) != len(self.lookbacks):
            raise ValueError("Duplicate lookbacks would hide the candidate count")
        if not math.isfinite(self.correlation_limit) or not 0 <= self.correlation_limit <= 1:
            raise ValueError("Correlation limit must be finite in [0, 1]")
        if (
            not self.cost_multipliers
            or 1 not in self.cost_multipliers
            or any(type(v) is not int or v < 1 for v in self.cost_multipliers)
            or len(set(self.cost_multipliers)) != len(self.cost_multipliers)
        ):
            raise ValueError("Cost multipliers must include 1 and be unique positive integers")
        for multiplier in self.cost_multipliers:
            self.paper(self.symbols[0], multiplier)
        dates = [
            getattr(self, name)
            for name in [
                "train_start",
                "train_end",
                "validation_start",
                "validation_end",
                "reused_start",
                "reused_end",
                "holdout_start",
                "holdout_end",
            ]
        ]
        if any(type(value) is not date for value in dates) or any(
            a >= b for a, b in zip(dates[:-1], dates[1:], strict=True)
        ):
            raise ValueError("Research periods must be ordered, nonoverlapping date ranges")
        if any(
            type(y) is not int
            or y <= self.train_start.year
            or date(y, 12, 31) >= self.holdout_start
            for y in self.walk_forward_years
        ):
            raise ValueError(
                "Walk-forward years must follow training inception and precede holdout"
            )
        if tuple(sorted(set(self.walk_forward_years))) != self.walk_forward_years:
            raise ValueError("Walk-forward years must be unique and ordered")

    @property
    def warmup(self) -> int:
        return max(*self.lookbacks, self.correlation_window) + 1

    def paper(self, symbol: str, multiplier: int = 1) -> PaperConfig:
        return PaperConfig(
            symbol=symbol,
            initial_cash=self.initial_cash,
            allocation=self.allocation,
            commission=self.commission * multiplier,
            slippage_bps=self.slippage_bps * multiplier,
            stop_loss=self.stop_loss,
            trailing_stop=self.trailing_stop,
            account_drawdown=self.account_drawdown,
        )


def parse_study(body: bytes) -> StudyConfig:
    values = tomllib.loads(body.decode())
    values.setdefault("candidate_kinds", ["trend", "rotation"])
    expected = {field.name for field in fields(StudyConfig)}
    if values.keys() != expected:
        raise ValueError(f"Study fields differ: {sorted(values.keys() ^ expected)}")
    for key in [
        "initial_cash",
        "allocation",
        "position_cap",
        "commission",
        "slippage_bps",
        "stop_loss",
        "trailing_stop",
        "account_drawdown",
    ]:
        try:
            values[key] = Decimal(str(values[key]))
        except InvalidOperation as exc:
            raise ValueError(f"{key} must be a decimal") from exc
    for key in [
        "symbols",
        "lookbacks",
        "cost_multipliers",
        "walk_forward_years",
        "candidate_kinds",
    ]:
        if not isinstance(values[key], list):
            raise ValueError(f"{key} must be an array")
        values[key] = tuple(values[key])
    try:
        return StudyConfig(**values)
    except TypeError as exc:
        raise ValueError("Invalid study configuration field types") from exc
