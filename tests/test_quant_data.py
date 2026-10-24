"""P1 的真实库离线集成：时序、精度、缓存隔离和原始证据保留。"""

import shutil
import socket
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.contracts import (
    RESEARCH_BARS,
    UNIVERSE,
    DataSnapshot,
    FactorFrame,
    LabelFrame,
    SnapshotSpec,
)
from invest.factor_diagnostics import diagnose_factor, forward_labels, qlib_dataset_frame
from invest.ibkr_data import save_capture
from invest.ibkr_models import IBKRConfig
from invest.ibkr_synthetic import SyntheticBroker, demo_capture
from invest.qlib_adapter import build_qlib_cache, calculate_factors
from invest.quality import regular_sessions
from invest.research_data import create_snapshot, digest, load_snapshot, snapshot_from_ibkr

SPEC = SnapshotSpec("synthetic", "test_quant_data_v1", "raw", "shares", "synthetic")


def inputs(
    length: int = 12, offset: int = 0, start: date = date(2024, 1, 2)
) -> tuple[pa.Table, pa.Table]:
    end = start + timedelta(days=31)
    sessions = regular_sessions(start, end).to_pylist()[:length]
    rows, members = [], []
    for number in range(1, 5):
        instrument = f"TEST{number}"
        members.append(
            {
                "instrument": instrument,
                "symbol": instrument,
                "start": sessions[0]["date"],
                "end": sessions[-1]["date"],
                "available_at": sessions[0]["open_at"],
            }
        )
        for index, session in enumerate(sessions):
            price = Decimal("100.123456789012345678") + offset + number * index
            rows.append(
                {
                    "date": session["date"],
                    "instrument": instrument,
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price + 1,
                    "volume": Decimal(1000 * number),
                    "available_at": session["close_at"],
                    "captured_at": datetime.combine(
                        end + timedelta(days=1), datetime.min.time(), tzinfo=UTC
                    ),
                }
            )
    return pa.Table.from_pylist(rows, schema=RESEARCH_BARS), pa.Table.from_pylist(
        members, schema=UNIVERSE
    )


def snapshot(tmp_path: Path, name: str = "snapshot", **kwargs: Any) -> DataSnapshot:
    bars, universe = inputs(**kwargs)
    return create_snapshot(bars, universe, tmp_path / name, SPEC)


def test_snapshot_preserves_decimal_and_is_immutable(tmp_path: Path) -> None:
    bars, universe = inputs()
    path = tmp_path / "snapshot"
    saved = create_snapshot(bars, universe, path, SPEC)
    original = {p: p.read_bytes() for p in path.iterdir()}
    loaded = load_snapshot(path)
    assert saved.snapshot_id == loaded.snapshot_id and loaded.scope == "synthetic"
    assert loaded.bars["open"][0].as_py() == Decimal("100.123456789012345678")
    assert pq.read_table(path / "snapshot.parquet")["account_eligible"].to_pylist() == [False]
    assert (
        pq.ParquetFile(path / "bars.parquet").metadata.row_group(0).column(0).compression == "ZSTD"
    )
    with pytest.raises(FileExistsError, match="immutable"):
        create_snapshot(bars, universe, path, SPEC)
    assert {p: p.read_bytes() for p in original} == original
    pq.write_table(bars.slice(1), path / "bars.parquet")
    with pytest.raises(ValueError, match="changed"):
        load_snapshot(path)


@pytest.mark.parametrize(
    "invalid", ["missing", "duplicate", "ohlc", "unfinished", "early", "weekend", "overlap"]
)
def test_snapshot_rejects_invalid_inputs_before_publication(tmp_path: Path, invalid: str) -> None:
    bars, universe = inputs()
    rows, members = bars.to_pylist(), universe.to_pylist()
    if invalid == "missing":
        rows.pop(2)
    elif invalid == "duplicate":
        rows.append(rows[0])
    elif invalid == "ohlc":
        rows[0]["low"] = Decimal(10000)
    elif invalid == "unfinished":
        rows[0]["captured_at"] = datetime(2024, 1, 2, 15, tzinfo=UTC)
    elif invalid == "early":
        rows[0]["available_at"] -= timedelta(days=1)
    elif invalid == "weekend":
        rows[0]["date"] = date(2024, 1, 6)
    else:
        members.append(members[0])
    with pytest.raises(ValueError):
        create_snapshot(
            pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
            pa.Table.from_pylist(members, schema=UNIVERSE),
            tmp_path / "bad",
            SPEC,
        )
    assert not (tmp_path / "bad").exists()


def test_unknown_availability_and_reference_sources_stay_explicit(tmp_path: Path) -> None:
    bars, universe = inputs()
    rows = bars.to_pylist()
    rows[0]["available_at"] = None
    bars = pa.Table.from_pylist(rows, schema=RESEARCH_BARS)
    spec = replace(SPEC, source="alpaca", universe_basis="current_sample")
    with pytest.raises(ValueError, match="opt-in"):
        create_snapshot(bars, universe, tmp_path / "rejected", spec)
    saved = create_snapshot(bars, universe, tmp_path / "reference", spec, allow_exploratory=True)
    assert saved.spec.source == "alpaca" and saved.scope == "exploratory"
    assert {
        "historical_availability_unknown",
        "historical_reference_source",
        "current_sample_not_historical_universe",
    } <= set(saved.limitations)


def test_ibkr_adapter_preserves_capture_and_downgrades_missing_evidence(tmp_path: Path) -> None:
    capture = save_capture(demo_capture(SyntheticBroker(), IBKRConfig()), tmp_path / "capture")
    original = {p: digest(p) for p in capture.iterdir()}
    with pytest.raises(ValueError, match="opt-in"):
        snapshot_from_ibkr(capture, tmp_path / "strict")
    saved = snapshot_from_ibkr(capture, tmp_path / "exploratory", allow_exploratory=True)
    assert saved.spec.source == "synthetic" and saved.spec.price_basis == "split_adjusted"
    assert saved.bars["available_at"].null_count == saved.bars.num_rows
    assert {
        "historical_availability_unknown",
        "volume_unit_unverified",
        "split_adjusted_without_dividend_returns",
    } <= set(saved.limitations)
    assert (
        saved.bars["open"].to_pylist()
        == pq.read_table(capture / "historical.parquet")["open"].to_pylist()
    )
    assert {p: digest(p) for p in original} == original


def test_native_cache_rebuild_and_snapshot_switch_preserve_source(tmp_path: Path) -> None:
    first = snapshot(tmp_path, "first")
    second = snapshot(tmp_path, "second", offset=50)
    root = tmp_path / "cache"
    before = {p: p.read_bytes() for p in first.directory.iterdir()}
    errors = np.geterr()
    left = calculate_factors(first, {"close": "$close", "mean": "Mean($close,2)"}, root)
    cache = build_qlib_cache(first, root)
    files = {p.relative_to(cache): p.read_bytes() for p in cache.rglob("*") if p.is_file()}
    assert np.geterr() == errors
    assert build_qlib_cache(first, root) == cache
    right = calculate_factors(second, {"close": "$close"}, root)
    assert right.table["value"][0].as_py() != left.table["value"][0].as_py()
    assert calculate_factors(
        first, {"close": "$close", "mean": "Mean($close,2)"}, root
    ).table.equals(left.table)
    shutil.rmtree(cache)
    assert build_qlib_cache(first, root) == cache
    assert {p.relative_to(cache): p.read_bytes() for p in cache.rglob("*") if p.is_file()} == files
    assert {p: p.read_bytes() for p in before} == before
    rows = [r for r in left.table.to_pylist() if r["instrument"] == "TEST1"]
    assert rows[1]["value"] is None
    assert rows[2]["value"] == pytest.approx(float(first.bars["close"][4].as_py()), rel=1e-6)
    assert rows[3]["value"] == pytest.approx(101.62345678901235, rel=1e-6)


def test_cache_versions_and_corruption_are_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = snapshot(tmp_path)
    root = tmp_path / "cache"
    old = build_qlib_cache(data, root)
    monkeypatch.setattr("invest.qlib_adapter.CONVERTER_VERSION", "test_converter_v2")
    new = build_qlib_cache(data, root)
    assert old != new and old.exists()
    (new / "features/test1/close.day.bin").write_bytes(b"bad")
    with pytest.raises(ValueError, match="changed"):
        build_qlib_cache(data, root)
    with pytest.raises(ValueError, match="separate"):
        build_qlib_cache(data, data.directory / "cache")


def test_snapshot_parameters_and_stale_handles_are_isolated(tmp_path: Path) -> None:
    first = snapshot(tmp_path)
    bars, universe = inputs()
    second = create_snapshot(
        bars,
        universe,
        tmp_path / "adjusted",
        replace(SPEC, price_basis="total_return_adjusted"),
    )
    assert first.snapshot_id != second.snapshot_id
    assert build_qlib_cache(first, tmp_path / "cache") != build_qlib_cache(
        second, tmp_path / "cache"
    )
    stale = replace(first, snapshot_id="0" * 64)
    with pytest.raises(ValueError, match="identity changed"):
        calculate_factors(stale, {"price": "$close"}, tmp_path / "cache")
    with pytest.raises(ValueError, match="identity changed"):
        forward_labels(stale)


def test_ibkr_mixed_capture_metadata_is_rejected(tmp_path: Path) -> None:
    capture = save_capture(demo_capture(SyntheticBroker(), IBKRConfig()), tmp_path / "capture")
    path = capture / "historical.parquet"
    table = pq.read_table(path)
    table = table.replace_schema_metadata(
        {**(table.schema.metadata or {}), b"captured_at": b"other_capture"}
    )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match="provenance"):
        snapshot_from_ibkr(capture, tmp_path / "mixed", allow_exploratory=True)


@pytest.mark.parametrize(
    "expression",
    [
        "Ref($close,-1)",
        "Ref($close,0)",
        "Mean($close,0)",
        "Mean($future,2)",
        "__import__('os')",
        "Mean($close,2).shift(-1)",
    ],
)
def test_noncausal_or_undeclared_expressions_are_rejected(tmp_path: Path, expression: str) -> None:
    data = snapshot(tmp_path)
    with pytest.raises(ValueError, match="causal"):
        calculate_factors(data, {"bad": expression}, tmp_path / "cache")
    assert not (tmp_path / "cache").exists()


def test_future_rows_do_not_change_past_factors(tmp_path: Path) -> None:
    short, long = snapshot(tmp_path, "short", length=6), snapshot(tmp_path, "long")
    expressions = {"momentum": "$close/Ref($close,2)-1", "mean": "Mean($close,3)"}
    left = calculate_factors(short, expressions, tmp_path / "cache").table.to_pandas()
    right = calculate_factors(long, expressions, tmp_path / "cache").table.to_pandas()
    right = right[right["date"] <= max(left["date"])]
    keys = ["date", "instrument", "factor"]
    pd.testing.assert_frame_equal(
        left.sort_values(keys).reset_index(drop=True),
        right.sort_values(keys).reset_index(drop=True),
    )


def test_labels_and_real_library_interfaces(tmp_path: Path) -> None:
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.loader import StaticDataLoader

    data = snapshot(tmp_path)
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    row = labels.table.to_pylist()[0]
    bars = data.bars.to_pylist()
    opening = {(r["date"], r["instrument"]): r["open"] for r in bars}
    assert row["entry_at"].date() == date(2024, 1, 3)
    assert row["exit_at"].date() == date(2024, 1, 4)
    assert row["value"] == pytest.approx(
        float(opening[(date(2024, 1, 4), "TEST1")] / opening[(date(2024, 1, 3), "TEST1")] - 1)
    )
    qlib_input = qlib_dataset_frame(factors, labels)
    path = tmp_path / "qlib.parquet"
    qlib_input.to_parquet(path, compression="zstd")
    loaded = StaticDataLoader(config=path).load()
    pd.testing.assert_frame_equal(qlib_input, loaded)
    handler = DataHandlerLP(
        data_loader=StaticDataLoader(config=path), infer_processors=[], learn_processors=[]
    )
    dataset = DatasetH(handler, segments={"train": ("2024-01-03", "2024-01-08")})
    train = dataset.prepare("train", col_set="feature")
    assert list(train.columns) == ["momentum"] and len(train) == 16
    assert list(qlib_dataset_frame(factors).columns.get_level_values(0).unique()) == ["feature"]
    result = diagnose_factor(factors, labels, "momentum", quantiles=2, max_loss=0.3)
    assert result.input_rows == 48 and result.retained_rows == 36
    assert result.loss_fraction == 0.25
    assert result.rank_ic["1D"].to_list() == pytest.approx([1.0] * 9)
    assert result.timing_rejected_rows == 0 and result.scope == "synthetic"


def test_diagnostics_enforce_timing_loss_and_matching_snapshots(tmp_path: Path) -> None:
    data = snapshot(tmp_path)
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    other = forward_labels(snapshot(tmp_path, "other", offset=1), (1,))
    with pytest.raises(ValueError, match="provenance"):
        diagnose_factor(factors, other, "momentum")
    with pytest.raises(ValueError, match="provenance"):
        qlib_dataset_frame(factors, other)
    rows = factors.table.to_pylist()
    for row in rows:
        row["available_at"] = datetime(2025, 1, 1, tzinfo=UTC)
    late = FactorFrame(pa.Table.from_pylist(rows, schema=factors.table.schema))
    with pytest.raises(Exception, match="max_loss"):
        diagnose_factor(late, labels, "momentum", quantiles=2)
    with pytest.raises(Exception, match="max_loss"):
        diagnose_factor(factors, labels, "momentum", quantiles=2, max_loss=0.1)
    rows = labels.table.to_pylist()
    rows[0]["entry_at"] = datetime(2024, 1, 2, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="after the decision"):
        LabelFrame(pa.Table.from_pylist(rows, schema=labels.table.schema))


@pytest.mark.parametrize(
    ("rejected_day", "available_at", "retained_rows"),
    [
        (date(2024, 1, 4), datetime(2024, 1, 4, 21, 0, 0, 1, tzinfo=UTC), 32),
        (date(2024, 1, 4), datetime(2024, 1, 5, 14, 30, tzinfo=UTC), 32),
        (date(2024, 1, 4), datetime(2025, 1, 1, tzinfo=UTC), 32),
        (date(2024, 1, 18), datetime(2025, 1, 1, tzinfo=UTC), 36),
    ],
)
def test_research_views_reject_factors_after_decision_close(
    tmp_path: Path, rejected_day: date, available_at: datetime, retained_rows: int
) -> None:
    from qlib.data.dataset.loader import StaticDataLoader

    data = snapshot(tmp_path)
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    rows = factors.table.to_pylist()
    for row in rows:
        if row["date"] == rejected_day:
            row["available_at"] = available_at
    factors = FactorFrame(pa.Table.from_pylist(rows, schema=factors.table.schema))
    original = factors.table.to_pylist()
    original_metadata = factors.table.schema.metadata
    for allow_exploratory in (False, True):
        for target_labels in (None, labels):
            target = qlib_dataset_frame(factors, target_labels, allow_exploratory=allow_exploratory)
            loaded = StaticDataLoader(config=target).load()
            assert loaded.loc[rejected_day.isoformat(), ("feature", "momentum")].isna().all()
            assert loaded.loc["2024-01-03", ("feature", "momentum")].notna().all()
            assert loaded.attrs["invest"]["timing_rejected_rows"] == 4
        result = diagnose_factor(
            factors,
            labels,
            "momentum",
            quantiles=2,
            max_loss=0.5,
            allow_exploratory=allow_exploratory,
        )
        assert result.timing_rejected_rows == 4 and result.retained_rows == retained_rows
        assert pd.Timestamp(rejected_day) not in result.clean.index.get_level_values("date")
    assert factors.table.to_pylist() == original
    assert factors.table.schema.metadata == original_metadata


@pytest.mark.parametrize(
    ("source", "input_scope"), [("synthetic", "synthetic"), ("ibkr", "research")]
)
def test_exploratory_views_preserve_provenance_through_parquet_and_qlib(
    tmp_path: Path, source: str, input_scope: str
) -> None:
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.loader import StaticDataLoader

    bars, universe = inputs()
    data = create_snapshot(
        bars,
        universe,
        tmp_path / "snapshot",
        replace(SPEC, source=source, universe_basis="historical"),
    )
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    rows = factors.table.to_pylist()
    for row in rows:
        row["available_at"] = None
    factors = FactorFrame(pa.Table.from_pylist(rows, schema=factors.table.schema))
    assert qlib_dataset_frame(factors)[("feature", "momentum")].isna().all()
    with pytest.raises(Exception, match="max_loss"):
        diagnose_factor(factors, labels, "momentum", quantiles=2)

    training = qlib_dataset_frame(factors, labels, allow_exploratory=True)
    provenance = training.attrs["invest"]
    assert provenance == {
        "snapshot_id": data.snapshot_id,
        "source": source,
        "price_basis": "raw",
        "input_scope": input_scope,
        "scope": "exploratory",
        "timing_policy": "xnys_session_close",
        "allow_exploratory": True,
        "unknown_timing_rows": 44,
        "timing_rejected_rows": 0,
    }
    assert (factors.table.schema.metadata or {})[b"scope"].decode() == input_scope
    result = diagnose_factor(factors, labels, "momentum", quantiles=2, allow_exploratory=True)
    assert result.scope == "exploratory" and result.source == source
    assert result.price_basis == "raw" and result.retained_rows == 36
    for name, frame in (
        ("dataset", training),
        ("rank_ic", result.rank_ic),
        ("clean", result.clean),
    ):
        path = tmp_path / f"{name}.parquet"
        frame.to_parquet(path, compression="zstd")
        assert pd.read_parquet(path).attrs["invest"] == provenance
    loaded = StaticDataLoader(config=tmp_path / "dataset.parquet").load()
    assert loaded.attrs["invest"] == provenance
    handler = DataHandlerLP(
        data_loader=StaticDataLoader(config=training), infer_processors=[], learn_processors=[]
    )
    dataset = DatasetH(handler, segments={"train": ("2024-01-03", "2024-01-08")})
    assert dataset.prepare("train", col_set="feature").attrs["invest"] == provenance
    assert qlib_dataset_frame(factors, allow_exploratory=True).attrs["invest"] == provenance


@pytest.mark.parametrize(
    ("start", "decision_at"),
    [
        (date(2024, 3, 6), datetime(2024, 3, 8, 21, tzinfo=UTC)),
        (date(2024, 3, 6), datetime(2024, 3, 11, 20, tzinfo=UTC)),
        (date(2024, 11, 25), datetime(2024, 11, 29, 18, tzinfo=UTC)),
    ],
)
def test_research_cutoff_uses_dst_and_early_close_sessions(
    tmp_path: Path, start: date, decision_at: datetime
) -> None:
    data = snapshot(tmp_path, start=start)
    factors = calculate_factors(
        data,
        {"on_time": "$close/Ref($close,1)-1", "late": "$close/Ref($close,1)-1"},
        tmp_path / "cache",
    )
    labels = forward_labels(data, (1,))
    rows = factors.table.to_pylist()
    for row in rows:
        if row["date"] == decision_at.date():
            row["available_at"] = decision_at + timedelta(microseconds=row["factor"] == "late")
    factors = FactorFrame(pa.Table.from_pylist(rows, schema=factors.table.schema))
    target = qlib_dataset_frame(factors, labels)
    day = decision_at.date().isoformat()
    selected = target.loc[target.index.get_level_values("datetime") == pd.Timestamp(day)]
    assert selected[("feature", "on_time")].notna().all()
    assert selected[("feature", "late")].isna().all()
    on_time = diagnose_factor(factors, labels, "on_time", quantiles=2)
    late = diagnose_factor(factors, labels, "late", quantiles=2, max_loss=0.5)
    assert pd.Timestamp(day) in on_time.clean.index.get_level_values("date")
    assert pd.Timestamp(day) not in late.clean.index.get_level_values("date")


def test_capture_time_factors_never_enter_historical_model_data(tmp_path: Path) -> None:
    bars, universe = inputs()
    rows = bars.to_pylist()
    for row in rows:
        row["available_at"] = row["captured_at"]
    data = create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS), universe, tmp_path / "snapshot", SPEC
    )
    factors = calculate_factors(data, {"price": "$close"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    assert factors.table["value"].null_count == 0
    for target_labels in (None, labels):
        target = qlib_dataset_frame(factors, target_labels, allow_exploratory=True)
        assert target[("feature", "price")].isna().all()
        assert target.attrs["invest"]["timing_rejected_rows"] == 48
    with pytest.raises(Exception, match="max_loss"):
        diagnose_factor(factors, labels, "price", quantiles=2, allow_exploratory=True)


def test_offline_frame_roundtrip_and_cache_cleanup_preserve_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Research data pipeline must run offline")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    history = tmp_path / "historical_account"
    history.mkdir()
    for name in ("registration.parquet", "journal.parquet", "research.parquet"):
        pq.write_table(pa.table({"original": [name]}), history / name)
    original = {p: p.read_bytes() for p in history.iterdir()}
    data = snapshot(tmp_path)
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    for name, table in (("factors", factors.table), ("labels", labels.table)):
        pq.write_table(table, tmp_path / f"{name}.parquet", compression="zstd")
    factors = FactorFrame(pq.read_table(tmp_path / "factors.parquet"))
    labels = LabelFrame(pq.read_table(tmp_path / "labels.parquet"))
    assert diagnose_factor(factors, labels, "momentum", quantiles=2).retained_rows == 36
    shutil.rmtree(build_qlib_cache(data, tmp_path / "cache"))
    assert {p: p.read_bytes() for p in original} == original
    assert load_snapshot(data.directory).snapshot_id == data.snapshot_id


def test_unknown_factor_timing_requires_explicit_exploration(tmp_path: Path) -> None:
    bars, universe = inputs()
    rows = bars.to_pylist()
    for row in rows:
        row["available_at"] = None
    data = create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        universe,
        tmp_path / "exploratory",
        replace(SPEC, source="ibkr"),
        allow_exploratory=True,
    )
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,1)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (1,))
    with pytest.raises(ValueError, match="opt-in"):
        diagnose_factor(factors, labels, "momentum", quantiles=2)
    for target_labels in (None, labels):
        with pytest.raises(ValueError, match="opt-in"):
            qlib_dataset_frame(factors, target_labels)
        view = qlib_dataset_frame(factors, target_labels, allow_exploratory=True)
        assert view.attrs["invest"]["source"] == "ibkr"
        assert view.attrs["invest"]["input_scope"] == view.attrs["invest"]["scope"] == "exploratory"
    result = diagnose_factor(factors, labels, "momentum", quantiles=2, allow_exploratory=True)
    assert result.scope == "exploratory" and result.retained_rows == 36
