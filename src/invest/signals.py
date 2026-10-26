"""冻结研究因子池与收盘排名信号；不产生订单或修改账户。"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as arrow_compute
import pyarrow.parquet as pq

from invest.contracts import (
    FACTOR_SCHEMA,
    SIGNAL_SCHEMA,
    TIME,
    DataSnapshot,
    FactorFrame,
    SignalFrame,
    research_schema,
    validate_frame,
)
from invest.factor_diagnostics import qlib_dataset_frame
from invest.qlib_adapter import calculate_factors, expression_lookback
from invest.quality import regular_sessions
from invest.research_data import identity, load_snapshot

# PyArrow 的计算函数在运行时注册，静态模块没有这些属性的类型声明。
pc: Any = arrow_compute

POOL_SCHEMA = research_schema(
    "factor_pool",
    [
        ("factor", pa.string()),
        ("expression", pa.string()),
        ("direction", pa.int8()),
        ("weight", pa.float64()),
        ("trial_id", pa.int32()),
    ],
)

CONTRIBUTION_SCHEMA = research_schema(
    "factor_contributions",
    [
        ("date", pa.date32()),
        ("instrument", pa.string()),
        ("factor", pa.string()),
        ("value", pa.float64()),
        ("scaled_rank", pa.float64()),
        ("direction", pa.int8()),
        ("weight", pa.float64()),
        ("contribution", pa.float64()),
        ("admitted", pa.bool_()),
        ("available_at", TIME),
    ],
)


@dataclass(frozen=True)
class SignalEvaluation:
    signals: SignalFrame
    factors: FactorFrame
    contributions: pa.Table


@dataclass(frozen=True)
class FrozenFactorPool:
    table: pa.Table

    @property
    def metadata(self) -> dict[str, str]:
        return {
            key.decode(): value.decode()
            for key, value in (self.table.schema.metadata or {}).items()
        }

    def __post_init__(self) -> None:
        validate_frame(self.table, POOL_SCHEMA, ["factor"], "weight")
        metadata = self.metadata
        required = {"pool_id", "knowledge_through", "horizon", "volume_unit", "currency", "run_id"}
        if not required <= metadata.keys() or any(not metadata[key] for key in required):
            raise ValueError("Frozen factor pool requires selection and source provenance")
        if metadata["pool_id"] != identity(
            {
                "metadata": {key: value for key, value in metadata.items() if key != "pool_id"},
                "members": self.table.to_pylist(),
            }
        ):
            raise ValueError("Frozen factor pool contents changed")
        date.fromisoformat(metadata["knowledge_through"])
        if int(metadata["horizon"]) < 1 or any(column.null_count for column in self.table.columns):
            raise ValueError("Invalid frozen factor pool horizon or missing member values")
        for row in self.table.to_pylist():
            expression_lookback(row["expression"])
            if row["direction"] not in {-1, 1} or not 0 < row["weight"] <= 1 or row["trial_id"] < 0:
                raise ValueError("Invalid frozen factor direction or weight")
        if self.table.num_rows and not np.isclose(
            sum(self.table["weight"].to_pylist()), 1, rtol=0, atol=1e-12
        ):
            raise ValueError("Frozen factor weights must sum to one")


def freeze_factor_pool(members: list[dict[str, Any]], metadata: dict[str, str]) -> FrozenFactorPool:
    values = {**metadata, "schema_version": "invest.research.factor_pool.v1"}
    values.pop("pool_id", None)
    table = pa.Table.from_pylist(members, schema=POOL_SCHEMA)
    values["pool_id"] = identity({"metadata": values, "members": table.to_pylist()})
    return FrozenFactorPool(
        table.replace_schema_metadata(
            {key.encode(): value.encode() for key, value in values.items()}
        )
    )


def load_factor_pool(path: Path) -> FrozenFactorPool:
    return FrozenFactorPool(pq.read_table(path))


def cross_sectional_ranks(features: pd.DataFrame) -> pd.DataFrame:
    """逐会话缩放到 [-1, 1]；无跨日期拟合，单个有效值和全并列横截面均为零。"""
    groups = features.groupby(level="datetime")
    ranks, counts = groups.rank(method="average"), groups.transform("count")
    return ((ranks - 1) / (counts - 1).replace(0, np.nan) * 2 - 1).mask(
        (counts == 1) & features.notna(), 0
    )


def generate_signals(
    pool: FrozenFactorPool,
    snapshot: DataSnapshot,
    as_of: date,
    *,
    allow_exploratory: bool = False,
    cache_root: Path = Path("data/cache"),
) -> SignalFrame:
    return generate_signal_history(
        pool, snapshot, as_of, as_of, allow_exploratory=allow_exploratory, cache_root=cache_root
    )


def generate_signal_history(
    pool: FrozenFactorPool,
    snapshot: DataSnapshot,
    start: date,
    end: date,
    *,
    allow_exploratory: bool = False,
    cache_root: Path = Path("data/cache"),
) -> SignalFrame:
    return evaluate_signals(
        pool, snapshot, start, end, allow_exploratory=allow_exploratory, cache_root=cache_root
    ).signals


def evaluate_signals(
    pool: FrozenFactorPool,
    snapshot: DataSnapshot,
    start: date,
    end: date,
    *,
    allow_exploratory: bool = False,
    cache_root: Path = Path("data/cache"),
) -> SignalEvaluation:
    """一次计算冻结表达式，各会话独立准入与横截面排名，不使用未来标签。"""
    metadata = pool.metadata
    if start < date.fromisoformat(metadata["knowledge_through"]):
        raise ValueError("Signals cannot precede the factor selection cutoff")
    snapshot = load_snapshot(snapshot.directory, expected_id=snapshot.snapshot_id)
    expected = {
        "source": snapshot.spec.source,
        "price_basis": snapshot.spec.price_basis,
        "volume_unit": snapshot.spec.volume_unit,
        "currency": snapshot.spec.currency,
    }
    if any(metadata[key] != value for key, value in expected.items()):
        raise ValueError("Signal data must match the frozen pool source, units and price basis")
    if "exploratory" in (metadata["scope"], snapshot.scope) and not allow_exploratory:
        raise ValueError("Exploratory factor pool requires explicit opt-in")
    if start > end or any(day not in snapshot.calendar["date"].to_pylist() for day in (start, end)):
        raise ValueError("Signal date must be a completed session in the snapshot")
    if not pool.table.num_rows:
        return _cash_signals(pool, snapshot, start, end, allow_exploratory)
    members = pool.table.to_pylist()
    factors = calculate_factors(
        snapshot, {r["factor"]: r["expression"] for r in members}, cache_root
    )
    factors = FactorFrame(
        factors.table.filter(
            pc.and_(
                pc.greater_equal(factors.table["date"], start),
                pc.less_equal(factors.table["date"], end),
            )
        )
    )
    view = qlib_dataset_frame(factors, allow_exploratory=allow_exploratory)
    features = cast(pd.DataFrame, view.get("feature", pd.DataFrame(index=view.index))).reindex(
        columns=[member["factor"] for member in members]
    )
    scaled = cross_sectional_ranks(features)
    ranks = scaled.dropna()
    weights = pd.Series({r["factor"]: r["weight"] * r["direction"] for r in members})
    scores = ranks.mul(weights).sum(axis=1).clip(-1, 1).rename("score").reset_index()
    scores = scores.sort_values(["datetime", "score", "instrument"], ascending=[True, False, True])
    scores["rank"] = scores.groupby("datetime").cumcount() + 1
    calendar = regular_sessions(start, end + timedelta(days=14)).to_pylist()
    cutoffs = {
        left["date"]: (left["close_at"], right["close_at"])
        for left, right in zip(calendar[:-1], calendar[1:], strict=True)
    }
    rows = [
        {
            "date": row["datetime"].date(),
            "instrument": row["instrument"],
            "score": row["score"],
            "rank": row["rank"],
            "direction": int(row["score"] > 0),
            "horizon": int(metadata["horizon"]),
            "available_at": cutoffs[row["datetime"].date()][0],
            "expires_at": cutoffs[row["datetime"].date()][1],
            "pool_id": metadata["pool_id"],
        }
        for row in scores.to_dict("records")
    ]
    provenance = view.attrs["invest"]
    scope = (
        "exploratory"
        if "exploratory" in (metadata["scope"], provenance["scope"])
        else snapshot.scope
    )
    output_metadata = {
        **snapshot.metadata(SIGNAL_SCHEMA),
        b"scope": scope.encode(),
        b"input_scope": snapshot.scope.encode(),
        b"pool_id": metadata["pool_id"].encode(),
        b"timing_policy": b"xnys_session_close",
        b"evidence_status": b"research_only",
        b"input_instruments": str(len(features)).encode(),
        b"retained_instruments": str(len(ranks)).encode(),
    }
    signals = SignalFrame(
        pa.Table.from_pylist(rows, schema=SIGNAL_SCHEMA.with_metadata(output_metadata))
    )
    definitions = {member["factor"]: member for member in members}
    contributions = []
    for row in factors.table.to_pylist():
        member = definitions[row["factor"]]
        key = (pd.Timestamp(row["date"]), row["instrument"])
        rank = float(scaled.loc[key, row["factor"]])
        admitted = bool(np.isfinite(rank))
        contributions.append(
            {
                "date": row["date"],
                "instrument": row["instrument"],
                "factor": row["factor"],
                "value": row["value"],
                "scaled_rank": rank if admitted else None,
                "direction": member["direction"],
                "weight": member["weight"],
                "contribution": rank * member["weight"] * member["direction"] if admitted else None,
                "admitted": admitted,
                "available_at": row["available_at"],
            }
        )
    return SignalEvaluation(
        signals,
        factors,
        pa.Table.from_pylist(
            contributions,
            schema=CONTRIBUTION_SCHEMA.with_metadata(
                {
                    **output_metadata,
                    **(CONTRIBUTION_SCHEMA.metadata or {}),
                }
            ),
        ),
    )


def _cash_signals(
    pool: FrozenFactorPool,
    snapshot: DataSnapshot,
    start: date,
    end: date,
    allow_exploratory: bool,
) -> SignalEvaluation:
    """空池是拒绝筛选后的现金方案；零分不伪造因子或改变原拒绝登记。"""
    calendar = regular_sessions(start, end + timedelta(days=14)).to_pylist()
    cutoffs = {
        left["date"]: (left["close_at"], right["close_at"])
        for left, right in zip(calendar[:-1], calendar[1:], strict=True)
    }
    members_history = snapshot.universe.to_pylist()
    bars_by_day: dict[date, list[dict[str, Any]]] = {}
    for bar in snapshot.bars.to_pylist():
        bars_by_day.setdefault(bar["date"], []).append(bar)
    rows: list[dict[str, Any]] = []
    unknown_admitted = False
    for day in snapshot.calendar["date"].to_pylist():
        if not start <= day <= end:
            continue
        close, expiry = cutoffs[day]
        members = {
            row["instrument"]
            for row in members_history
            if row["start"] <= day <= row["end"]
            and (
                (row["available_at"] is None and allow_exploratory)
                or (row["available_at"] is not None and row["available_at"] <= close)
            )
        }
        eligible = sorted(
            row["instrument"]
            for row in bars_by_day[day]
            if row["date"] == day
            and row["instrument"] in members
            and (
                (row["available_at"] is None and allow_exploratory)
                or (row["available_at"] is not None and row["available_at"] <= close)
            )
        )
        unknown_admitted |= any(
            row["instrument"] in eligible and row["available_at"] is None
            for row in bars_by_day[day]
        ) or any(
            row["instrument"] in eligible
            and row["start"] <= day <= row["end"]
            and row["available_at"] is None
            for row in members_history
        )
        rows.extend(
            {
                "date": day,
                "instrument": instrument,
                "score": 0.0,
                "rank": rank,
                "direction": 0,
                "horizon": int(pool.metadata["horizon"]),
                "available_at": close,
                "expires_at": expiry,
                "pool_id": pool.metadata["pool_id"],
            }
            for rank, instrument in enumerate(eligible, 1)
        )
    metadata = {
        **snapshot.metadata(SIGNAL_SCHEMA),
        b"scope": b"exploratory"
        if unknown_admitted or pool.metadata["scope"] == "exploratory"
        else snapshot.scope.encode(),
        b"pool_id": pool.metadata["pool_id"].encode(),
        b"evidence_status": b"research_only",
        b"selection_status": b"no_selected_factors",
    }
    return SignalEvaluation(
        SignalFrame(pa.Table.from_pylist(rows, schema=SIGNAL_SCHEMA.with_metadata(metadata))),
        FactorFrame(
            pa.Table.from_pylist(
                [], schema=FACTOR_SCHEMA.with_metadata(snapshot.metadata(FACTOR_SCHEMA))
            )
        ),
        pa.Table.from_pylist(
            [],
            schema=CONTRIBUTION_SCHEMA.with_metadata(
                {**metadata, **(CONTRIBUTION_SCHEMA.metadata or {})}
            ),
        ),
    )
