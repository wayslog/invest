"""排序分数、风险过滤、绝对门槛及相关性必须独立生效。"""

import pandas as pd
import pytest

from invest.funnel_variants import rerank_candidates


def test_factor_score_and_threshold_are_separate_from_risk_gate() -> None:
    rows = [
        {
            "instrument": "A",
            "stage_one": True,
            "score": 75.0,
            "momentum_126_points": 5.0,
            "momentum_252_points": 3.0,
            "trend_points": 2.0,
            "liquidity_points": 2.0,
            "volatility": 0.2,
            "drawdown": 0.1,
        },
        {
            "instrument": "B",
            "stage_one": True,
            "score": 60.0,
            "momentum_126_points": 23.0,
            "momentum_252_points": 18.0,
            "trend_points": 13.0,
            "liquidity_points": 8.0,
            "volatility": 0.3,
            "drawdown": 0.2,
        },
        {
            "instrument": "C",
            "stage_one": True,
            "score": 90.0,
            "momentum_126_points": 24.0,
            "momentum_252_points": 19.0,
            "trend_points": 14.0,
            "liquidity_points": 9.0,
            "volatility": 0.7,
            "drawdown": 0.2,
        },
    ]
    prices = pd.DataFrame(
        {"A": [0.0, 1.0, -1.0, 0.0], "B": [-1.0, 0.0, 0.0, 1.0], "C": [1.0, 0.0, 1.0, 0.0]}
    )
    assert rerank_candidates(rows, prices, score_mode="original", fixed_threshold=True) == ("A",)
    assert rerank_candidates(rows, prices, score_mode="original", fixed_threshold=False) == (
        "A",
        "B",
    )
    assert rerank_candidates(rows, prices, score_mode="return_only", fixed_threshold=True) == ("B",)
    assert rerank_candidates(rows, prices, score_mode="return_only", fixed_threshold=False) == (
        "B",
        "A",
    )
    prices["B"] = prices["A"]
    assert rerank_candidates(rows, prices, score_mode="original", fixed_threshold=False) == ("A",)
    prices["B"] = 0.0
    assert rerank_candidates(rows, prices, score_mode="original", fixed_threshold=False) == ("A",)
    with pytest.raises(ValueError, match="unique"):
        rerank_candidates([rows[0], rows[0]], prices, score_mode="original", fixed_threshold=True)
