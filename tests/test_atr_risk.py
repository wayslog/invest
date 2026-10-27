"""ATR 只使用决策日及以前的行情；拆股和跳空按真实时序处理。"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from invest.atr_risk import atr_distances, atr_position_cap

D = Decimal


def test_atr_uses_past_bars_and_adjusts_only_effective_splits() -> None:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(23)]
    rows = [
        {"date": day, "high": D(105), "low": D(95), "close": D(100), "split_ratio": 1}
        for day in days
    ]
    rows[21] = {
        "date": days[21],
        "high": D("52.5"),
        "low": D("47.5"),
        "close": D(50),
        "split_ratio": 2,
    }
    rows[22] = {
        "date": days[22],
        "high": D("52.5"),
        "low": D("47.5"),
        "close": D(50),
        "split_ratio": 1,
    }
    values = atr_distances(rows)
    assert values[days[19]] == D(20)
    assert values[days[21]] == D(10)
    assert atr_distances(rows[:21]) == {d: v for d, v in values.items() if d <= days[20]}
    rows[20] = {"date": days[20], "high": D(130), "low": D(120), "close": D(125), "split_ratio": 1}
    assert atr_distances(rows)[days[20]] == D(22)


def test_atr_budget_limits_entry_to_fixed_fraction_of_equity() -> None:
    assert atr_position_cap(D(100), D(10), D(".01"), D(".25")) == D(".1")
    assert atr_position_cap(D(100), D(2), D(".01"), D(".25")) == D(".25")
    with pytest.raises(ValueError, match="positive"):
        atr_position_cap(D(100), D(0), D(".01"), D(".25"))
