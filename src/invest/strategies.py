"""Close-only, point-in-time strategy targets and correlation screening."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import numpy as np

from invest.study_config import StudyConfig

History = dict[str, list[Decimal]]


class Signal(Protocol):
    def rank(self, history: History, lookback: int) -> list[str]: ...


class TrendSignal:
    def rank(self, history: History, lookback: int) -> list[str]:
        return sorted(
            symbol
            for symbol, values in history.items()
            if len(values) >= lookback and values[-1] > sum(values[-lookback:]) / lookback
        )


class RotationSignal:
    def rank(self, history: History, lookback: int) -> list[str]:
        scores = {
            symbol: values[-1] / values[-lookback - 1] - 1
            for symbol, values in history.items()
            if len(values) > lookback
        }
        return sorted(
            (symbol for symbol in scores if scores[symbol] > 0),
            key=lambda symbol: (-scores[symbol], symbol),
        )


@dataclass(frozen=True)
class Candidate:
    kind: str
    lookback: int = 0

    def __post_init__(self) -> None:
        if self.kind not in {"trend", "rotation", "equal_weight", "buy_hold", "market", "cash"}:
            raise ValueError("Unknown strategy")
        if self.kind in {"trend", "rotation"} and self.lookback < 2:
            raise ValueError("Candidate lookback must be >= 2")

    @property
    def name(self) -> str:
        return f"{self.kind}-{self.lookback}" if self.lookback else self.kind

    @property
    def is_strategy(self) -> bool:
        return self.kind in {"trend", "rotation"}


def candidates(config: StudyConfig) -> list[Candidate]:
    return [
        Candidate(kind, window) for kind in config.candidate_kinds for window in config.lookbacks
    ]


def correlation(left: list[Decimal], right: list[Decimal], window: int) -> float | None:
    if min(len(left), len(right)) <= window:
        return None
    a, b = (
        np.asarray(left[-window - 1 :], dtype=float),
        np.asarray(right[-window - 1 :], dtype=float),
    )
    a, b = a[1:] / a[:-1] - 1, b[1:] / b[:-1] - 1
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def target_weights(
    candidate: Candidate, history: History, config: StudyConfig
) -> tuple[dict[str, Decimal], list[dict[str, object]]]:
    if candidate.kind == "cash":
        return {}, []
    if candidate.kind == "market":
        if "SPY" not in history:
            raise ValueError("The declared market benchmark requires SPY")
        return {"SPY": Decimal(1)}, []
    if not candidate.is_strategy:
        return {symbol: config.allocation / len(history) for symbol in sorted(history)}, []
    signal: Signal = TrendSignal() if candidate.kind == "trend" else RotationSignal()
    ranked = signal.rank(history, candidate.lookback)
    selected: list[str] = []
    checks: list[dict[str, object]] = []
    for symbol in ranked:
        allowed = True
        for other in selected:
            rho = correlation(history[symbol], history[other], config.correlation_window)
            accepted = rho is not None and rho <= config.correlation_limit
            checks.append(
                {"symbol": symbol, "other": other, "correlation": rho, "accepted": accepted}
            )
            allowed = allowed and accepted
        if allowed:
            selected.append(symbol)
        if candidate.kind == "rotation" and len(selected) >= config.rotation_count:
            break
    weight = min(config.position_cap, config.allocation / len(selected)) if selected else Decimal(0)
    return {symbol: weight for symbol in selected}, checks
