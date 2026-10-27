"""分段结果必须延续前一窗口净值与风险状态，成本使用实际成交。"""

from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest

from invest.rolling_validation import window_metrics


def test_half_year_uses_prior_equity_and_never_resets_halted_state() -> None:
    days = [date(2024, 6, 28), date(2024, 7, 1), date(2024, 7, 2)]
    equity = pa.Table.from_pylist(
        [
            {"date": day, "equity": Decimal(value), "status": status}
            for day, value, status in zip(
                days, ("120", "90", "90"), ("active", "halted", "halted"), strict=True
            )
        ]
    )
    benchmark = pa.Table.from_pylist(
        [
            {"date": day, "equity": Decimal(value)}
            for day, value in zip(days, ("110", "100", "105"), strict=True)
        ]
    )
    fills = pa.Table.from_pylist(
        [
            {
                "date": days[1],
                "commission": Decimal("1"),
                "price": Decimal("9"),
                "base_price": Decimal("10"),
                "quantity": 2,
            }
        ]
    )
    result = window_metrics(equity, benchmark, fills, Decimal(100), rolling_sessions=2).to_pylist()
    second = next(
        row for row in result if row["window_kind"] == "half_year" and row["start"] == days[1]
    )
    assert second["opening_equity"] == Decimal(120)
    assert second["total_return"] == -0.25 and second["max_drawdown"] == -0.25
    assert second["commissions"] == 1 and second["slippage"] == 2
    assert second["ending_status"] == "halted" and not second["account_reset"]


def test_window_rejects_misaligned_benchmark() -> None:
    equity = pa.Table.from_pylist(
        [{"date": date(2024, 1, 2), "equity": Decimal(100), "status": "active"}]
    )
    reference = pa.Table.from_pylist([{"date": date(2024, 1, 3), "equity": Decimal(100)}])
    with pytest.raises(ValueError, match="aligned"):
        window_metrics(equity, reference, pa.table({}), Decimal(100))
