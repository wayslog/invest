"""P2 公开研究接口：搜索预算、时间边界、冻结结果和信号。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.contracts import RESEARCH_BARS, UNIVERSE, DataSnapshot, SnapshotSpec
from invest.factor_diagnostics import forward_labels
from invest.qlib_adapter import calculate_factors
from invest.quality import regular_sessions
from invest.research_data import create_snapshot


def research_snapshot(
    root: Path,
    name: str = "snapshot",
    length: int = 160,
    changed_after: int = 1000,
    flat: bool = False,
    instrument_prefix: str = "SYNTH",
) -> DataSnapshot:
    sessions = regular_sessions(date(2022, 1, 3), date(2022, 12, 30)).to_pylist()[:length]
    rows, members = [], []
    for number in range(1, 9):
        instrument = f"{instrument_prefix}{number}"
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
            slope = number if index < changed_after else 9 - number
            price = (
                Decimal(100)
                if flat
                else (Decimal(50 + number * 10) * (1 + Decimal(slope) / 2000) ** index)
            ).quantize(Decimal("0.00000001"))
            rows.append(
                {
                    "date": session["date"],
                    "instrument": instrument,
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price,
                    "volume": Decimal(1000 * number + index % 7 * 20),
                    "available_at": session["close_at"],
                    "captured_at": datetime(2023, 1, 1, tzinfo=UTC),
                }
            )
    return create_snapshot(
        pa.Table.from_pylist(rows, schema=RESEARCH_BARS),
        pa.Table.from_pylist(members, schema=UNIVERSE),
        root / name,
        SnapshotSpec("synthetic", "p2_test_v1", "raw", "shares", "synthetic"),
    )


def mining_config(root: Path, data: DataSnapshot, name: str = "mine.toml") -> Path:
    days = data.calendar["date"].to_pylist()
    path = root / name
    path.write_text(f'''snapshot = "{data.directory.as_posix()}"
train_start = {days[10]}
train_end = {days[79]}
validation_start = {days[80]}
validation_end = {days[119]}
test_start = {days[120]}
test_end = {days[139]}
known_through = {days[79]}
families = ["momentum", "reversal"]
windows = [2, 4, 8]
candidate_budget = 6
seed = 19
horizon = 3
min_sessions = 8
test_block_size = 1
''')
    return path


def test_candidate_search_is_bounded_and_reproducible(tmp_path: Path) -> None:
    from invest.factor_mining import generate_candidates
    from invest.mining_config import load_mining_config
    from invest.qlib_adapter import expression_lookback

    path = tmp_path / "mine.toml"
    path.write_text(
        """snapshot = "snapshot"
train_start = 2022-01-03
train_end = 2022-04-29
validation_start = 2022-05-02
validation_end = 2022-06-30
test_start = 2022-07-01
test_end = 2022-07-29
known_through = 2022-06-30
families = ["momentum", "reversal"]
windows = [2, 4, 8]
candidate_budget = 4
seed = 19
"""
    )
    config = load_mining_config(path)
    candidates = generate_candidates(config)
    assert len(candidates) == 4 and candidates == generate_candidates(config)
    assert len({candidate.expression for candidate in candidates}) == 4
    assert {candidate.family for candidate in candidates} == {"momentum", "reversal"}
    assert all(expression_lookback(candidate.expression) in {2, 4, 8} for candidate in candidates)
    assert [candidate.trial_id for candidate in candidates] == list(range(4))


def test_segment_labels_are_purged_at_the_training_boundary(tmp_path: Path) -> None:
    from invest.factor_mining import purge_segment

    data = research_snapshot(tmp_path)
    factors = calculate_factors(data, {"momentum": "$close/Ref($close,2)-1"}, tmp_path / "cache")
    labels = forward_labels(data, (3,))
    days = data.calendar["date"].to_pylist()
    segment_factors, segment_labels, purged = purge_segment(
        factors, labels, days[10], days[79], 3, snapshot=data
    )
    assert purged == 32
    assert max(segment_factors.table["date"].to_pylist()) == days[75]
    assert all(row["exit_at"].date() <= days[79] for row in segment_labels.table.to_pylist())
    assert all(row["date"] >= days[10] for row in segment_labels.table.to_pylist())
    assert segment_labels.table.num_rows == 66 * 8


def test_frozen_pool_produces_rank_signals_without_future_labels(tmp_path: Path) -> None:
    from invest.signals import (
        freeze_factor_pool,
        generate_signal_history,
        generate_signals,
        load_factor_pool,
    )

    data = research_snapshot(tmp_path)
    days = data.calendar.to_pylist()
    pool = freeze_factor_pool(
        [
            {
                "factor": "price",
                "expression": "$close",
                "direction": 1,
                "weight": 0.5,
                "trial_id": 0,
            },
            {
                "factor": "inverse",
                "expression": "0-$close",
                "direction": -1,
                "weight": 0.5,
                "trial_id": 1,
            },
        ],
        {
            "snapshot_id": data.snapshot_id,
            "source": "synthetic",
            "price_basis": "raw",
            "scope": "synthetic",
            "volume_unit": "shares",
            "currency": "USD",
            "knowledge_through": days[79]["date"].isoformat(),
            "horizon": "3",
            "run_id": "test_run",
        },
    )
    path = tmp_path / "pool.parquet"
    pq.write_table(pool.table, path, compression="zstd")
    loaded = load_factor_pool(path)
    signals = generate_signals(loaded, data, days[119]["date"], cache_root=tmp_path / "cache")
    rows = signals.table.to_pylist()
    assert len(rows) == 8 and rows[0]["instrument"] == "SYNTH8"
    assert rows[0]["score"] == 1.0 and rows[0]["rank"] == 1 and rows[0]["direction"] == 1
    assert rows[-1]["score"] == -1.0 and rows[-1]["direction"] == 0
    assert all(row["available_at"] == days[119]["close_at"] for row in rows)
    assert all(row["expires_at"] == days[120]["close_at"] for row in rows)
    history = generate_signal_history(
        loaded, data, days[118]["date"], days[120]["date"], cache_root=tmp_path / "cache"
    )
    assert [row for row in history.table.to_pylist() if row["date"] == days[119]["date"]] == rows
    assert history.table.num_rows == 24
    with pytest.raises(ValueError, match="selection"):
        generate_signals(loaded, data, days[78]["date"], cache_root=tmp_path / "cache")
    extended = research_snapshot(tmp_path, "changed", changed_after=120)
    assert (
        generate_signals(
            loaded, extended, days[119]["date"], cache_root=tmp_path / "cache"
        ).table.to_pylist()
        == rows
    )
    truncated = research_snapshot(tmp_path, "prefix", length=120)
    assert (
        generate_signals(
            loaded, truncated, days[119]["date"], cache_root=tmp_path / "cache"
        ).table.to_pylist()
        == rows
    )
    with pytest.raises(ValueError, match="changed"):
        from invest.signals import FrozenFactorPool

        tampered = pool.table.set_column(
            pool.table.schema.get_field_index("weight"), "weight", pa.array([0.2, 0.8])
        )
        FrozenFactorPool(tampered)
    late_rows = truncated.bars.to_pylist()
    from datetime import timedelta

    for row in late_rows:
        if row["date"] == days[119]["date"] and row["instrument"] == "SYNTH8":
            row["available_at"] += timedelta(seconds=1)
    late = create_snapshot(
        pa.Table.from_pylist(late_rows, schema=truncated.bars.schema),
        truncated.universe,
        tmp_path / "late",
        truncated.spec,
    )
    admitted = generate_signals(loaded, late, days[119]["date"], cache_root=tmp_path / "cache")
    assert "SYNTH8" not in admitted.table["instrument"].to_pylist()
    assert admitted.table.num_rows == 7


def test_mining_records_every_trial_and_freezes_a_nonredundant_pool(tmp_path: Path) -> None:
    from invest.factor_mining import run_mining
    from invest.signals import load_factor_pool

    data = research_snapshot(tmp_path)
    config = mining_config(tmp_path, data)
    result = run_mining(config, tmp_path / "study", cache_root=tmp_path / "cache")
    assert result.status == "selected" and result.candidates == 6 and result.selected == 1
    trials = pq.read_table(result.directory / "trials.parquet").to_pylist()
    assert len(trials) == 6 and {row["trial_id"] for row in trials} == set(range(6))
    assert sum(row["status"] == "selected" for row in trials) == 1
    assert sum(row["reason"] == "redundant_correlation" for row in trials) == 5
    pool = load_factor_pool(result.directory / "factor_pool.parquet")
    assert pool.table["weight"].to_pylist() == [1.0]
    assert pool.metadata["scope"] == "synthetic"
    assert pq.read_table(result.directory / "signals.parquet").num_rows == 8
    dates = pq.read_table(result.directory / "factors.parquet")["date"].to_pylist()
    assert max(dates) == data.calendar["date"][119].as_py()
    metrics = pq.read_table(result.directory / "diagnostics.parquet").to_pylist()
    assert {"rank_ic", "quantile_return", "turnover", "rank_autocorrelation", "annual_rank_ic"} <= {
        row["metric"] for row in metrics
    }
    assert all(
        abs(row["value"]) < 1e-10
        for row in metrics
        if row["metric"] == "turnover" and row["value"] is not None
    )
    saved = pq.read_table(result.directory / "run.parquet").to_pylist()[0]
    assert saved["holdout_status"] == "reserved_unassessed" and not saved["account_eligible"]
    with pytest.raises(FileExistsError):
        run_mining(config, result.directory, cache_root=tmp_path / "cache")


def test_single_available_factor_value_does_not_restore_missing_signals(tmp_path: Path) -> None:
    from invest.signals import freeze_factor_pool, generate_signals

    data = research_snapshot(tmp_path)
    days = data.calendar.to_pylist()
    rows = data.bars.to_pylist()
    for row in rows:
        if row["date"] == days[118]["date"] and row["instrument"] != "SYNTH1":
            row["available_at"] = days[119]["close_at"] + timedelta(seconds=1)
    late = create_snapshot(
        pa.Table.from_pylist(rows, schema=data.bars.schema),
        data.universe,
        tmp_path / "late",
        data.spec,
    )
    pool = freeze_factor_pool(
        [
            {
                "factor": name,
                "expression": expression,
                "direction": 1,
                "weight": 0.5,
                "trial_id": index,
            }
            for index, (name, expression) in enumerate(
                (("price", "$close"), ("momentum", "$close/Ref($close,2)-1"))
            )
        ],
        {
            "snapshot_id": data.snapshot_id,
            "source": "synthetic",
            "price_basis": "raw",
            "scope": "synthetic",
            "volume_unit": "shares",
            "currency": "USD",
            "knowledge_through": days[79]["date"].isoformat(),
            "horizon": "3",
            "run_id": "singleton_test",
        },
    )
    signals = generate_signals(pool, late, days[119]["date"], cache_root=tmp_path / "cache")
    assert signals.table["instrument"].to_pylist() == ["SYNTH1"]
    assert signals.table["score"].to_pylist() == [-0.5]
    metadata = signals.table.schema.metadata
    assert metadata[b"input_instruments"] == b"8"
    assert metadata[b"retained_instruments"] == b"1"


def test_unavailable_label_prices_do_not_change_mining_selection(tmp_path: Path) -> None:
    from invest.factor_mining import run_mining

    data = research_snapshot(tmp_path)
    days = data.calendar.to_pylist()
    original = {(row["date"], row["instrument"]): row for row in data.bars.to_pylist()}
    results = []
    for changed in (False, True):
        rows = data.bars.to_pylist()
        for row in rows:
            if row["date"] == days[108]["date"]:
                row["available_at"] = days[119]["close_at"] + timedelta(seconds=1)
                if changed:
                    number = int(row["instrument"].removeprefix("SYNTH"))
                    entry = original[days[105]["date"], row["instrument"]]["open"]
                    row["open"] = (entry * (1 + Decimal(9 - number) / 10000)).quantize(
                        Decimal("0.00000001")
                    )
                    row["high"] = max(row["open"], row["close"]) + 2
                    row["low"] = min(row["open"], row["close"]) - 2
        snapshot = create_snapshot(
            pa.Table.from_pylist(rows, schema=data.bars.schema),
            data.universe,
            tmp_path / f"late_{changed}",
            data.spec,
        )
        config = mining_config(tmp_path, snapshot, f"mine_{changed}.toml")
        config.write_text(config.read_text() + "min_validation_ic = 0.99\n")
        results.append(
            run_mining(config, tmp_path / f"study_{changed}", cache_root=tmp_path / "cache")
        )
    left, right = results
    assert left.selected == right.selected == 1
    for name in ("trials", "factor_pool", "labels"):
        assert (
            pq.read_table(left.directory / f"{name}.parquet").to_pylist()
            == pq.read_table(right.directory / f"{name}.parquet").to_pylist()
        )
    for result in results:
        labels = pq.read_table(result.directory / "labels.parquet").to_pylist()
        rejected = [row for row in labels if row["date"] == days[104]["date"]]
        assert len(rejected) == 8 and all(row["value"] is None for row in rejected)
        assert pq.read_table(result.directory / "signals.parquet").num_rows == 8
        metrics = pq.read_table(result.directory / "diagnostics.parquet").to_pylist()
        rejected_counts = [
            row["value"]
            for row in metrics
            if row["segment"] == "validation" and row["metric"] == "label_timing_rejected_rows"
        ]
        assert rejected_counts == [16.0] * 6


@pytest.mark.parametrize(
    ("offset", "allow_exploratory", "retained"),
    [
        (-1, False, True),
        (0, False, True),
        (1, False, False),
        (1, True, False),
        (None, False, False),
        (None, True, True),
    ],
)
def test_label_price_admission_uses_segment_cutoff_and_preserves_scope(
    tmp_path: Path, offset: int | None, allow_exploratory: bool, retained: bool
) -> None:
    from invest.factor_diagnostics import diagnose_factor, qlib_dataset_frame
    from invest.factor_mining import purge_segment

    data = research_snapshot(tmp_path, length=12)
    days = data.calendar.to_pylist()
    cutoff = days[7]["close_at"]
    rows = data.bars.to_pylist()
    for row in rows:
        if row["date"] == days[6]["date"] and row["instrument"] == "SYNTH1":
            row["available_at"] = None if offset is None else cutoff + timedelta(seconds=offset)
    changed = create_snapshot(
        pa.Table.from_pylist(rows, schema=data.bars.schema),
        data.universe,
        tmp_path / "changed",
        data.spec,
        allow_exploratory=True,
    )
    factors = calculate_factors(changed, {"price": "$close"}, tmp_path / "cache")
    features, labels, _ = purge_segment(
        factors,
        forward_labels(changed, (1,)),
        days[0]["date"],
        days[7]["date"],
        1,
        snapshot=changed,
        allow_exploratory=allow_exploratory,
    )
    affected = [
        row
        for row in labels.table.to_pylist()
        if row["instrument"] == "SYNTH1" and row["date"] in (days[4]["date"], days[5]["date"])
    ]
    assert len(affected) == 2
    assert all((row["value"] is not None) == retained for row in affected)
    metadata = labels.table.schema.metadata
    assert metadata[b"label_available_by"] == cutoff.isoformat().encode()
    expected_scope = "exploratory" if offset is None and allow_exploratory else "synthetic"
    view = qlib_dataset_frame(features, labels, allow_exploratory=allow_exploratory)
    diagnostic = diagnose_factor(
        features,
        labels,
        "price",
        quantiles=4,
        max_loss=0.2,
        allow_exploratory=allow_exploratory,
    )
    assert view.attrs["invest"] == diagnostic.clean.attrs["invest"]
    for provenance in (view.attrs["invest"], diagnostic.rank_ic.attrs["invest"]):
        assert provenance["snapshot_id"] == changed.snapshot_id
        assert provenance["source"] == provenance["input_scope"] == "synthetic"
        assert provenance["scope"] == expected_scope
        assert provenance["label_timing_rejected_rows"] == (0 if retained else 2)
        assert provenance["label_unknown_timing_rows"] == (2 if offset is None else 0)
    assert diagnostic.retained_rows == (48 if retained else 46)
    if expected_scope == "exploratory":
        with pytest.raises(ValueError, match="opt-in"):
            qlib_dataset_frame(features, labels)
        with pytest.raises(ValueError, match="opt-in"):
            diagnose_factor(features, labels, "price", quantiles=4)


def test_reserved_prices_never_change_development_selection(tmp_path: Path) -> None:
    from invest.factor_mining import run_mining
    from invest.signals import load_factor_pool

    first = research_snapshot(tmp_path)
    changed = research_snapshot(tmp_path, "changed", changed_after=120)
    original = run_mining(
        mining_config(tmp_path, first), tmp_path / "first", cache_root=tmp_path / "cache"
    )
    altered = run_mining(
        mining_config(tmp_path, changed, "changed.toml"),
        tmp_path / "altered",
        cache_root=tmp_path / "cache",
    )
    assert first.snapshot_id != changed.snapshot_id
    for name in ("trials", "factors", "labels", "diagnostics"):
        assert pq.read_table(original.directory / f"{name}.parquet").equals(
            pq.read_table(altered.directory / f"{name}.parquet"), check_metadata=False
        )
    left, right = [
        load_factor_pool(result.directory / "factor_pool.parquet") for result in (original, altered)
    ]
    assert left.metadata["snapshot_id"] == right.metadata["snapshot_id"]
    assert left.table.to_pylist() == right.table.to_pylist()
    assert (
        max(pq.read_table(original.directory / "labels.parquet")["exit_at"].to_pylist()).date()
        <= first.calendar["date"][119].as_py()
    )


@pytest.mark.parametrize("source", ["synthetic", "ibkr"])
def test_reserved_data_quality_does_not_gate_development(tmp_path: Path, source: str) -> None:
    import json

    from invest.factor_mining import run_mining
    from invest.research_data import load_snapshot
    from invest.signals import load_factor_pool

    data = research_snapshot(tmp_path)
    first = create_snapshot(
        data.bars,
        data.universe,
        tmp_path / "first",
        SnapshotSpec(source, "holdout_quality_test_v1", "raw", "shares", "historical"),
    )
    rows = first.bars.to_pylist()
    for row in rows:
        if row["date"] > data.calendar["date"][119].as_py():
            row["available_at"] = None
    changed = create_snapshot(
        pa.Table.from_pylist(rows, schema=first.bars.schema),
        first.universe,
        tmp_path / "changed",
        first.spec,
        allow_exploratory=True,
    )
    results = [
        run_mining(
            mining_config(tmp_path, snapshot, f"{name}.toml"),
            tmp_path / f"study_{name}",
            cache_root=tmp_path / "cache",
        )
        for name, snapshot in (("first", first), ("changed", changed))
    ]
    assert all(result.selected == 1 for result in results)
    for name in ("trials", "factors", "labels", "diagnostics", "factor_pool"):
        assert pq.read_table(results[0].directory / f"{name}.parquet").equals(
            pq.read_table(results[1].directory / f"{name}.parquet"), check_metadata=False
        )
    expected_scope = "synthetic" if source == "synthetic" else "research"
    for snapshot, result in zip((first, changed), results, strict=True):
        pool = load_factor_pool(result.directory / "factor_pool.parquet")
        assert pool.metadata["scope"] == pool.metadata["input_scope"] == expected_scope
        assert pool.metadata["source_snapshot_id"] == snapshot.snapshot_id
        assert pool.metadata["source_scope"] == snapshot.scope
        assert json.loads(pool.metadata["source_limitations"]) == list(snapshot.limitations)
        for name in ("registration", "run"):
            table = pq.read_table(result.directory / f"{name}.parquet")
            assert table.schema.metadata[b"scope"] == expected_scope.encode()
            assert table.schema.metadata[b"source_scope"] == snapshot.scope.encode()
            assert json.loads(table.schema.metadata[b"source_limitations"]) == list(
                snapshot.limitations
            )
            assert "historical_availability_unknown" not in table["limitations"][0].as_py()
        assert load_snapshot(snapshot.directory).snapshot_id == snapshot.snapshot_id
    assert changed.limitations == ("historical_availability_unknown",)


@pytest.mark.parametrize("mode", ["constant", "complexity", "short", "incremental"])
def test_unqualified_search_is_saved_without_forced_selection(tmp_path: Path, mode: str) -> None:
    from invest.factor_mining import run_mining
    from invest.signals import load_factor_pool

    data = research_snapshot(tmp_path, flat=mode == "constant")
    config = mining_config(tmp_path, data)
    addition = {
        "constant": "",
        "complexity": "max_depth = 1\n",
        "short": "min_sessions = 40\n",
        "incremental": "min_incremental_ic = 1.0\n",
    }[mode]
    if mode == "short":
        config.write_text(config.read_text().replace("min_sessions = 8", "min_sessions = 40"))
    else:
        config.write_text(config.read_text() + addition)
    # 该样本的单因子 IC 为 1；增量门槛测试改用更苛刻的覆盖与量价候选。
    if mode == "incremental":
        config.write_text(
            config.read_text().replace('["momentum", "reversal"]', '["volume_trend"]')
        )
    result = run_mining(config, tmp_path / "study", cache_root=tmp_path / "cache")
    assert result.status == "rejected" and result.selected == 0
    assert load_factor_pool(result.directory / "factor_pool.parquet").table.num_rows == 0
    assert pq.read_table(result.directory / "signals.parquet").num_rows == 0
    trials = pq.read_table(result.directory / "trials.parquet").to_pylist()
    assert len(trials) == result.candidates and all(row["status"] == "rejected" for row in trials)
    assert all(row["reason"] for row in trials)
    assert (result.directory / "registration.parquet").is_file()
    assert (result.directory / "artifacts.parquet").is_file()


def test_mining_completes_with_empty_signals_when_no_members_remain(tmp_path: Path) -> None:
    from invest.contracts import SIGNAL_SCHEMA, SignalFrame
    from invest.factor_mining import run_mining
    from invest.signals import load_factor_pool

    data = research_snapshot(tmp_path)
    days = data.calendar["date"].to_pylist()
    members = [{**row, "end": days[118]} for row in data.universe.to_pylist()]
    expired = create_snapshot(
        data.bars,
        pa.Table.from_pylist(members, schema=data.universe.schema),
        tmp_path / "expired",
        data.spec,
    )
    result = run_mining(
        mining_config(tmp_path, expired), tmp_path / "study", cache_root=tmp_path / "cache"
    )
    assert result.status == "selected" and result.selected == 1
    pool = load_factor_pool(result.directory / "factor_pool.parquet")
    signals = SignalFrame(pq.read_table(result.directory / "signals.parquet"))
    assert signals.table.num_rows == 0
    assert signals.table.schema.equals(SIGNAL_SCHEMA, check_metadata=False)
    metadata = signals.table.schema.metadata
    assert metadata[b"snapshot_id"] == pool.metadata["snapshot_id"].encode()
    assert metadata[b"pool_id"] == pool.metadata["pool_id"].encode()
    assert metadata[b"source"] == metadata[b"scope"] == metadata[b"input_scope"] == b"synthetic"
    assert metadata[b"price_basis"] == b"raw"
    assert metadata[b"evidence_status"] == b"research_only"
    assert metadata[b"input_instruments"] == metadata[b"retained_instruments"] == b"0"
    saved = pq.read_table(result.directory / "run.parquet").to_pylist()[0]
    assert saved["status"] == "selected" and saved["completed_at"] is not None
    assert (
        "signals.parquet"
        in pq.read_table(result.directory / "artifacts.parquet")["path"].to_pylist()
    )


def test_validation_cannot_flip_training_direction(tmp_path: Path) -> None:
    from invest.factor_mining import run_mining

    changed = research_snapshot(tmp_path, changed_after=80)
    config = mining_config(tmp_path, changed)
    result = run_mining(config, tmp_path / "study", cache_root=tmp_path / "cache")
    trials = pq.read_table(result.directory / "trials.parquet").to_pylist()
    assert all(row["direction"] == (1 if row["family"] == "momentum" else -1) for row in trials)
    assert all(row["train_ic"] * row["direction"] > 0.9 for row in trials)


@pytest.mark.parametrize("source", ["alpaca", "synthetic"])
def test_known_history_and_unknown_timing_keep_their_research_scope(
    tmp_path: Path, source: str
) -> None:
    from invest.factor_mining import run_mining
    from invest.signals import generate_signals, load_factor_pool

    data = research_snapshot(tmp_path)
    unknown = data.bars.set_column(
        data.bars.schema.get_field_index("available_at"),
        data.bars.schema.field("available_at"),
        pa.nulls(data.bars.num_rows, type=data.bars.schema.field("available_at").type),
    )
    reference = create_snapshot(
        unknown,
        data.universe,
        tmp_path / "reference",
        SnapshotSpec(source, "historical_reference_v1", "raw", "shares", "historical"),
        allow_exploratory=True,
    )
    config = mining_config(tmp_path, reference)
    config.write_text(
        config.read_text().replace(
            str(data.calendar["date"][79].as_py()) + "\nfamilies",
            str(data.calendar["date"][139].as_py()) + "\nfamilies",
        )
    )
    with pytest.raises(ValueError, match="opt-in"):
        run_mining(config, tmp_path / "denied", cache_root=tmp_path / "cache")
    assert not (tmp_path / "denied").exists()
    config.write_text(config.read_text() + "allow_exploratory = true\n")
    result = run_mining(config, tmp_path / "allowed", cache_root=tmp_path / "cache")
    pool = load_factor_pool(result.directory / "factor_pool.parquet")
    assert pool.metadata["scope"] == "exploratory" and pool.metadata["source"] == source
    for name in ("trials", "diagnostics"):
        metadata = pq.read_table(result.directory / f"{name}.parquet").schema.metadata
        assert metadata[b"scope"] == b"exploratory" and metadata[b"source"] == source.encode()
        assert metadata[b"input_scope"] == reference.scope.encode()
    assert pq.read_table(result.directory / "run.parquet")["holdout_status"].to_pylist() == [
        "known_history_reserved"
    ]
    assert (
        pq.read_table(result.directory / "signals.parquet").schema.metadata[b"scope"]
        == b"exploratory"
    )
    with pytest.raises(ValueError, match="opt-in"):
        generate_signals(
            pool, reference, data.calendar["date"][119].as_py(), cache_root=tmp_path / "cache"
        )


def test_diagnostic_lags_do_not_skip_missing_sessions(tmp_path: Path) -> None:
    from invest.contracts import FactorFrame
    from invest.factor_diagnostics import describe_factor, diagnose_factor

    data = research_snapshot(tmp_path, length=20)
    factors = calculate_factors(data, {"price": "$close"}, tmp_path / "cache")
    days = data.calendar["date"].to_pylist()
    rows = factors.table.to_pylist()
    for row in rows:
        if row["date"] == days[6]:
            row["value"] = None
    factors = FactorFrame(pa.Table.from_pylist(rows, schema=factors.table.schema))
    result = diagnose_factor(
        factors, forward_labels(data, (1,)), "price", quantiles=4, max_loss=0.4
    )
    summary = describe_factor(result)
    for name in ("turnover", "rank_autocorrelation"):
        frame = summary[name]
        assert frame.loc[str(days[7])].isna().all()
        assert frame.loc[str(days[8])].notna().all()
    assert summary["turnover"].loc[str(days[8])].eq(0).all()
    assert summary["rank_autocorrelation"].loc[str(days[8])].iloc[0] == pytest.approx(1)


def test_mine_cli_uses_offline_snapshots_and_keeps_source_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import socket

    from invest.cli import main
    from invest.research_data import digest

    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Mining must not open network connections")

    data = research_snapshot(tmp_path)
    hashes = {path: digest(path) for path in data.directory.glob("*.parquet")}
    config = mining_config(tmp_path, data)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    assert main(["mine", "--config", str(config), "--output", str(tmp_path / "study")]) == 0
    assert json.loads(capsys.readouterr().out)["selected"] == 1
    assert all(digest(path) == sha for path, sha in hashes.items())
    assert not (tmp_path / "study" / "orders.parquet").exists()


def test_failed_attempt_is_preserved_when_cache_cannot_be_created(tmp_path: Path) -> None:
    from invest.factor_mining import run_mining

    data = research_snapshot(tmp_path)
    config = mining_config(tmp_path, data)
    cache = tmp_path / "blocked_cache"
    cache.write_text("occupied")
    output = tmp_path / "incomplete"
    with pytest.raises(OSError):
        run_mining(config, output, cache_root=cache)
    trials = pq.read_table(output / "trials.parquet").to_pylist()
    assert len(trials) == 1 and trials[0]["status"] == "error"
    assert trials[0]["reason"] == "execution_error" and trials[0]["error"]
    assert not (output / "run.parquet").exists()
    assert not (output / "factor_pool.parquet").exists()


@pytest.mark.parametrize("change", ["overlap", "window", "family", "unknown", "holiday"])
def test_invalid_mining_configuration_creates_no_study(tmp_path: Path, change: str) -> None:
    from invest.factor_mining import run_mining

    data = research_snapshot(tmp_path)
    config = mining_config(tmp_path, data)
    content = config.read_text()
    if change == "overlap":
        content = content.replace(
            f"validation_start = {data.calendar['date'][80].as_py()}",
            f"validation_start = {data.calendar['date'][79].as_py()}",
        )
    elif change == "window":
        content = content.replace("windows = [2, 4, 8]", "windows = [0]")
    elif change == "family":
        content = content.replace('"momentum"', '"future_return"')
    elif change == "unknown":
        content += "max_unknown = 1\n"
    else:
        content = content.replace(
            f"train_start = {data.calendar['date'][10].as_py()}", "train_start = 2022-01-01"
        )
    config.write_text(content)
    with pytest.raises(ValueError):
        run_mining(config, tmp_path / "invalid", cache_root=tmp_path / "cache")
    assert not (tmp_path / "invalid").exists()
