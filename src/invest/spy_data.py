"""SPY 及可选 QQQ 持仓与批量行情捕获；仅供关注列表，不授予成交准入。"""

import hashlib
import html
import json
import math
import os
import re
import shutil
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.request import Request, build_opener
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import (
    NEW_YORK,
    RAW_SCHEMA,
    NoRedirect,
    RequestData,
    authenticated_request,
    decode,
)
from invest.contracts import RESEARCH_BARS, research_schema
from invest.quality import daily_capture_after, regular_sessions
from invest.research_artifacts import seal_artifacts, verify_artifacts

HOLDINGS_URL = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
)
QQQ_HOLDINGS_URL = (
    "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund"
    "?idType=ticker&interval=monthly&productType=ETF"
)
HOLDINGS_SCHEMA = research_schema(
    "spy_members",
    [
        ("symbol", pa.string()),
        ("instrument", pa.string()),
        ("name", pa.string()),
        ("sector", pa.string()),
        ("weight", pa.float64()),
        ("membership_as_of", pa.date32()),
        ("eligible", pa.bool_()),
        ("exclusion_reason", pa.string()),
    ],
)
FUND_HOLDINGS_SCHEMA = research_schema(
    "fund_members",
    [(field.name, field.type) for field in HOLDINGS_SCHEMA]
    + [
        ("funds", pa.list_(pa.field("element", pa.string()))),
        ("spy_membership_as_of", pa.date32()),
        ("qqq_membership_as_of", pa.date32()),
        ("spy_weight", pa.float64()),
        ("qqq_weight", pa.float64()),
    ],
)


def market_request(credentials: Path | None = None) -> RequestData:
    """仅加载指定文件中的两个 Alpaca 字段；不执行配置、不输出或复制凭据。"""
    if credentials is None:
        return authenticated_request()
    names = {
        "ALPACA_API_KEY_ID": "APCA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY": "APCA_API_SECRET_KEY",
        "APCA_API_KEY_ID": "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY": "APCA_API_SECRET_KEY",
    }
    values = {}
    for line in credentials.read_text().splitlines():
        key, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and key in names:
            values[names[key]] = value.strip().strip('"').strip("'")
    if set(values) != set(names.values()) or not all(values.values()):
        raise ValueError("Credentials file is missing Alpaca key fields")
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        return authenticated_request()
    finally:
        for key, original in previous.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def parse_holdings(body: bytes) -> pa.Table:
    """权重由百分数转比例；不把现金、多股类或未知行业混为普通股票。"""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(body)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 32 * 1024 * 1024:
            raise ValueError("Holdings workbook exceeds size limit")
        strings = (
            [
                "".join(node.itertext())
                for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
            if "xl/sharedStrings.xml" in archive.namelist()
            else []
        )
        grid: dict[str, str] = {}
        for cell in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall(".//s:c", ns):
            value = cell.find("s:v", ns)
            if cell.get("t") == "inlineStr":
                inline = cell.find("s:is", ns)
                if inline is None:
                    raise ValueError("Invalid inline workbook string")
                grid[cell.attrib["r"]] = "".join(inline.itertext())
            elif value is not None and value.text is not None:
                grid[cell.attrib["r"]] = (
                    strings[int(value.text)] if cell.get("t") == "s" else value.text
                ).strip()
    if grid.get("B2") != "SPY" or any(
        grid.get(f"{column}5") != name
        for column, name in {
            "A": "Name",
            "B": "Ticker",
            "E": "Weight",
            "F": "Sector",
            "H": "Local Currency",
        }.items()
    ):
        raise ValueError("Unexpected SPY holdings workbook layout")
    as_of = datetime.strptime(grid["B3"], "As of %d-%b-%Y").date()
    rows: list[dict[str, Any]] = []
    for row in range(6, max(int(re.sub(r"\D", "", k)) for k in grid) + 1):
        symbol = grid.get(f"B{row}", "")
        if not symbol:
            continue
        eligible = bool(re.fullmatch(r"[A-Z][A-Z0-9.]{0,12}", symbol)) and grid.get(f"H{row}") in {
            None,
            "",
            "USD",
        }
        weight = float(grid[f"E{row}"]) / 100
        if not 0 < weight <= 1:
            raise ValueError("Invalid SPY constituent weight")
        rows.append(
            {
                "symbol": symbol,
                "instrument": symbol.replace(".", "_") if eligible else f"HOLDING_{row}",
                "name": grid[f"A{row}"],
                "sector": None if grid.get(f"F{row}") in {None, "", "-"} else grid[f"F{row}"],
                "weight": weight,
                "membership_as_of": as_of,
                "eligible": eligible,
                "exclusion_reason": "" if eligible else "cash_or_unsupported_security",
            }
        )
    if len({r["instrument"] for r in rows}) != len(rows) or not rows:
        raise ValueError("Empty or duplicate SPY constituents")
    if not 0.95 <= sum(r["weight"] for r in rows) <= 1.01:
        raise ValueError("SPY constituent weight coverage is incomplete")
    return pa.Table.from_pylist(rows, schema=HOLDINGS_SCHEMA).sort_by("symbol")


def parse_qqq_holdings(body: bytes) -> pa.Table:
    """仅将股票和存托凭证纳入；现金、期货及抵销项保留但排除。"""
    payload = decode(body)
    values = payload.get("holdings")
    if (
        payload.get("cusip") != "QQQ"
        or not isinstance(values, list)
        or not values
        or payload.get("totalNumberOfHoldings") != len(values)
    ):
        raise ValueError("Invalid QQQ holdings identity or count")
    day = date.fromisoformat(payload["effectiveBusinessDate"])
    rows = []
    for index, value in enumerate(values):
        symbol = value.get("ticker") or ""
        eligible = (
            value.get("securityTypeCode") in {"COM", "ADR", "DRNY"}
            and bool(re.fullmatch(r"[A-Z][A-Z0-9.]{0,12}", symbol))
            and value.get("currency") in {None, "", "USD"}
        )
        raw_weight = value.get("percentageOfTotalNetAssets")
        weight = float(raw_weight) / 100 if raw_weight is not None else None
        if weight is not None and (not math.isfinite(weight) or abs(weight) > 1):
            raise ValueError("Invalid QQQ holding weight")
        if eligible and (weight is None or weight <= 0):
            raise ValueError("Missing or nonpositive QQQ equity weight")
        rows.append(
            {
                "symbol": symbol,
                "instrument": symbol.replace(".", "_") if eligible else f"QQQ_HOLDING_{index}",
                "name": html.unescape(value["issuerName"]),
                "sector": None,
                "weight": weight,
                "membership_as_of": day,
                "eligible": eligible,
                "exclusion_reason": "" if eligible else "cash_or_unsupported_security",
            }
        )
    if len({r["instrument"] for r in rows}) != len(rows):
        raise ValueError("Duplicate QQQ equity constituents")
    if not 0.95 <= sum(r["weight"] for r in rows if r["eligible"]) <= 1.01:
        raise ValueError("QQQ equity weight coverage is incomplete")
    return pa.Table.from_pylist(rows, schema=HOLDINGS_SCHEMA).sort_by("instrument")


def combine_holdings(spy: pa.Table, qqq: pa.Table | None = None) -> pa.Table:
    """共同证券只保留一行；分别保留基金成员日期和权重，不相加权重。"""
    combined: dict[str, dict[str, Any]] = {}
    for fund, table in (("SPY", spy), ("QQQ", qqq)):
        if table is None:
            continue
        for member in table.to_pylist():
            key = member["instrument"]
            if key not in combined:
                combined[key] = {**member, "funds": []}
            row = combined[key]
            if row["symbol"] != member["symbol"] or row["eligible"] != member["eligible"]:
                raise ValueError("Conflicting fund security identities")
            row["funds"].append(fund)
            row[f"{fund.lower()}_membership_as_of"] = member["membership_as_of"]
            row[f"{fund.lower()}_weight"] = member["weight"]
            row["membership_as_of"] = max(row["membership_as_of"], member["membership_as_of"])
            if qqq is not None:
                row["weight"] = None
    return pa.Table.from_pylist(list(combined.values()), schema=FUND_HOLDINGS_SCHEMA).sort_by(
        "instrument"
    )


def frozen_holdings_sources(path: Path) -> dict[str, dict[str, Any]]:
    """接受已保存的发行方原始响应；重放使用原采集时刻，不重标日期。"""
    table = pq.read_table(path)
    expected = {"SPY": HOLDINGS_URL, "QQQ": QQQ_HOLDINGS_URL}
    sources = {}
    for row in table.to_pylist():
        fund = row.get("fund")
        body = row.get("body")
        captured = row.get("captured_at")
        if (
            fund not in expected
            or fund in sources
            or row.get("url") != expected[fund]
            or row.get("final_url") != expected[fund]
            or row.get("status") != 200
            or not isinstance(body, bytes)
            or len(body) > 16 * 1024 * 1024
            or hashlib.sha256(body).hexdigest() != row.get("sha256")
            or not isinstance(captured, datetime)
            or captured.tzinfo is None
            or captured > datetime.now(UTC)
        ):
            raise ValueError("Invalid frozen official holdings source")
        sources[fund] = row
    if "SPY" not in sources:
        raise ValueError("Frozen holdings must include SPY")
    return sources


def validate_membership_dates(holdings: pa.Table, end: date) -> None:
    for column in ("spy_membership_as_of", "qqq_membership_as_of"):
        for day in set(holdings[column].to_pylist()) - {None}:
            if day > end or regular_sessions(day, end).num_rows > 4:
                raise ValueError("Fund membership is future dated or more than three sessions old")


def capture_spy_inputs(
    output: Path,
    end: date,
    request: RequestData,
    *,
    holdings_body: bytes | None = None,
    holdings_sources: Path | None = None,
) -> dict[str, Any]:
    """新目录中保存每一页，失败也保留证据；请求中没有任何账户或订单端点。"""
    now = datetime.now(UTC)
    if now < daily_capture_after(end) or not regular_sessions(end, end).num_rows:
        raise ValueError("Funnel capture requires a completed daily session")
    if holdings_sources is not None and holdings_body is not None:
        raise ValueError("Specify only one holdings source")
    sources = frozen_holdings_sources(holdings_sources) if holdings_sources is not None else {}
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    sequence = 0

    def save(
        kind: str,
        endpoint: str,
        query: dict[str, str],
        body: bytes,
        received_at: datetime | None = None,
    ) -> None:
        nonlocal sequence
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "kind": kind,
                        "endpoint": endpoint,
                        "query": json.dumps(query, sort_keys=True),
                        "received_at": received_at or datetime.now(UTC),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "body": body,
                    }
                ],
                schema=RAW_SCHEMA,
            ),
            raw / f"{sequence:04d}.parquet",
            compression="zstd",
        )
        sequence += 1

    try:
        if sources:
            holdings_body = sources["SPY"]["body"]
            assert holdings_sources is not None
            shutil.copy2(holdings_sources, output / "holdings-sources.parquet")
        if holdings_body is None:
            with build_opener(NoRedirect()).open(Request(HOLDINGS_URL), timeout=30) as response:
                holdings_body = response.read(16 * 1024 * 1024 + 1)
        if len(holdings_body) > 16 * 1024 * 1024:
            raise ValueError("Oversized holdings response")
        save("holdings", HOLDINGS_URL, {}, holdings_body, sources.get("SPY", {}).get("captured_at"))
        qqq = None
        if "QQQ" in sources:
            source = sources["QQQ"]
            save("qqq_holdings", QQQ_HOLDINGS_URL, {}, source["body"], source["captured_at"])
            qqq = parse_qqq_holdings(source["body"])
        holdings = combine_holdings(parse_holdings(holdings_body), qqq)
        validate_membership_dates(holdings, end)
        symbols = sorted({r["symbol"] for r in holdings.to_pylist() if r["eligible"]} | {"SPY"})
        start = end - timedelta(days=420)
        for adjustment in ("raw", "split"):
            query = {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "feed": "sip",
                "adjustment": adjustment,
                "start": datetime.combine(start, time(), NEW_YORK).isoformat(),
                "end": (
                    datetime.combine(end + timedelta(days=1), time(), NEW_YORK)
                    - timedelta(microseconds=1)
                ).isoformat(),
                "asof": end.isoformat(),
                "sort": "asc",
                "limit": "10000",
            }
            seen: set[str] = set()
            for _ in range(1000):
                body = request("/v2/stocks/bars", query.copy())
                save(adjustment, "/v2/stocks/bars", query, body)
                page = decode(body)
                token = page["next_page_token"]
                if token is None:
                    break
                if not isinstance(token, str) or not token or token in seen:
                    raise ValueError("Invalid or repeated market pagination")
                seen.add(token)
                query["page_token"] = token
            else:
                raise ValueError("Market pagination limit reached")
        read_spy_inputs(output, end, sealed=False)
    finally:
        seal_artifacts(output)
    return {"inputs": output, "status": "captured", "members": holdings.num_rows, "as_of": end}


def read_spy_inputs(
    directory: Path, end: date, *, sealed: bool = True
) -> tuple[pa.Table, dict[str, pa.Table]]:
    """离线重放请求和原字节；不把完整行情分页冒充公司行动完整证明。"""
    if sealed:
        verify_artifacts(directory)
    pages = []
    for path in sorted((directory / "raw").glob("*.parquet")):
        table = pq.read_table(path)
        if table.num_rows != 1 or not table.schema.equals(RAW_SCHEMA, check_metadata=True):
            raise ValueError("Invalid market capture schema")
        pages.extend(table.to_pylist())
    if not pages or pages[0]["kind"] != "holdings" or pages[0]["endpoint"] != HOLDINGS_URL:
        raise ValueError("Missing official holdings capture")
    if sum(page["kind"] == "holdings" for page in pages) != 1:
        raise ValueError("Duplicate holdings captures")
    for page in pages:
        if (
            hashlib.sha256(page["body"]).hexdigest() != page["sha256"]
            or page["received_at"] is None
            or page["received_at"] > datetime.now(UTC)
        ):
            raise ValueError("Source capture hash or timestamp changed")
    qqq_pages = [p for p in pages if p["kind"] == "qqq_holdings"]
    if len(qqq_pages) > 1 or (qqq_pages and qqq_pages[0]["endpoint"] != QQQ_HOLDINGS_URL):
        raise ValueError("Invalid or duplicate official QQQ holdings capture")
    source_path = directory / "holdings-sources.parquet"
    if source_path.exists():
        sources = frozen_holdings_sources(source_path)
        captured = {"SPY": pages[0], **({"QQQ": qqq_pages[0]} if qqq_pages else {})}
        if set(sources) != set(captured) or any(
            sources[fund]["body"] != captured[fund]["body"]
            or sources[fund]["captured_at"] != captured[fund]["received_at"]
            for fund in sources
        ):
            raise ValueError("Frozen fund sources differ from captured holdings")
    holdings = combine_holdings(
        parse_holdings(pages[0]["body"]),
        parse_qqq_holdings(qqq_pages[0]["body"]) if qqq_pages else None,
    )
    validate_membership_dates(holdings, end)
    expected_symbols = {r["symbol"] for r in holdings.to_pylist() if r["eligible"]} | {"SPY"}
    results = {}
    groups = {"holdings", "raw", "split"} | ({"qqq_holdings"} if qqq_pages else set())
    if {p["kind"] for p in pages} != groups:
        raise ValueError("Missing or unexpected market capture groups")
    for kind in ("raw", "split"):
        subset = [p for p in pages if p["kind"] == kind]
        expected = None
        rows = []
        seen: set[tuple[str, date]] = set()
        tokens: set[str] = set()
        for index, page in enumerate(subset):
            query = json.loads(page["query"])
            if (
                page["endpoint"] != "/v2/stocks/bars"
                or query.get("adjustment") != kind
                or query.get("feed") != "sip"
                or query.get("timeframe") != "1Day"
                or set(query.get("symbols", "").split(",")) != expected_symbols
                or query.get("asof") != end.isoformat()
                or (index == 0 and "page_token" in query)
                or (index > 0 and query != expected)
            ):
                raise ValueError("Market request identity or pagination changed")
            payload = decode(page["body"])
            token = payload["next_page_token"]
            if token is None:
                if index != len(subset) - 1:
                    raise ValueError("Unexpected page after completion")
            elif not isinstance(token, str) or not token or token in tokens:
                raise ValueError("Invalid market pagination token")
            else:
                tokens.add(token)
            expected = {**query, "page_token": token} if token else None
            if set(payload["bars"]) - expected_symbols:
                raise ValueError("Unexpected market symbols")
            for symbol, values in payload["bars"].items():
                for value in values:
                    stamp = datetime.fromisoformat(value["t"])
                    if stamp.tzinfo is None:
                        raise ValueError("Daily timestamp must include timezone")
                    local = stamp.astimezone(NEW_YORK)
                    key = symbol, local.date()
                    if (
                        local.time() != time()
                        or not end - timedelta(days=420) <= local.date() <= end
                        or key in seen
                    ):
                        raise ValueError("Duplicate or invalid market daily timestamp")
                    if page["received_at"] < daily_capture_after(local.date()):
                        raise ValueError("Premature daily market capture")
                    seen.add(key)
                    rows.append(
                        {
                            "date": local.date(),
                            "instrument": symbol.replace(".", "_"),
                            **{
                                field: Decimal(str(value[key]))
                                for field, key in (
                                    ("open", "o"),
                                    ("high", "h"),
                                    ("low", "l"),
                                    ("close", "c"),
                                    ("volume", "v"),
                                )
                            },
                            "available_at": None,
                            "captured_at": page["received_at"],
                        }
                    )
        if expected is not None or not rows:
            raise ValueError("Incomplete or empty market capture")
        results[kind] = pa.Table.from_pylist(rows, schema=RESEARCH_BARS)
    return holdings, results
