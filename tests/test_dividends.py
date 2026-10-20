import hashlib
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.cli import main
from invest.datasets import fetch_dataset
from invest.dividends import SOURCE_SCHEMA, SOURCE_URL, audit_dividends
from invest.storage import update_paper
from tests.helpers import BASE
from tests.test_datasets import SPEC, provider


def source_capture(tmp_path: Path, records: list[list[str]]) -> Path:
    """Tiny artificial issuer workbook in the documented archived-source format."""
    headers = [
        "FUND NAME",
        "TICKER",
        "CUSIP",
        "EX-DATE",
        "RECORD DATE",
        "PAYABLE DATE",
        "DIVIDEND ($)",
        "SHORT TERM CAPITAL GAIN ($)",
        "LONG TERM CAPITAL GAIN ($)",
    ]
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    strings = ET.Element("sst", xmlns=ns)
    sheet = ET.Element("worksheet", xmlns=ns)
    data = ET.SubElement(sheet, "sheetData")
    index = 0
    for number, values in enumerate([headers, *records], 1):
        row = ET.SubElement(data, "row", r=str(number))
        for column, value in zip("ABCDEFGHI", values, strict=True):
            ET.SubElement(ET.SubElement(strings, "si"), "t").text = value
            ET.SubElement(ET.SubElement(row, "c", r=f"{column}{number}", t="s"), "v").text = str(
                index
            )
            index += 1
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", ET.tostring(strings))
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))
    body = buffer.getvalue()
    capture = pa.Table.from_pylist(
        [
            {
                "url": SOURCE_URL,
                "observed_at": datetime(2025, 1, 2, tzinfo=UTC),
                "sha256": hashlib.sha256(body).hexdigest(),
                "body": body,
            }
        ],
        schema=SOURCE_SCHEMA,
    )
    path = tmp_path / "issuer.parquet"
    pq.write_table(capture, path, compression="zstd")
    return path


RECORD = ["Test fund", "DEMO", "test", "01/05/2024", "01/05/2024", "01/09/2024", "1", "", ""]


def test_issuer_evidence_is_checked_archived_and_required_on_restart(tmp_path: Path) -> None:
    dataset = fetch_dataset(SPEC, tmp_path / "data", provider())
    source = source_capture(tmp_path, [RECORD])
    output = tmp_path / "audit.parquet"
    assert (
        main(
            [
                "audit-dividends",
                "--dataset",
                str(dataset),
                "--source",
                str(source),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert pq.read_table(output)["status"].to_pylist() == ["pass"]
    account = tmp_path / "account"
    result = update_paper(
        dataset / "bars.parquet", account, BASE, dataset=dataset, dividend_source=source
    )
    assert (result.directory / "dividend-source.parquet").read_bytes() == source.read_bytes()
    assert pq.read_table(result.directory / "dividends.parquet").equals(
        pq.read_table(output), check_metadata=True
    )
    assert "Issuer cash dividends matched" in (result.directory / "report.html").read_text()
    assert not update_paper(
        dataset / "bars.parquet", account, BASE, dataset=dataset, dividend_source=source
    ).updated
    pointer = (account / "CURRENT").read_bytes()
    with pytest.raises(ValueError, match="Issuer evidence changed"):
        update_paper(dataset / "bars.parquet", account, BASE, dataset=dataset)
    assert (account / "CURRENT").read_bytes() == pointer


@pytest.mark.parametrize("problem", ["missing", "extra", "amount", "payment"])
def test_disagreement_is_reported_and_blocks_account_creation(tmp_path: Path, problem: str) -> None:
    dataset = fetch_dataset(
        SPEC, tmp_path / "data", provider(actions={} if problem == "missing" else None)
    )
    record = RECORD.copy()
    if problem == "amount":
        record[6] = "1.000001"
    if problem == "payment":
        record[5] = "01/10/2024"
    source = source_capture(
        tmp_path,
        [record, [*RECORD[:3], "01/08/2024", *RECORD[4:]]] if problem == "extra" else [record],
    )
    report = audit_dividends(dataset, source)
    assert report.errors == 1
    account = tmp_path / "account"
    with pytest.raises(ValueError, match="Issuer dividend mismatch"):
        update_paper(
            dataset / "bars.parquet", account, BASE, dataset=dataset, dividend_source=source
        )
    assert not account.exists()
    assert (
        main(
            [
                "audit-dividends",
                "--dataset",
                str(dataset),
                "--source",
                str(source),
                "--output",
                str(tmp_path / "failed.parquet"),
            ]
        )
        == 1
    )


@pytest.mark.parametrize("problem", ["checksum", "duplicate", "capital_gain", "no_events"])
def test_incomplete_or_unsupported_reference_does_not_certify_data(
    tmp_path: Path, problem: str
) -> None:
    dataset = fetch_dataset(SPEC, tmp_path / "data", provider())
    record = RECORD.copy()
    if problem == "capital_gain":
        record[7] = "0.01"
    records = (
        [record, record] if problem == "duplicate" else [] if problem == "no_events" else [record]
    )
    source = source_capture(tmp_path, records)
    if problem == "checksum":
        rows = pq.read_table(source).to_pylist()
        rows[0]["sha256"] = "0" * 64
        pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), source)
    with pytest.raises(ValueError):
        audit_dividends(dataset, source)


def test_public_capture_uses_no_credentials_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = source_capture(tmp_path, [RECORD])
    body = pq.read_table(original)["body"][0].as_py()
    calls = []

    class Opener:
        def open(self, request: Request, timeout: int) -> BytesIO:
            assert request.full_url == SOURCE_URL and not request.header_items()
            assert timeout == 30
            calls.append(request.full_url)
            return BytesIO(body)

    monkeypatch.setattr("invest.dividends.build_opener", lambda *args: Opener())
    output = tmp_path / "download.parquet"
    assert main(["capture-dividends", "--output", str(output)]) == 0
    assert pq.read_table(output)["body"][0].as_py() == body
    with pytest.raises(SystemExit) as error:
        main(["capture-dividends", "--output", str(output)])
    assert error.value.code == 2 and len(calls) == 1


def test_failed_public_capture_does_not_write_an_evidence_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Opener:
        def open(self, request: Request, timeout: int) -> BytesIO:
            raise HTTPError(request.full_url, 429, "untrusted response body", Message(), None)

    monkeypatch.setattr("invest.dividends.build_opener", lambda *args: Opener())
    output = tmp_path / "failed.parquet"
    with pytest.raises(SystemExit) as error:
        main(["capture-dividends", "--output", str(output)])
    assert error.value.code == 2 and not output.exists()
    message = capsys.readouterr().err
    assert "429" in message and "untrusted response body" not in message
