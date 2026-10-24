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
    SIGNAL_SCHEMA,
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
    metadata = pool.metadata
    if not pool.table.num_rows:
        raise ValueError("No selected factors; an empty pool cannot produce signals")
    if as_of < date.fromisoformat(metadata["knowledge_through"]):
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
    if metadata["scope"] == "exploratory" and not allow_exploratory:
        raise ValueError("Exploratory factor pool requires explicit opt-in")
    if as_of not in snapshot.calendar["date"].to_pylist():
        raise ValueError("Signal date must be a completed session in the snapshot")
    members = pool.table.to_pylist()
    factors = calculate_factors(
        snapshot, {r["factor"]: r["expression"] for r in members}, cache_root
    )
    factors = FactorFrame(factors.table.filter(pc.equal(factors.table["date"], as_of)))
    view = qlib_dataset_frame(factors, allow_exploratory=allow_exploratory)
    features = cast(pd.DataFrame, view.get("feature", pd.DataFrame(index=view.index))).reindex(
        columns=[member["factor"] for member in members]
    )
    ranks = cross_sectional_ranks(features).dropna()
    weights = pd.Series({r["factor"]: r["weight"] * r["direction"] for r in members})
    scores = ranks.mul(weights).sum(axis=1).clip(-1, 1).rename("score").reset_index()
    scores = scores.sort_values(["score", "instrument"], ascending=[False, True])
    calendar = regular_sessions(as_of, as_of + timedelta(days=14)).to_pylist()
    rows = [
        {
            "date": as_of,
            "instrument": row["instrument"],
            "score": row["score"],
            "rank": index + 1,
            "direction": int(row["score"] > 0),
            "horizon": int(metadata["horizon"]),
            "available_at": calendar[0]["close_at"],
            "expires_at": calendar[1]["close_at"],
            "pool_id": metadata["pool_id"],
        }
        for index, row in enumerate(scores.to_dict("records"))
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
    return SignalFrame(
        pa.Table.from_pylist(rows, schema=SIGNAL_SCHEMA.with_metadata(output_metadata))
    )
