"""冻结第一轮候选上的排序对照；收益评分与风险准入分别处理。"""

from math import isfinite
from typing import Any

import pandas as pd


def rerank_candidates(
    rows: list[dict[str, Any]],
    returns: pd.DataFrame,
    *,
    score_mode: str,
    fixed_threshold: bool,
    limit: int = 5,
    min_score: float = 70.0,
    max_volatility: float = 0.60,
    max_drawdown: float = 0.30,
    max_correlation: float = 0.85,
) -> tuple[str, ...]:
    """只使用当期第一轮分值和截至当期的收益；缺失相关性不得视为低风险。"""
    if score_mode not in {"original", "return_only"} or not 1 <= limit <= 5:
        raise ValueError("Invalid funnel comparison mode")
    if (
        type(fixed_threshold) is not bool
        or not 0 < max_correlation < 1
        or not max_volatility > 0
        or not 0 < max_drawdown <= 1
        or not 0 <= min_score <= 100
    ):
        raise ValueError("Invalid funnel comparison limits")
    names = [r["instrument"] for r in rows]
    if len(names) != len(set(names)):
        raise ValueError("Funnel comparison requires unique instruments")
    ranked = []
    for row in rows:
        if not row["stage_one"]:
            continue
        columns = (
            ("score",)
            if score_mode == "original"
            else ("momentum_126_points", "momentum_252_points", "trend_points", "liquidity_points")
        )
        values = [row.get(k) for k in (*columns, "volatility", "drawdown")]
        if any(v is None or not isfinite(v) for v in values):
            continue
        score = row["score"] if score_mode == "original" else sum(row[k] for k in columns) / 0.70
        if (
            (fixed_threshold and score < min_score)
            or row["volatility"] > max_volatility
            or row["drawdown"] > max_drawdown
        ):
            continue
        ranked.append((row["instrument"], score))
    selected: list[str] = []
    for instrument, _ in sorted(ranked, key=lambda item: (-item[1], item[0])):
        if instrument not in returns.columns:
            continue
        if any(peer not in returns.columns for peer in selected):
            raise ValueError("Selected instrument lacks correlation history")
        correlations = []
        for peer in selected:
            pair = returns[[instrument, peer]].dropna()
            if len(pair) < 2 or pair[instrument].nunique() < 2 or pair[peer].nunique() < 2:
                correlations.append(float("nan"))
            else:
                correlations.append(float(pair[instrument].corr(pair[peer])))
        if any(not isfinite(corr) or abs(corr) > max_correlation for corr in correlations):
            continue
        selected.append(instrument)
        if len(selected) == limit:
            break
    return tuple(selected)
