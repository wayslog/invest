"""股票发行方现金分红证据；保留原除息日并显式核对 T+1 记录日规则。"""

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import decimal_value
from invest.contracts import research_schema
from invest.datasets import verify_dataset
from invest.quality import QUALITY_SCHEMA, QualityReport, regular_sessions

SOURCE_SCHEMA = research_schema(
    "stock_issuer_sources",
    [
        ("key", pa.string()),
        ("url", pa.string()),
        ("method", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("sha256", pa.string()),
        ("body", pa.binary()),
    ],
)
SOURCE_URLS = {
    "vlo_history": "https://investorvalero.com/stock-information/default.aspx",
    "nyse_exdate": "https://www.nyse.com/trade/ex-date-dividends",
    "nyse_t1_guidance": "https://www.nyse.com/publicdocs/nyse/markets/nyse/NYSE_2024_Annual_Guidance_Letter.pdf",
    "ftnt_dividend_policy": "https://investor.fortinet.com/investor-faqs",
    "ftnt_annual_2025_dividends": "https://investor.fortinet.com/node/27496/html",
    "ilmn_dividend_policy": "https://investor.illumina.com/ir-resources/investor-faqs",
    "ilmn_annual_2025_dividends": "https://investor.illumina.com/static-files/8478238c-850e-4206-9c80-d09b060ce134",
}


class DividendTable(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []
        self.current: dict[str, str] = {}
        self.field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current = {}
        elif tag == "td":
            self.field = dict(attrs).get("data-heading")
            if self.field:
                self.current[self.field] = ""

    def handle_data(self, data: str) -> None:
        if self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self.field = None
        elif tag == "tr" and self.current:
            self.rows.append({key: value.strip() for key, value in self.current.items()})
            self.current = {}


def source_text(row: dict[str, Any]) -> str:
    text = row["body"].decode("utf-8")
    text = re.sub(r"L\d+(?:@P\d+)?:\s*", "", text)
    return " ".join(re.sub(r"<[^>]*>", " ", text).split()).lower()


def read_sources(path: Path, end: date) -> dict[str, dict[str, Any]]:
    table = pq.read_table(path)
    if not table.schema.equals(SOURCE_SCHEMA, check_metadata=True):
        raise ValueError("Invalid stock issuer evidence schema")
    rows = {}
    for row in table.to_pylist():
        key = row["key"]
        if (
            key in rows
            or key not in SOURCE_URLS
            or row["url"] != SOURCE_URLS[key]
            or row["method"] not in {"http_get_decoded_entity", "web_tool_extract"}
            or not row["body"]
            or hashlib.sha256(row["body"]).hexdigest() != row["sha256"]
            or row["observed_at"] is None
            or not end < row["observed_at"].date() <= datetime.now(UTC).date()
            or row["observed_at"] > datetime.now(UTC)
        ):
            raise ValueError("Invalid stock issuer identity, body or observation")
        rows[key] = row
    return rows


def vlo_schedule(
    sources: dict[str, dict[str, Any]], start: date, end: date, bars: pa.Table
) -> tuple[dict[date, tuple[str, str]], list[dict[str, Any]]]:
    """仅限 T+1 后、提前宣告、低于股价 25% 的普通现金分红；原网页日期不覆盖。"""
    if start < date(2024, 7, 1):
        raise ValueError("Stock issuer T1 audit requires a post-transition interval")
    if not {"vlo_history", "nyse_exdate", "nyse_t1_guidance"} <= sources.keys():
        raise ValueError("Missing issuer record dates or NYSE T1 evidence")
    rule = source_text(sources["nyse_exdate"])
    transition = source_text(sources["nyse_t1_guidance"])
    if (
        "on the record date" not in rule
        or "t+1" not in rule
        or "may 29, 2024" not in transition
        or sources["vlo_history"]["method"] != "http_get_decoded_entity"
    ):
        raise ValueError("NYSE T1 basis or issuer table capture changed")
    parser = DividendTable()
    parser.feed(sources["vlo_history"]["body"].decode("utf-8"))
    prices = {row["date"]: row["close"] for row in bars.to_pylist()}
    expected = {}
    checks = []
    for row in parser.rows:
        if set(row) != {"Declared", "Ex Date", "Record", "Payable", "Amount", "Type"}:
            continue
        try:
            record = datetime.strptime(row["Record"], "%m/%d/%y").date()
        except ValueError:
            continue
        if not start <= record <= end:
            continue
        declared, reported, payable = (
            datetime.strptime(row[field], "%m/%d/%y").date()
            for field in ("Declared", "Ex Date", "Payable")
        )
        amount = decimal_value(row["Amount"])
        sessions = regular_sessions(record - timedelta(days=10), record)["date"].to_pylist()
        preceding = [day for day in prices if day < record]
        if (
            row["Type"] != "U.S. Currency"
            or len(sessions) < 2
            or sessions[-1] != record
            or reported not in sessions[-2:]
            or (record - declared).days < 10
            or payable < record
            or not preceding
            or not 0 < amount < prices[max(preceding)] / 4
            or record in expected
        ):
            raise ValueError("Issuer distribution is outside the supported normal T1 rule")
        expected[record] = (str(amount), payable.isoformat())
        checks.append(
            {
                "status": "warning" if reported != record else "pass",
                "check": "issuer_reported_ex_date",
                "date": record,
                "detail": (
                    f"Issuer display={reported}; record={record}; "
                    "effective ex-date follows captured NYSE T1 rule"
                ),
            }
        )
    if not expected:
        raise ValueError("Issuer dividend table contains no events in the requested interval")
    return expected, checks


def audit_stock_dividends(dataset: Path, source: Path) -> QualityReport:
    bars = verify_dataset(dataset)
    manifest = pq.read_table(dataset / "manifest.parquet").to_pylist()[0]
    sources = read_sources(source, manifest["end"])
    symbol = manifest["symbol"]
    checks: list[dict[str, Any]] = []
    reference: dict[date, tuple[str, str]] = {}
    if symbol == "VLO":
        reference, checks = vlo_schedule(sources, manifest["start"], manifest["end"], bars)
    elif symbol in {"FTNT", "ILMN"}:
        prefix = symbol.lower()
        keys = f"{prefix}_dividend_policy", f"{prefix}_annual_2025_dividends"
        if any(key not in sources for key in keys):
            raise ValueError("Missing issuer current policy or historical dividend statement")
        current, annual = (source_text(sources[key]) for key in keys)
        current_phrase = (
            "never declared or paid cash dividends"
            if symbol == "FTNT"
            else "currently does not issue dividends"
        )
        if current_phrase not in current or not any(
            phrase in annual
            for phrase in ("never declared or paid cash dividends", "never paid cash dividends")
        ):
            raise ValueError("Issuer zero-cash-dividend statement changed")
        if manifest["start"] < date(2024, 7, 1) or manifest["end"] > date(2026, 10, 23):
            raise ValueError("Zero dividend evidence is bounded to the verified research interval")
        checks.append(
            {
                "status": "pass",
                "check": "issuer_zero_cash_dividends",
                "date": None,
                "detail": "Captured annual statement and current policy; reconcile provider events",
            }
        )
    else:
        raise ValueError("Unsupported stock issuer evidence")
    actual = {
        row["date"]: (str(row["dividend"]), row["dividend_pay_date"].isoformat())
        for row in bars.to_pylist()
        if row["dividend"] > 0
    }
    for day in sorted(reference.keys() | actual.keys()):
        left, right = reference.get(day), actual.get(day)
        matches = (
            left is not None
            and right is not None
            and decimal_value(left[0]) == decimal_value(right[0])
            and left[1] == right[1]
        )
        checks.append(
            {
                "status": "pass" if matches else "error",
                "check": "issuer_cash_dividend",
                "date": day,
                "detail": f"Issuer amount/pay_date={left}; provider={right}",
            }
        )
    return QualityReport(pa.Table.from_pylist(checks, schema=QUALITY_SCHEMA))
