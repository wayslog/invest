"""周度候选与持仓管理分离；排名落选不等于独立技术信号失效。"""

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WeeklySelection:
    candidates: tuple[str, ...]
    mode: str
    decision_at: datetime
    selection_id: str
    rebalance: bool
    correlations: tuple[tuple[str, str, float | None], ...] = ()
    max_correlation: float = 0.85
    allow_entries: bool = True
    resize_existing: bool = True
    enforce_exposure: bool = True
    enforce_account_risk: bool = True

    def __post_init__(self) -> None:
        if (
            self.mode not in {"rank_rotation", "hold_until_exit"}
            or not self.selection_id
            or self.decision_at.utcoffset() is None
            or len(set(self.candidates)) != len(self.candidates)
            or not 0 < self.max_correlation < 1
            or any(
                type(value) is not bool
                for value in (
                    self.rebalance,
                    self.allow_entries,
                    self.resize_existing,
                    self.enforce_exposure,
                    self.enforce_account_risk,
                )
            )
        ):
            raise ValueError("Invalid weekly selection identity, time or policy")
        pairs = set()
        for left, right, value in self.correlations:
            key = tuple(sorted((left, right)))
            if (
                left == right
                or key in pairs
                or (value is not None and (not math.isfinite(value) or abs(value) > 1.000001))
            ):
                raise ValueError("Invalid or duplicate portfolio correlation")
            pairs.add(key)

    def targets(
        self, eligible: set[str], held: set[str], exiting: set[str], pending: set[str], limit: int
    ) -> tuple[list[str], dict[str, str]]:
        """在途退出仍占名额；保留旧仓后，按候选排名检查新增风险。"""
        keep = (
            sorted(held - exiting)
            if self.mode == "hold_until_exit"
            else [key for key in self.candidates if key in held and key in eligible]
        )
        remaining = max(0, limit - len(held | pending))
        selected = list(keep)
        blocked = {}
        correlations = {tuple(sorted((a, b))): value for a, b, value in self.correlations}
        for key in self.candidates:
            if key in selected or key not in eligible or key in held:
                continue
            if key in pending:
                selected.append(key)
                continue
            if remaining == 0:
                blocked[key] = "position_slots_occupied"
                continue
            peers = (held | pending | set(selected)) - {key}
            values = [correlations.get(tuple(sorted((key, other)))) for other in peers]
            if any(value is None for value in values):
                blocked[key] = "correlation_unavailable"
            elif any(abs(value) > self.max_correlation for value in values if value is not None):
                blocked[key] = "portfolio_correlation_limit"
            else:
                selected.append(key)
                remaining -= 1
        return selected, blocked
