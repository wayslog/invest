"""验证段 RankIC 的分块符号检验和预先固定搜索族的 Bonferroni 校正。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def corrected_ic_test(
    values: pd.Series[float],
    *,
    direction: int,
    block_size: int,
    family_size: int,
    resamples: int,
    seed: int,
) -> tuple[float, float, int]:
    from scipy.stats import permutation_test  # type: ignore[import-untyped]

    if direction not in {-1, 1} or min(block_size, family_size, resamples) < 1:
        raise ValueError("Invalid factor significance test parameters")
    samples = values.to_numpy(dtype=float) * direction
    if np.isinf(samples).any():
        raise ValueError("RankIC samples must be finite or missing")
    # 缺失会话保留在原时间网格内；不压缩时间后跨缺口拼接成新的块。
    blocks = np.asarray(
        [
            np.nansum(part)
            for start in range(0, len(samples), block_size)
            if np.isfinite(part := samples[start : start + block_size]).any()
        ]
    )
    if len(blocks) < 2 or not np.any(blocks) or np.sum(blocks) <= 0:
        return 1.0, 1.0, len(blocks)
    result = permutation_test(
        (blocks,),
        np.sum,
        permutation_type="samples",
        vectorized=True,
        alternative="greater",
        n_resamples=resamples,
        batch=256,
        rng=np.random.default_rng(abs(seed)),
    )
    pvalue = float(result.pvalue)
    return pvalue, min(1.0, pvalue * family_size), len(blocks)
