"""历史基金原件按可得上界选择；缺周输出缺口，不向过去回填当前名单。"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.contracts import research_schema
from invest.quality import regular_sessions
from invest.spy_data import parse_holdings, parse_qqq_holdings

CATALOG_SCHEMA = research_schema(
    "fund_membership_sources",
    [
        ("fund", pa.string()),
        ("source_kind", pa.string()),
        ("url", pa.string()),
        ("captured_at", pa.timestamp("us", tz="UTC")),
        ("known_by", pa.timestamp("us", tz="UTC")),
        ("archive_sha1", pa.string()),
        ("sha256", pa.string()),
        ("body", pa.binary()),
    ],
)
COVERAGE_SCHEMA = research_schema(
    "weekly_membership_coverage",
    [
        ("week", pa.string()),
        ("fund", pa.string()),
        ("price_as_of", pa.date32()),
        ("decision_at", pa.timestamp("us", tz="UTC")),
        ("first_execution_session", pa.date32()),
        ("status", pa.string()),
        ("reason", pa.string()),
        ("membership_as_of", pa.date32()),
        ("known_by", pa.timestamp("us", tz="UTC")),
        ("source_id", pa.string()),
        ("members", pa.int64()),
    ],
)
MEMBERS_SCHEMA = research_schema(
    "weekly_fund_members",
    [
        ("week", pa.string()),
        ("fund", pa.string()),
        ("instrument", pa.string()),
        ("symbol", pa.string()),
        ("source_id", pa.string()),
        ("membership_as_of", pa.date32()),
        ("known_by", pa.timestamp("us", tz="UTC")),
    ],
)


@dataclass(frozen=True)
class FundSnapshot:
    fund: str
    as_of: date
    known_by: datetime
    source_id: str
    members: tuple[tuple[str, str], ...]


def weekly_schedule(start: date, end: date) -> list[dict[str, Any]]:
    sessions = regular_sessions(start - timedelta(days=14), end).to_pylist()
    days = [row["date"] for row in sessions]
    if start not in days or end not in days or start > end:
        raise ValueError("Weekly evaluation boundaries must be trading sessions")
    seen: set[tuple[int, int]] = set()
    result = []
    for day in (day for day in days if day >= start):
        week = day.isocalendar()[:2]
        if week in seen:
            continue
        seen.add(week)
        monday = day - timedelta(days=day.weekday())
        decision = datetime.combine(monday - timedelta(days=1), time(2), tzinfo=UTC)
        previous = days[days.index(day) - 1]
        # 首次从周中启动时，不能偷偷把首次交易前一天当作该周周末。
        if sessions[days.index(previous)]["close_at"] > decision:
            raise ValueError("Weekly evaluation must start on the first session of its week")
        result.append(
            {
                "week": f"{week[0]}-W{week[1]:02d}",
                "price_as_of": previous,
                "decision_at": decision,
                "first_execution_session": day,
            }
        )
    return result


def read_membership_catalog(path: Path, *, synthetic: bool = False) -> list[FundSnapshot]:
    table = pq.read_table(path)
    if not table.schema.equals(CATALOG_SCHEMA, check_metadata=True):
        raise ValueError("Invalid historical membership source schema")
    result = []
    seen = set()
    for row in table.to_pylist():
        if (
            row["fund"] not in {"SPY", "QQQ"}
            or not row["body"]
            or hashlib.sha256(row["body"]).hexdigest() != row["sha256"]
            or row["known_by"] is None
            or row["captured_at"] is None
            or row["known_by"] > row["captured_at"]
            or row["captured_at"] > datetime.now(UTC)
            or (row["fund"], row["sha256"], row["known_by"]) in seen
        ):
            raise ValueError("Invalid membership source bytes or time evidence")
        seen.add((row["fund"], row["sha256"], row["known_by"]))
        kind = row["source_kind"]
        if kind == "synthetic" and synthetic:
            data = json.loads(row["body"])
            if data["fund"] != row["fund"]:
                raise ValueError("Synthetic fund identity mismatch")
            day = date.fromisoformat(data["as_of"])
            members = tuple((s, s) for s in data["members"])
        elif kind in {"issuer_capture", "issuer_archive"} and not synthetic:
            if kind == "issuer_capture":
                if row["known_by"] != row["captured_at"] or not row["url"].startswith(
                    (
                        "https://www.ssga.com/",
                        "https://dng-api.invesco.com/",
                    )
                ):
                    raise ValueError("Direct issuer capture cannot backdate availability")
            else:
                match = re.match(
                    r"https://web\.archive\.org/web/(\d{14})(?:if_|id_)?/https://"
                    r"(?:www\.ssga\.com|dng-api\.invesco\.com)/",
                    row["url"],
                )
                if not match or (
                    datetime.strptime(match[1], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                    != row["known_by"]
                    or base64.b32encode(hashlib.sha1(row["body"]).digest()).decode().rstrip("=")
                    != row["archive_sha1"]
                ):
                    raise ValueError("Historical archive payload and capture evidence disagree")
            parsed = (parse_holdings if row["fund"] == "SPY" else parse_qqq_holdings)(row["body"])
            records = parsed.to_pylist()
            dates = {r["membership_as_of"] for r in records}
            if len(dates) != 1:
                raise ValueError("Fund snapshot requires one holdings date")
            day = dates.pop()
            members = tuple((r["instrument"], r["symbol"]) for r in records if r["eligible"])
        else:
            raise ValueError("Membership source must match the declared real or synthetic scope")
        if (
            not members
            or len({m[0] for m in members}) != len(members)
            or day > row["known_by"].date()
            or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) for key, _ in members)
        ):
            raise ValueError("Invalid complete fund membership")
        result.append(FundSnapshot(row["fund"], day, row["known_by"], row["sha256"], members))
    return result


def membership_coverage(
    sources: list[FundSnapshot], start: date, end: date, *, max_age_sessions: int = 3
) -> tuple[pa.Table, pa.Table]:
    if type(max_age_sessions) is not int or max_age_sessions < 0:
        raise ValueError("Invalid membership age limit")
    rows: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    for week in weekly_schedule(start, end):
        for fund in ("SPY", "QQQ"):
            available = [
                s
                for s in sources
                if s.fund == fund
                and s.as_of <= week["price_as_of"]
                and s.known_by <= week["decision_at"]
            ]
            chosen = max(available, key=lambda s: (s.as_of, s.known_by, s.source_id), default=None)
            age = (
                regular_sessions(chosen.as_of, week["price_as_of"]).num_rows - 1 if chosen else None
            )
            ready = chosen is not None and age is not None and age <= max_age_sessions
            rows.append(
                {
                    **week,
                    "fund": fund,
                    "status": "ready" if ready else "blocked",
                    "reason": ""
                    if ready
                    else "historical_membership_stale"
                    if chosen
                    else "historical_membership_missing",
                    "membership_as_of": chosen.as_of if chosen else None,
                    "known_by": chosen.known_by if chosen else None,
                    "source_id": chosen.source_id if chosen else None,
                    "members": len(chosen.members) if ready and chosen else 0,
                }
            )
            if ready and chosen:
                members.extend(
                    {
                        "week": week["week"],
                        "fund": fund,
                        "instrument": key,
                        "symbol": symbol,
                        "source_id": chosen.source_id,
                        "membership_as_of": chosen.as_of,
                        "known_by": chosen.known_by,
                    }
                    for key, symbol in chosen.members
                )
    return (
        pa.Table.from_pylist(rows, schema=COVERAGE_SCHEMA),
        pa.Table.from_pylist(members, schema=MEMBERS_SCHEMA),
    )
