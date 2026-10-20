import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from invest.quality import (
    audit_bars,
    daily_capture_after,
    latest_completed_session,
    parse_as_of,
    regular_sessions,
    save_quality,
)
from tests.helpers import make_bars


def test_holidays_early_closes_and_exceptional_closure() -> None:
    summer = regular_sessions(date(2024, 7, 1), date(2024, 7, 5)).to_pylist()
    assert [row["date"].day for row in summer] == [1, 2, 3, 5]
    assert summer[2]["close_at"] == datetime(2024, 7, 3, 17, tzinfo=UTC)
    assert summer[2]["early_close"] is True
    fall = regular_sessions(date(2024, 11, 28), date(2024, 11, 29)).to_pylist()
    assert len(fall) == 1
    assert fall[0]["close_at"] == datetime(2024, 11, 29, 18, tzinfo=UTC)
    assert regular_sessions(date(2025, 1, 9), date(2025, 1, 9)).num_rows == 0


def test_dst_keeps_local_open_but_changes_utc() -> None:
    rows = regular_sessions(date(2024, 3, 8), date(2024, 3, 11)).to_pylist()
    assert rows[0]["open_at"] == datetime(2024, 3, 8, 14, 30, tzinfo=UTC)
    assert rows[1]["open_at"] == datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    assert not any(row["early_close"] for row in rows)


def test_range_and_timezone_are_explicit() -> None:
    with pytest.raises(ValueError, match="start"):
        regular_sessions(date(2024, 1, 3), date(2024, 1, 2))
    with pytest.raises(ValueError, match="timezone"):
        parse_as_of("2024-01-03T20:00:00")
    assert parse_as_of("2024-01-03T16:00:00-05:00") == datetime(2024, 1, 3, 21, tzinfo=UTC)


def test_valid_calendar_does_not_certify_real_data(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100, 110, 120]), path)
    report = audit_bars(
        path, "DEMO", date(2024, 1, 2), date(2024, 1, 4), datetime(2024, 1, 4, 21, tzinfo=UTC)
    )
    assert report.errors == 0
    assert report.warnings == 3
    assert {"availability_unverified", "events_unverified", "synthetic_data"} <= set(
        report.checks["check"].to_pylist()
    )
    output = tmp_path / "quality.parquet"
    save_quality(report, output)
    assert pq.read_table(output).equals(report.checks, check_metadata=True)
    with pytest.raises(FileExistsError):
        save_quality(report, output)


@pytest.mark.parametrize("indices", [[1, 2], [0, 2], [0, 1]])
def test_missing_sessions_at_either_edge_or_middle_fail(tmp_path: Path, indices: list[int]) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100, 110, 120]).take(indices), path)
    report = audit_bars(
        path, "DEMO", date(2024, 1, 2), date(2024, 1, 4), datetime(2024, 1, 5, tzinfo=UTC)
    )
    assert report.errors == 1
    assert "missing_session" in report.checks["check"].to_pylist()


def test_unfinished_bar_is_rejected_at_half_day_close(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100], updates={0: {"date": date(2024, 11, 29)}}), path)
    report = audit_bars(
        path,
        "DEMO",
        date(2024, 11, 29),
        date(2024, 11, 29),
        datetime(2024, 11, 29, 17, 59, tzinfo=UTC),
    )
    assert "unfinished_session" in report.checks["check"].to_pylist()
    assert report.errors == 1
    closed = audit_bars(
        path,
        "DEMO",
        date(2024, 11, 29),
        date(2024, 11, 29),
        datetime(2024, 11, 29, 18, tzinfo=UTC),
    )
    assert closed.errors == 0
    assert "availability_unverified" in closed.checks["check"].to_pylist()


def test_outside_range_and_zero_volume_are_reported_without_changing_data(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    bars = make_bars([100, 110, 120], updates={0: {"volume": 0}})
    pq.write_table(bars, path)
    original = path.read_bytes()
    report = audit_bars(
        path, "DEMO", date(2024, 1, 3), date(2024, 1, 4), datetime(2024, 1, 5, tzinfo=UTC)
    )
    assert report.errors == 2
    assert {"outside_range", "zero_volume"} <= set(report.checks["check"].to_pylist())
    assert path.read_bytes() == original


def test_audit_requires_an_aware_timestamp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        audit_bars(
            tmp_path / "unused.parquet",
            "DEMO",
            date(2024, 1, 2),
            date(2024, 1, 3),
            datetime(2024, 1, 4),
        )


def test_holiday_record_is_not_accepted_as_a_trading_day(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100], updates={0: {"date": date(2024, 7, 4)}}), path)
    report = audit_bars(
        path, "DEMO", date(2024, 7, 4), date(2024, 7, 5), datetime(2024, 7, 6, tzinfo=UTC)
    )
    assert {"non_session", "missing_session"} <= set(report.checks["check"].to_pylist())


def test_invalid_schema_is_saved_as_a_failed_check(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    pq.write_table(make_bars([100, 110]).drop(["volume"]), path)
    report = audit_bars(
        path, "DEMO", date(2024, 1, 2), date(2024, 1, 3), datetime(2024, 1, 4, tzinfo=UTC)
    )
    assert report.errors == 1
    assert report.checks["check"].to_pylist() == ["structure"]


def test_cli_persists_failure_and_returns_nonzero(tmp_path: Path) -> None:
    path, output = tmp_path / "bars.parquet", tmp_path / "quality.parquet"
    pq.write_table(make_bars([100, 110]).slice(0, 1), path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest",
            "audit",
            "--data",
            str(path),
            "--symbol",
            "DEMO",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--as-of",
            "2024-01-04T00:00:00Z",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert not result.stderr
    assert json.loads(result.stdout)["errors"] == 1
    assert "missing_session" in pq.read_table(output)["check"].to_pylist()


@pytest.mark.parametrize(
    ("session", "floor"),
    [
        (date(2024, 3, 8), datetime(2024, 3, 9, 5, 15, tzinfo=UTC)),
        (date(2024, 3, 11), datetime(2024, 3, 12, 4, 15, tzinfo=UTC)),
        (date(2024, 7, 3), datetime(2024, 7, 4, 4, 15, tzinfo=UTC)),
        (date(2024, 11, 29), datetime(2024, 11, 30, 5, 15, tzinfo=UTC)),
    ],
)
def test_provider_day_cannot_be_admitted_at_regular_close(
    tmp_path: Path, session: date, floor: datetime
) -> None:
    from datetime import timedelta

    bars = make_bars([100], updates={0: {"date": session}})
    bars = bars.replace_schema_metadata({**(bars.schema.metadata or {}), b"source": b"alpaca"})
    path = tmp_path / "bars.parquet"
    pq.write_table(bars, path)
    assert daily_capture_after(session) == floor
    for observed in [
        regular_sessions(session, session)["close_at"][0].as_py(),
        floor - timedelta(microseconds=1),
    ]:
        report = audit_bars(path, "DEMO", session, session, observed)
        assert report.errors == 1
        assert "unfinished_provider_day" in report.checks["check"].to_pylist()
        assert latest_completed_session(observed, provider_daily=True) < session
    admitted = audit_bars(path, "DEMO", session, session, floor)
    assert admitted.errors == 0
    assert "availability_unverified" in admitted.checks["check"].to_pylist()
    assert latest_completed_session(floor, provider_daily=True) == session
