"""统一研究表到 Qlib 与 Alphalens；未来标签只用于研究评价。"""

import warnings
from dataclasses import dataclass
from decimal import localcontext
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from invest.contracts import LABEL_SCHEMA, DataSnapshot, FactorFrame, LabelFrame
from invest.quality import regular_sessions
from invest.research_data import load_snapshot


def forward_labels(snapshot: DataSnapshot, horizons: tuple[int, ...] = (1, 5)) -> LabelFrame:
    """收盘决策后下一会话开盘入场，第 H 个会话后的开盘退出，值为价格收益比例。"""
    if (
        not horizons
        or len(set(horizons)) != len(horizons)
        or any(type(h) is not int or h < 1 for h in horizons)
    ):
        raise ValueError("Label horizons must be distinct positive session counts")
    snapshot = load_snapshot(snapshot.directory, expected_id=snapshot.snapshot_id)
    calendar = snapshot.calendar.to_pylist()
    bars = {(r["date"], r["instrument"]): r for r in snapshot.bars.to_pylist()}
    rows = []
    for member in snapshot.universe.to_pylist():
        instrument = member["instrument"]
        for index, session in enumerate(calendar):
            if not member["start"] <= session["date"] <= member["end"]:
                continue
            for horizon in horizons:
                if index + 1 + horizon >= len(calendar):
                    continue
                entry, exit_ = calendar[index + 1], calendar[index + 1 + horizon]
                first, last = (
                    bars.get((entry["date"], instrument)),
                    bars.get((exit_["date"], instrument)),
                )
                if first is None or last is None:
                    continue
                with localcontext() as context:
                    context.prec = 50
                    value = float(last["open"] / first["open"] - 1)
                rows.append(
                    {
                        "date": session["date"],
                        "instrument": instrument,
                        "horizon": horizon,
                        "entry_at": entry["open_at"],
                        "exit_at": exit_["open_at"],
                        "value": value,
                    }
                )
    return LabelFrame(
        pa.Table.from_pylist(
            rows, schema=LABEL_SCHEMA.with_metadata(snapshot.metadata(LABEL_SCHEMA))
        )
    )


def _frame(table: pa.Table) -> pd.DataFrame:
    frame = cast(pd.DataFrame, table.to_pandas())
    frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
    return frame


def _same_snapshot(factors: FactorFrame, labels: LabelFrame) -> None:
    left, right = factors.table.schema.metadata or {}, labels.table.schema.metadata or {}
    if any(
        left.get(k) != right.get(k) for k in (b"snapshot_id", b"source", b"price_basis")
    ) or left.get(b"input_scope", left[b"scope"]) != right.get(b"input_scope", right[b"scope"]):
        raise ValueError("Factor and label snapshot provenance must match")


def _label_provenance(
    metadata: dict[str, Any], labels: LabelFrame, *, allow_exploratory: bool
) -> dict[str, Any]:
    values = labels.table.schema.metadata or {}
    exploratory = values[b"scope"] == b"exploratory"
    if exploratory and not allow_exploratory:
        raise ValueError("Exploratory label use requires explicit opt-in")
    return {
        **metadata,
        "scope": "exploratory" if exploratory else metadata["scope"],
        **{
            key.decode(): int(value) if key.endswith(b"_rows") else value.decode()
            for key, value in values.items()
            if key.startswith(b"label_")
        },
    }


def _admit_factors(
    factors: FactorFrame, *, allow_exploratory: bool, factor: str | None = None
) -> tuple[pd.DataFrame, int]:
    metadata = factors.table.schema.metadata or {}
    input_scope = metadata[b"scope"].decode()
    if input_scope not in {"research", "synthetic", "exploratory"}:
        raise ValueError("Unsupported factor research scope")
    if input_scope == "exploratory" and not allow_exploratory:
        raise ValueError("Exploratory factor use requires explicit opt-in")
    frame = _frame(factors.table)
    if factor is not None:
        frame = frame[frame["factor"] == factor].copy()
    unknown_count, rejected_count = 0, 0
    if not frame.empty:
        sessions = regular_sessions(frame["date"].min().date(), frame["date"].max().date())
        closes = {pd.Timestamp(r["date"]): r["close_at"] for r in sessions.to_pylist()}
        cutoff = pd.to_datetime(frame["date"].map(closes), utc=True)
        if cutoff.isna().any():
            raise ValueError("Factor dates must be XNYS trading sessions")
        # 统一在会话收盘决策；标签是否存在、期限长短都不能放宽特征的可得时间。
        unknown = frame["available_at"].isna() & frame["value"].notna()
        invalid = (frame["available_at"].gt(cutoff) | (unknown & (not allow_exploratory))) & frame[
            "value"
        ].notna()
        unknown_count, rejected_count = int(unknown.sum()), int(invalid.sum())
        frame["value"] = frame["value"].mask(invalid)
    frame.attrs["invest"] = {
        **{
            key: metadata[key.encode()].decode() for key in ("snapshot_id", "source", "price_basis")
        },
        "input_scope": input_scope,
        "scope": "exploratory" if allow_exploratory and unknown_count else input_scope,
        "timing_policy": "xnys_session_close",
        "allow_exploratory": allow_exploratory,
        "unknown_timing_rows": unknown_count,
        "timing_rejected_rows": rejected_count,
    }
    return frame, rejected_count


def qlib_dataset_frame(
    factors: FactorFrame,
    labels: LabelFrame | None = None,
    *,
    allow_exploratory: bool = False,
) -> pd.DataFrame:
    """按收盘截点准入，生成 Qlib 视图并保留来源；推断默认不含未来标签。"""
    admitted, _ = _admit_factors(factors, allow_exploratory=allow_exploratory)
    features = admitted.pivot(index=["date", "instrument"], columns="factor", values="value")
    groups = {"feature": features}
    if labels is not None:
        _same_snapshot(factors, labels)
        admitted.attrs["invest"] = _label_provenance(
            admitted.attrs["invest"], labels, allow_exploratory=allow_exploratory
        )
        returns = _frame(labels.table).pivot(
            index=["date", "instrument"], columns="horizon", values="value"
        )
        returns.columns = [f"return_{h}d" for h in returns.columns]
        groups["label"] = returns
    result = pd.concat(groups, axis=1).sort_index()
    result.index.names = ["datetime", "instrument"]
    result.columns.names = ["group", "field"]
    # pandas 将这些 JSON 元数据写入 Parquet；保留依据，但不混入模型特征列。
    result.attrs["invest"] = admitted.attrs["invest"].copy()
    return result


@dataclass(frozen=True)
class FactorDiagnostics:
    clean: pd.DataFrame
    rank_ic: pd.DataFrame
    input_rows: int
    retained_rows: int
    timing_rejected_rows: int
    snapshot_id: str
    scope: str
    source: str
    price_basis: str

    @property
    def loss_fraction(self) -> float:
        return 1 - self.retained_rows / self.input_rows


def diagnose_factor(
    factors: FactorFrame,
    labels: LabelFrame,
    factor: str,
    *,
    quantiles: int = 5,
    max_loss: float = 0.35,
    allow_exploratory: bool = False,
) -> FactorDiagnostics:
    """使用同一收盘截点准入，记录探索范围及包括时点拒绝在内的全部丢样。"""
    from alphalens.performance import factor_information_coefficient
    from alphalens.utils import get_clean_factor

    _same_snapshot(factors, labels)
    if type(quantiles) is not int or quantiles < 2 or not 0 <= max_loss < 1:
        raise ValueError("quantiles must be >= 2 and max_loss must be in [0, 1)")
    admitted, rejected = _admit_factors(factors, allow_exploratory=allow_exploratory, factor=factor)
    admitted.attrs["invest"] = _label_provenance(
        admitted.attrs["invest"], labels, allow_exploratory=allow_exploratory
    )
    selected = admitted.set_index(["date", "instrument"])
    if selected.empty or labels.table.num_rows == 0:
        raise ValueError("Factor and forward labels must be nonempty")
    label_data = _frame(labels.table)
    forward = label_data.pivot(index=["date", "instrument"], columns="horizon", values="value")
    forward.columns = [f"{h}D" for h in forward.columns]
    values = selected["value"].copy()
    values.index.names = forward.index.names = ["date", "asset"]
    # max_loss 以原始因子行数计，包含预热、未知时点、末端无标签和分组丢样。
    clean = cast(
        pd.DataFrame, get_clean_factor(values, forward, quantiles=quantiles, max_loss=max_loss)
    )
    if clean.empty:
        raise ValueError("No usable factor observations remain")
    rank_ic = cast(pd.DataFrame, factor_information_coefficient(clean))
    metadata = admitted.attrs["invest"]
    clean.attrs["invest"] = metadata.copy()
    rank_ic.attrs["invest"] = metadata.copy()
    return FactorDiagnostics(
        clean,
        rank_ic,
        len(selected),
        len(clean),
        rejected,
        metadata["snapshot_id"],
        metadata["scope"],
        metadata["source"],
        metadata["price_basis"],
    )


def describe_factor(result: FactorDiagnostics) -> dict[str, pd.DataFrame]:
    """Alphalens 分组价格收益和换手诊断；滞后一步固定为相邻 XNYS 会话。"""
    from alphalens.performance import (
        factor_rank_autocorrelation,
        mean_return_by_quantile,
        quantile_turnover,
    )

    clean = result.clean
    observed = clean.index.get_level_values("date")
    sessions = regular_sessions(observed.min().date(), observed.max().date())
    dates = pd.DatetimeIndex(sessions["date"].to_pylist())
    holidays = pd.bdate_range(dates.min(), dates.max()).difference(dates)
    dates = pd.DatetimeIndex(dates, freq=pd.offsets.CustomBusinessDay(holidays=holidays.to_list()))
    # 补齐缺失会话，避免 Alphalens 把两个不相邻的观测日当作相邻交易日。
    grid = pd.MultiIndex.from_product(
        [dates, clean.index.get_level_values("asset").unique()], names=["date", "asset"]
    )
    padded = clean.reindex(grid)
    returns, errors = mean_return_by_quantile(clean, by_date=True, demeaned=False)
    turnover = pd.concat(
        [
            quantile_turnover(padded["factor_quantile"], int(quantile), period=1)
            for quantile in sorted(clean["factor_quantile"].unique())
        ],
        axis=1,
    )
    # pandas 在只有一个共同标的的相邻横截面上会产生无定义相关系数。
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.filterwarnings(
            "ignore", message="Degrees of freedom <= 0 for slice", category=RuntimeWarning
        )
        autocorrelation = factor_rank_autocorrelation(padded, period=1).to_frame("value")
    outputs = {
        "quantile_return": returns,
        "quantile_return_error": errors,
        "turnover": turnover,
        "rank_autocorrelation": autocorrelation,
    }
    for frame in outputs.values():
        frame.attrs["invest"] = clean.attrs["invest"].copy()
    return outputs
