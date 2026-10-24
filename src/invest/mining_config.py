"""P2 冻结研究参数；日期为 XNYS 会话，收益与覆盖门槛均为比例。"""

import math
import tomllib
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invest.backtest_config import parse_policy
from invest.strategies import Policy

FAMILIES = ("momentum", "reversal", "volatility", "volume_trend", "range_position", "price_volume")


@dataclass(frozen=True)
class CostScreenConfig:
    execution: dict[str, Path]
    initial_cash: Decimal = Decimal("5000")
    policy: Policy = Policy()
    min_return: float = 0.0
    min_excess_return: float = 0.0
    max_drawdown: float = 0.15
    min_fills: int = 2

    def __post_init__(self) -> None:
        if not self.execution or any(not isinstance(p, Path) for p in self.execution.values()):
            raise ValueError("Cost screening requires raw execution inputs")
        if (
            not self.initial_cash.is_finite()
            or self.initial_cash <= self.policy.commission * 2
            or self.initial_cash != self.initial_cash.quantize(Decimal(".000001"))
        ):
            raise ValueError("Invalid cost screening capital")
        for value in (self.min_return, self.min_excess_return, self.max_drawdown):
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Cost screening thresholds must be proportions in [0, 1]")
        if type(self.min_fills) is not int or self.min_fills < 1:
            raise ValueError("Cost screening requires a positive fill count")


@dataclass(frozen=True)
class MiningConfig:
    snapshot: Path
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    known_through: date
    families: tuple[str, ...] = FAMILIES
    windows: tuple[int, ...] = (5, 10, 20)
    candidate_budget: int = 16
    seed: int = 0
    max_depth: int = 12
    max_nodes: int = 80
    horizon: int = 5
    quantiles: int = 4
    min_sessions: int = 10
    min_coverage: float = 0.8
    min_train_ic: float = 0.02
    min_validation_ic: float = 0.02
    max_correlation: float = 0.9
    min_incremental_ic: float = 0.005
    pool_size: int = 5
    allow_exploratory: bool = False
    test_alpha: float = 0.05
    test_block_size: int = 2
    test_resamples: int = 19999
    test_family_size: int = 0
    cost_screen: CostScreenConfig | None = None

    def __post_init__(self) -> None:
        dates = (
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.test_start,
            self.test_end,
            self.known_through,
        )
        if any(type(value) is not date for value in dates):
            raise ValueError("Mining dates must be TOML dates")
        if not (
            self.train_start
            <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("Training, validation and reserved test intervals must not overlap")
        if (
            not self.families
            or len(set(self.families)) != len(self.families)
            or any(family not in FAMILIES for family in self.families)
        ):
            raise ValueError("Mining requires distinct declared factor families")
        if (
            not self.windows
            or len(self.windows) > 16
            or len(set(self.windows)) != len(self.windows)
            or any(type(window) is not int or not 2 <= window <= 2520 for window in self.windows)
        ):
            raise ValueError("Mining windows must be distinct session counts in [2, 2520]")
        for name in (
            "candidate_budget",
            "max_depth",
            "max_nodes",
            "horizon",
            "quantiles",
            "min_sessions",
            "pool_size",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.candidate_budget > 256 or self.max_depth > 32 or self.max_nodes > 256:
            raise ValueError("Search exceeds the P2 candidate or expression complexity limits")
        if self.horizon > 2520 or self.quantiles < 2 or self.min_sessions < 2:
            raise ValueError("Invalid horizon, quantile count or nonoverlapping session minimum")
        if type(self.seed) is not int or type(self.allow_exploratory) is not bool:
            raise ValueError("seed must be an integer and allow_exploratory a boolean")
        if (
            type(self.test_alpha) not in (int, float)
            or not math.isfinite(self.test_alpha)
            or not 0 < self.test_alpha <= 0.1
            or type(self.test_block_size) is not int
            or self.test_block_size < 1
            or type(self.test_resamples) is not int
            or not 999 <= self.test_resamples <= 99999
            or type(self.test_family_size) is not int
            or self.test_family_size < 0
            or (self.test_family_size and self.test_family_size < self.candidate_budget)
        ):
            raise ValueError("Invalid block test or multiple testing family configuration")
        if self.cost_screen and self.cost_screen.policy.allow_exploratory != self.allow_exploratory:
            raise ValueError("Mining and cost screening must share exploratory admission")
        for name in (
            "min_coverage",
            "min_train_ic",
            "min_validation_ic",
            "max_correlation",
            "min_incremental_ic",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be a finite proportion in [0, 1]")
        if self.min_coverage <= 0 or not 0 < self.max_correlation < 1:
            raise ValueError(
                "Coverage must be positive and correlation strictly between zero and one"
            )


def load_mining_config(path: Path) -> MiningConfig:
    return parse_mining_config(path.read_bytes(), path.parent)


def parse_mining_config(body: bytes, directory: Path) -> MiningConfig:
    values = tomllib.loads(body.decode())
    unknown = values.keys() - {field.name for field in fields(MiningConfig)}
    if unknown:
        raise ValueError(f"Unknown mining configuration fields: {sorted(unknown)}")
    if not isinstance(values.get("snapshot"), str):
        raise ValueError("snapshot must name an authoritative Parquet snapshot directory")
    values["snapshot"] = (directory / values["snapshot"]).resolve()
    for name in ("families", "windows"):
        if name in values:
            if not isinstance(values[name], list):
                raise ValueError(f"{name} must be a TOML array")
            values[name] = tuple(values[name])
    try:
        if "cost_screen" in values:
            settings = dict(values["cost_screen"])
            settings["execution"] = {
                instrument: (directory / file).resolve()
                for instrument, file in settings["execution"].items()
            }
            if "initial_cash" in settings:
                if not isinstance(settings["initial_cash"], str):
                    raise ValueError("Cost screening capital must be a decimal string")
                settings["initial_cash"] = Decimal(settings["initial_cash"])
            settings["policy"] = parse_policy(settings.get("policy", {}))
            values["cost_screen"] = CostScreenConfig(**settings)
        return MiningConfig(**values)
    except (TypeError, KeyError, AttributeError, InvalidOperation) as exc:
        raise ValueError("Missing or invalid mining configuration fields") from exc
