"""合成发行方证据检验日期差异、金额和支付日；不访问外部服务。"""

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.stock_dividends import (
    SOURCE_SCHEMA,
    SOURCE_URLS,
    audit_stock_dividends,
    read_sources,
    vlo_schedule,
)


def issuer_fixture(root: Path, *, amount: str = "1.07") -> Path:
    fields = {
        "Declared": "07/18/24",
        "Ex Date": "07/31/24",
        "Record": "08/01/24",
        "Payable": "09/03/24",
        "Amount": amount,
        "Type": "U.S. Currency",
    }
    bodies = {
        "vlo_history": "<table><tr>"
        + "".join(f'<td data-heading="{key}">{value}</td>' for key, value in fields.items())
        + "</tr></table>",
        "nyse_exdate": "Under T+1 normal cash dividends go ex on the record date.",
        "nyse_t1_guidance": "The first T+1 record date is May 29, 2024.",
        "ftnt_dividend_policy": "We have never declared or paid cash dividends.",
        "ftnt_annual_2025_dividends": "We have never declared or paid cash dividends.",
        "ilmn_dividend_policy": "Illumina currently does not issue dividends.",
        "ilmn_annual_2025_dividends": "We have never paid cash dividends.",
    }
    rows = [
        {
            "key": key,
            "url": SOURCE_URLS[key],
            "method": "http_get_decoded_entity",
            "observed_at": datetime(2026, 10, 24, tzinfo=UTC),
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "body": body.encode(),
        }
        for key, body in bodies.items()
    ]
    path = root / "issuer.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), path, compression="zstd")
    return path


def dividend_bars(*, pay_date: date = date(2024, 9, 3), amount: str = "1.07") -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "date": day,
                "close": Decimal(100),
                "dividend": Decimal(amount) if i else Decimal(0),
                "dividend_pay_date": pay_date if i else None,
            }
            for i, day in enumerate([date(2024, 7, 31), date(2024, 8, 1)])
        ]
    )


def test_t1_record_date_reconciles_without_overwriting_reported_ex_date(tmp_path: Path) -> None:
    path = issuer_fixture(tmp_path)
    before = path.read_bytes()
    sources = read_sources(path, date(2024, 8, 2))
    events, checks = vlo_schedule(sources, date(2024, 7, 1), date(2024, 8, 2), dividend_bars())
    assert events == {date(2024, 8, 1): ("1.07", "2024-09-03")}
    assert checks[0]["status"] == "warning"
    assert "display=2024-07-31; record=2024-08-01" in checks[0]["detail"]
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="post-transition"):
        vlo_schedule(sources, date(2024, 5, 1), date(2024, 8, 2), dividend_bars())
    issuer_fixture(tmp_path, amount="25")
    with pytest.raises(ValueError, match="normal T1"):
        vlo_schedule(
            read_sources(path, date(2024, 8, 2)),
            date(2024, 7, 1),
            date(2024, 8, 2),
            dividend_bars(),
        )


@pytest.mark.parametrize("problem", ["none", "amount", "payment", "extra", "missing_policy"])
def test_cash_amount_payment_and_zero_policy_are_independently_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    path = issuer_fixture(tmp_path)
    symbol = "FTNT" if problem in {"extra", "missing_policy"} else "VLO"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "symbol": symbol,
                    "start": date(2024, 7, 1),
                    "end": date(2024, 8, 2),
                }
            ]
        ),
        tmp_path / "manifest.parquet",
        compression="zstd",
    )
    data = dividend_bars(
        amount="2" if problem == "amount" else "1.07",
        pay_date=date(2024, 9, 4) if problem == "payment" else date(2024, 9, 3),
    )
    monkeypatch.setattr("invest.stock_dividends.verify_dataset", lambda _: data)
    if problem == "missing_policy":
        rows = [r for r in pq.read_table(path).to_pylist() if r["key"] != "ftnt_dividend_policy"]
        pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), path, compression="zstd")
        with pytest.raises(ValueError, match="current policy"):
            audit_stock_dividends(tmp_path, path)
    else:
        checks = audit_stock_dividends(tmp_path, path).checks
        assert ("error" in checks["status"].to_pylist()) == (problem != "none")


def test_source_bytes_cannot_be_changed_without_detection(tmp_path: Path) -> None:
    path = issuer_fixture(tmp_path)
    rows = pq.read_table(path).to_pylist()
    rows[0]["body"] += b"changed"
    pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), path, compression="zstd")
    with pytest.raises(ValueError, match="identity, body"):
        read_sources(path, date(2024, 8, 2))
