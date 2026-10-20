"""Independent State Street cash-distribution evidence, archived entirely in Parquet."""

import hashlib
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import NoRedirect, decimal_value
from invest.datasets import verify_dataset
from invest.quality import QUALITY_SCHEMA, QualityReport

SOURCE_URL = (
    "https://www.ssga.com/library-content/products/fund-data/etfs/us/"
    "spdr-etf-historical-distributions.xlsx"
)
SOURCE_SCHEMA = pa.schema(
    [
        ("url", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("sha256", pa.string()),
        ("body", pa.binary()),
    ],
    metadata={b"schema_version": b"invest.research.source.v1"},
)
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def capture_distributions(output: Path) -> None:
    """Capture the public issuer file without API credentials or local spreadsheet inputs."""
    if output.suffix.lower() != ".parquet":
        raise ValueError("Source capture must use the .parquet extension")
    if output.exists():
        raise FileExistsError(output)
    try:
        with build_opener(NoRedirect()).open(Request(SOURCE_URL), timeout=30) as response:
            body = response.read(16 * 1024 * 1024 + 1)
    except HTTPError as exc:
        raise ValueError(f"Issuer HTTP {exc.code}; source capture not saved") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Issuer network/TLS request failed") from None
    if not body or len(body) > 16 * 1024 * 1024:
        raise ValueError("Invalid issuer response size")
    table = pa.Table.from_pylist(
        [
            {
                "url": SOURCE_URL,
                "observed_at": datetime.now(UTC),
                "sha256": hashlib.sha256(body).hexdigest(),
                "body": body,
            }
        ],
        schema=SOURCE_SCHEMA,
    )
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression="zstd")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(buffer.getvalue().to_pybytes())


def issuer_dividends(
    body: bytes, symbol: str, start: date, end: date
) -> dict[date, tuple[str, str]]:
    """Read exact amounts and payable dates; fail on layout changes or capital gains."""
    selected: dict[date, tuple[str, str]] = {}
    try:
        with ZipFile(BytesIO(body)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 32 * 1024 * 1024:
                raise ValueError("Issuer workbook exceeds the expanded size limit")
            strings = [
                "".join(node.itertext())
                for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
            rows = ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall(
                "s:sheetData/s:row", NS
            )
            for index, row in enumerate(rows):
                cells: dict[str, str] = {}
                for cell in row:
                    value = cell.find("s:v", NS)
                    if value is not None and value.text is not None:
                        column = "".join(c for c in cell.attrib["r"] if c.isalpha())
                        cells[column] = (
                            strings[int(value.text)] if cell.get("t") == "s" else value.text
                        ).strip()
                if index == 0:
                    expected = {
                        "B": "TICKER",
                        "D": "EX-DATE",
                        "F": "PAYABLE DATE",
                        "G": "DIVIDEND ($)",
                        "H": "SHORT TERM CAPITAL GAIN ($)",
                        "I": "LONG TERM CAPITAL GAIN ($)",
                    }
                    if any(cells.get(key) != value for key, value in expected.items()):
                        raise ValueError("Unsupported issuer workbook layout")
                if cells.get("B") != symbol:
                    continue
                ex_date = datetime.strptime(cells["D"], "%m/%d/%Y").date()
                if not start <= ex_date <= end:
                    continue
                if ex_date in selected:
                    raise ValueError("Duplicate issuer distribution date")
                if any(decimal_value(cells.get(c) or "0") != 0 for c in ["H", "I"]):
                    raise ValueError("Capital-gain distributions require separate treatment")
                amount = decimal_value(cells["G"])
                payment = datetime.strptime(cells["F"], "%m/%d/%Y").date()
                if amount <= 0 or payment < ex_date:
                    raise ValueError("Invalid issuer dividend amount/payment date")
                selected[ex_date] = (str(amount), payment.isoformat())
    except (BadZipFile, ET.ParseError, KeyError, IndexError) as exc:
        raise ValueError("Invalid/incomplete issuer workbook") from exc
    if not selected:
        raise ValueError("No issuer events in range; this cannot certify an empty event history")
    return selected


def audit_dividends(dataset: Path, source: Path) -> QualityReport:
    """Compare the full event set, amounts and pay dates without rewriting the dataset."""
    bars = verify_dataset(dataset)
    manifest = pq.read_table(dataset / "manifest.parquet").to_pylist()[0]
    capture = pq.read_table(source)
    if not capture.schema.equals(SOURCE_SCHEMA, check_metadata=True) or capture.num_rows != 1:
        raise ValueError("Invalid issuer source capture")
    row = capture.to_pylist()[0]
    if (
        row["url"] != SOURCE_URL
        or not isinstance(row["body"], bytes)
        or hashlib.sha256(row["body"]).hexdigest() != row["sha256"]
        or row["observed_at"] is None
        or not manifest["end"] < row["observed_at"].date() <= datetime.now(UTC).date()
        or row["observed_at"] > datetime.now(UTC)
    ):
        raise ValueError("Issuer capture identity, checksum or observation time is invalid")
    reference = issuer_dividends(
        row["body"], manifest["symbol"], manifest["start"], manifest["end"]
    )
    actual = {
        bar["date"]: (str(bar["dividend"]), bar["dividend_pay_date"].isoformat())
        for bar in bars.to_pylist()
        if bar["dividend"] > 0
    }
    checks = []
    for session in sorted(reference.keys() | actual.keys()):
        expected, observed = reference.get(session), actual.get(session)
        matches = (
            expected is not None
            and observed is not None
            and decimal_value(expected[0]) == decimal_value(observed[0])
            and expected[1] == observed[1]
        )
        checks.append(
            {
                "status": "pass" if matches else "error",
                "check": "issuer_cash_dividend",
                "date": session,
                "detail": f"Issuer amount/pay_date={expected}; provider={observed}",
            }
        )
    metadata = {
        b"schema_version": b"invest.dividend_audit.v1",
        b"scope": b"independent_cash_dividends_only; not_other_actions_or_publication_times",
        b"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest().encode(),
        b"issuer_body_sha256": row["sha256"].encode(),
        b"input_sha256": hashlib.sha256((dataset / "bars.parquet").read_bytes())
        .hexdigest()
        .encode(),
        b"dataset_id": manifest["dataset_id"].encode(),
        b"symbol": manifest["symbol"].encode(),
        b"start": manifest["start"].isoformat().encode(),
        b"end": manifest["end"].isoformat().encode(),
    }
    return QualityReport(
        pa.Table.from_pylist(checks, schema=QUALITY_SCHEMA.with_metadata(metadata))
    )
