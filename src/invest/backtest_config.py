"""冻结因子池回测配置；路径相对 TOML，金额使用十进制字符串。"""

import tomllib
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invest.strategies import Policy


def parse_policy(settings: dict[str, object]) -> Policy:
    """研究入口共用同一策略参数解析，不接受浮点金额。"""
    values = dict(settings)
    defaults = Policy()
    for field in fields(Policy):
        if field.name in values and isinstance(getattr(defaults, field.name), Decimal):
            value = values[field.name]
            if not isinstance(value, str):
                raise ValueError("Policy financial values must be decimal strings")
            values[field.name] = Decimal(value)
    return Policy(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class BacktestConfig:
    snapshot: Path
    factor_pool: Path
    start: date
    end: date
    known_through: date
    initial_cash: Decimal
    execution: dict[str, Path]
    policy: Policy


def load_backtest_config(path: Path) -> BacktestConfig:
    values = tomllib.loads(path.read_text())
    if values.keys() - {field.name for field in fields(BacktestConfig)}:
        raise ValueError("Unknown backtest configuration fields")
    try:
        for name in ("snapshot", "factor_pool"):
            values[name] = (path.parent / values[name]).resolve()
        values["execution"] = {
            instrument: (path.parent / file).resolve()
            for instrument, file in values["execution"].items()
        }
        if not values["execution"]:
            raise ValueError("Execution inputs are required")
        values["policy"] = parse_policy(values.get("policy", {}))
        if not isinstance(values.get("initial_cash"), str):
            raise ValueError("initial_cash must be a decimal string")
        values["initial_cash"] = Decimal(values["initial_cash"])
        result = BacktestConfig(**values)
        if (
            any(
                type(value) is not date
                for value in (result.start, result.end, result.known_through)
            )
            or result.start > result.end
        ):
            raise ValueError("Invalid backtest date interval")
        if (
            not result.initial_cash.is_finite()
            or result.initial_cash <= result.policy.commission * 2
            or result.initial_cash != result.initial_cash.quantize(Decimal(".000001"))
        ):
            raise ValueError("Invalid backtest initial capital or cost stress budget")
        return result
    except (KeyError, TypeError, AttributeError, InvalidOperation) as exc:
        raise ValueError("Invalid or missing backtest configuration") from exc
