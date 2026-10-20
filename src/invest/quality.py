"""Explicit structural/session checks; not a certification of point-in-time data."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pyarrow as pa
import pyarrow.parquet as pq

from invest.market import read_bars

SCHEDULE_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("open_at", pa.timestamp("us", tz="UTC")),
        ("close_at", pa.timestamp("us", tz="UTC")),
        ("early_close", pa.bool_()),
    ]
)
QUALITY_SCHEMA = pa.schema(
    [
        ("status", pa.string()),
        ("check", pa.string()),
        ("date", pa.date32()),
        ("detail", pa.string()),
    ]
)


@lru_cache(maxsize=4096)
def regular_sessions(start: date, end: date) -> pa.Table:
    """Return XNYS regular sessions with UTC opens/closes, including half days."""
    if start > end:
        raise ValueError("start must be on or before end")
    # Padding permits an empty requested interval made entirely of holidays.
    calendar = xcals.get_calendar(
        "XNYS", start=start - timedelta(days=7), end=end + timedelta(days=7)
    )
    rows = []
    for session in calendar.sessions_in_range(start, end):
        opening = calendar.session_open(session).to_pydatetime()
        closing = calendar.session_close(session).to_pydatetime()
        rows.append(
            {
                "date": session.date(),
                "open_at": opening,
                "close_at": closing,
                "early_close": closing - opening < timedelta(hours=6, minutes=30),
            }
        )
    return pa.Table.from_pylist(rows, schema=SCHEDULE_SCHEMA)


def parse_as_of(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("as-of must include a timezone, e.g. 2024-07-05T21:00:00Z")
    return timestamp.astimezone(UTC)


def daily_capture_after(session: date) -> datetime:
    """Conservative capture floor, not a promise of vendor publication/finality."""
    return datetime.combine(
        session + timedelta(days=1), time(0, 15), ZoneInfo("America/New_York")
    ).astimezone(UTC)


def latest_completed_session(as_of: datetime, *, provider_daily: bool = False) -> date:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as-of must include a timezone")
    sessions = regular_sessions(as_of.date() - timedelta(days=14), as_of.date())
    completed = [
        row["date"]
        for row in sessions.to_pylist()
        if (daily_capture_after(row["date"]) if provider_daily else row["close_at"]) <= as_of
    ]
    if not completed:
        raise ValueError("No completed XNYS session found")
    return date.fromisoformat(completed[-1].isoformat())


@dataclass(frozen=True)
class QualityReport:
    checks: pa.Table

    @property
    def errors(self) -> int:
        return int(self.checks["status"].to_pylist().count("error"))

    @property
    def warnings(self) -> int:
        return int(self.checks["status"].to_pylist().count("warning"))


def audit_bars(path: Path, symbol: str, start: date, end: date, as_of: datetime) -> QualityReport:
    """Check an explicitly requested date range without filling or modifying bars."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as-of must include a timezone")
    as_of = as_of.astimezone(UTC)
    schedule = regular_sessions(start, end)
    checks: list[dict[str, object]] = []

    def add(status: str, check: str, detail: str, session: date | None = None) -> None:
        checks.append({"status": status, "check": check, "date": session, "detail": detail})

    try:
        bars = read_bars(path, symbol)
    except ValueError as exc:
        add("error", "structure", str(exc))
    else:
        add(
            "pass", "structure", "invest.bars.v1 types, prices and corporate-action fields accepted"
        )
        source = (bars.schema.metadata or {})[b"source"].decode()
        if source == "synthetic":
            add("warning", "synthetic_data", "Engineering fixture; not investment evidence")
        observed = set(bars["date"].to_pylist())
        expected = {row["date"] for row in schedule.to_pylist()}
        if not expected:
            add("error", "empty_range", "Requested range contains no XNYS sessions")
        for session in sorted(observed - expected):
            code = "outside_range" if session < start or session > end else "non_session"
            add("error", code, "Unexpected date; data is not silently trimmed", session)
        for row in schedule.to_pylist():
            session = row["date"]
            if row["close_at"] > as_of:
                add(
                    "error",
                    "unfinished_session",
                    "Session has not closed as of the requested time",
                    session,
                )
            elif session not in observed:
                add(
                    "error",
                    "missing_session",
                    "Completed session is missing; prices are not filled",
                    session,
                )
            if source == "alpaca" and daily_capture_after(session) > as_of:
                add(
                    "error",
                    "unfinished_provider_day",
                    "Alpaca daily bars require the next New York day at 00:15; "
                    "regular-session close alone is insufficient",
                    session,
                )
        if source == "alpaca":
            add(
                "warning",
                "provider_daily_semantics",
                "Provider OHLC uses trade eligibility rules; volume is not regular-session "
                "volume. Open is a historical proxy, not a verified auction fill. "
                "The capture floor does not certify finality",
            )
        for row in bars.to_pylist():
            if row["volume"] == 0:
                add(
                    "error",
                    "zero_volume",
                    "Zero-volume history cannot support the daily-open fill proxy",
                    row["date"],
                )
        add(
            "warning",
            "availability_unverified",
            "Session close is a necessary condition, not proof of provider publication or finality",
        )
        add(
            "warning",
            "events_unverified",
            "Schema checks do not prove completeness of dividends, splits or delistings",
        )
    metadata = {
        b"schema_version": b"invest.quality.v1",
        b"scope": b"structure_and_calendar_only",
        b"calendar": b"XNYS",
        b"calendar_version": version("exchange-calendars").encode(),
        b"symbol": symbol.encode(),
        b"start": start.isoformat().encode(),
        b"end": end.isoformat().encode(),
        b"as_of": as_of.isoformat().encode(),
        b"input_sha256": hashlib.sha256(path.read_bytes()).hexdigest().encode(),
    }
    return QualityReport(
        pa.Table.from_pylist(checks, schema=QUALITY_SCHEMA.with_metadata(metadata))
    )


def save_quality(report: QualityReport, output: Path) -> None:
    """Write a new report; preserve prior reports rather than silently overwriting."""
    if output.suffix.lower() != ".parquet":
        raise ValueError("Quality report output must use the .parquet extension")
    buffer = pa.BufferOutputStream()
    pq.write_table(report.checks, buffer, compression="zstd")
    contents = buffer.getvalue().to_pybytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(contents)
