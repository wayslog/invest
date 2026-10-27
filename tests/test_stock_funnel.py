"""关注漏斗的真实边界：分页、成员时点、缺值、相关性和非交易资格。"""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import NEW_YORK
from invest.quality import regular_sessions
from invest.research_artifacts import seal_artifacts, verify_artifacts
from invest.spy_data import (
    HOLDINGS_URL,
    QQQ_HOLDINGS_URL,
    capture_spy_inputs,
    frozen_holdings_sources,
    parse_holdings,
    parse_qqq_holdings,
    read_spy_inputs,
)
from invest.stock_funnel import METRICS, load_funnel_config, percentile, run_funnel, select_focus

END = date(2024, 12, 31)


def workbook(day: date = END, *, currency: str = "USD") -> bytes:
    cells = {
        "B2": "SPY",
        "B3": day.strftime("As of %d-%b-%Y"),
        "A5": "Name",
        "B5": "Ticker",
        "E5": "Weight",
        "F5": "Sector",
        "H5": "Local Currency",
    }
    for row, symbol in enumerate(["AAA", "BRK.B", "CCC", "DDD", "EEE", "-", "2602335D"], 6):
        cells.update(
            {
                f"A{row}": f"Company {symbol}",
                f"B{row}": symbol,
                f"E{row}": "19.96" if row < 11 else "0.1",
                f"F{row}": "-",
                f"H{row}": currency,
            }
        )
    body = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row>'
    body += "".join(
        f'<c r="{key}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        for key, value in cells.items()
    )
    body += "</row></sheetData></worksheet>"
    out = BytesIO()
    with ZipFile(out, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", body)
    return out.getvalue()


def capture(
    root: Path,
    *,
    missing: bool = False,
    broken_page: bool = False,
    sources: Path | None = None,
) -> Path:
    sessions = regular_sessions(END - timedelta(days=420), END)["date"].to_pylist()

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        assert endpoint == "/v2/stocks/bars" and query["feed"] == "sip"
        symbols = query["symbols"].split(",")
        selected = symbols[2:] if query.get("page_token") else symbols[:2]
        bars = {}
        for symbol in selected:
            number = symbols.index(symbol) + 1
            values = []
            for index, day in enumerate(sessions):
                if missing and symbol == "AAA" and day == sessions[-10]:
                    continue
                price = round(
                    100 * np.exp(index * 0.0006 * number) * (1 + 0.01 * np.sin(index / number)), 4
                )
                values.append(
                    {
                        "t": datetime.combine(day, time(), NEW_YORK).isoformat(),
                        "o": price,
                        "h": price + 1,
                        "l": price - 1,
                        "c": price,
                        "v": 1000000,
                    }
                )
            bars[symbol] = values
        token = "next" if not query.get("page_token") or broken_page else None
        return json.dumps({"bars": bars, "next_page_token": token}).encode()

    capture_spy_inputs(
        root,
        END,
        get,
        holdings_body=workbook() if sources is None else None,
        holdings_sources=sources,
    )
    return root


def qqq_holdings(day: date = END) -> bytes:
    rows = [
        {
            "ticker": symbol,
            "issuerName": f"Company {symbol}",
            "securityTypeCode": kind,
            "percentageOfTotalNetAssets": weight,
            "currency": "USD",
        }
        for symbol, kind, weight in (
            ("AAA", "COM", 50),
            ("ASML", "DRNY", 50),
            ("USD", "CURR", 0.1),
            ("NQZ4", "IFUT", 0.1),
            (None, "SYN", -0.1),
        )
    ]
    return json.dumps(
        {
            "cusip": "QQQ",
            "effectiveBusinessDate": str(day),
            "totalNumberOfHoldings": len(rows),
            "holdings": rows,
        }
    ).encode()


def fund_sources(path: Path, spy_day: date = END) -> Path:
    rows = [
        {
            "fund": fund,
            "url": url,
            "final_url": url,
            "status": 200,
            "captured_at": datetime(2025, 1, 3, tzinfo=UTC),
            "sha256": hashlib.sha256(body).hexdigest(),
            "body": body,
        }
        for fund, url, body in (
            ("SPY", HOLDINGS_URL, workbook(spy_day)),
            ("QQQ", QQQ_HOLDINGS_URL, qqq_holdings()),
        )
    ]
    schema = pa.schema(
        [
            ("fund", pa.string()),
            ("url", pa.string()),
            ("final_url", pa.string()),
            ("status", pa.int32()),
            ("captured_at", pa.timestamp("us", tz="UTC")),
            ("sha256", pa.string()),
            ("body", pa.binary()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
    return path


def test_qqq_depositary_receipts_admitted_and_non_equities_excluded() -> None:
    rows = parse_qqq_holdings(qqq_holdings()).to_pylist()
    assert {r["symbol"] for r in rows if r["eligible"]} == {"AAA", "ASML"}
    assert all(not r["eligible"] for r in rows if r["symbol"] in {"USD", "NQZ4", ""})
    payload = json.loads(qqq_holdings())
    for row in payload["holdings"]:
        row.pop("currency")
    assert sum(parse_qqq_holdings(json.dumps(payload).encode())["eligible"].to_pylist()) == 2
    payload["holdings"][1]["ticker"] = "AAA"
    with pytest.raises(ValueError, match="Duplicate"):
        parse_qqq_holdings(json.dumps(payload).encode())


def test_union_deduplicates_and_keeps_both_sources_dates_and_weights(tmp_path: Path) -> None:
    sources = fund_sources(tmp_path / "sources.parquet", END - timedelta(days=1))
    inputs = capture(tmp_path / "inputs", sources=sources)
    members, bars = read_spy_inputs(inputs, END)
    assert sum(members["eligible"].to_pylist()) == 6
    common = next(row for row in members.to_pylist() if row["symbol"] == "AAA")
    assert common["funds"] == ["SPY", "QQQ"] and common["weight"] is None
    assert common["spy_weight"] == pytest.approx(0.1996) and common["qqq_weight"] == 0.5
    assert common["spy_membership_as_of"] == END - timedelta(days=1)
    assert common["qqq_membership_as_of"] == END
    assert set(bars["raw"]["instrument"].to_pylist()) == {
        "AAA",
        "ASML",
        "BRK_B",
        "CCC",
        "DDD",
        "EEE",
        "SPY",
    }
    original = frozen_holdings_sources(sources)
    for index, fund in enumerate(("SPY", "QQQ")):
        page = pq.read_table(inputs / "raw" / f"{index:04d}.parquet").to_pylist()[0]
        assert page["body"] == original[fund]["body"]
        assert page["received_at"] == original[fund]["captured_at"]
    result = tmp_path / "study"
    run_funnel(inputs, Path("configs/spy-funnel.toml"), result, END)
    record = pq.read_table(result / "run.parquet").to_pylist()[0]
    assert record["members"] == 6 and record["universe_name"] == "SPY_QQQ"
    ranked = pq.read_table(result / "rankings.parquet").to_pylist()
    assert all(not row["trade_eligible"] for row in ranked)
    assert next(row for row in ranked if row["symbol"] == "ASML")["funds"] == ["QQQ"]
    assert "SPY + QQQ" in (result / "report.html").read_text()
    verify_artifacts(result)


def test_recent_qqq_cannot_hide_stale_spy_membership(tmp_path: Path) -> None:
    sources = fund_sources(tmp_path / "sources.parquet", END - timedelta(days=20))
    with pytest.raises(ValueError, match="membership"):
        capture(tmp_path / "inputs", sources=sources)


def test_frozen_fund_source_hash_and_qqq_market_coverage_are_required(tmp_path: Path) -> None:
    sources = fund_sources(tmp_path / "sources.parquet")
    inputs = capture(tmp_path / "inputs", sources=sources)
    path = inputs / "raw/0002.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    query = json.loads(rows[0]["query"])
    query["symbols"] = ",".join(x for x in query["symbols"].split(",") if x != "ASML")
    rows[0]["query"] = json.dumps(query)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    seal_artifacts(inputs)
    with pytest.raises(ValueError, match="identity"):
        read_spy_inputs(inputs, END)
    table = pq.read_table(sources)
    rows = table.to_pylist()
    rows[1]["body"] = b"changed"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), sources, compression="zstd")
    with pytest.raises(ValueError, match="source"):
        frozen_holdings_sources(sources)


def test_holdings_preserve_dates_cash_special_rights_and_share_classes() -> None:
    table = parse_holdings(workbook())
    rows = {r["symbol"]: r for r in table.to_pylist()}
    assert table.num_rows == 7 and sum(table["eligible"].to_pylist()) == 5
    assert rows["BRK.B"]["instrument"] == "BRK_B"
    assert rows["-"]["eligible"] is False and rows["2602335D"]["eligible"] is False
    assert all(r["sector"] is None and r["membership_as_of"] == END for r in rows.values())
    assert sum(table["weight"].to_pylist()) == pytest.approx(1)
    assert sum(parse_holdings(workbook(currency=""))["eligible"].to_pylist()) == 5


def test_stale_and_future_membership_are_rejected_before_market_access(tmp_path: Path) -> None:
    def forbidden(endpoint: str, query: dict[str, str]) -> bytes:
        raise AssertionError("Market query must not run")

    for day in (END + timedelta(days=1), END - timedelta(days=20)):
        with pytest.raises(ValueError, match="membership"):
            capture_spy_inputs(tmp_path / str(day), END, forbidden, holdings_body=workbook(day))


def test_complete_market_pages_replay_and_repeated_page_fails(tmp_path: Path) -> None:
    inputs = capture(tmp_path / "inputs")
    holdings, tables = read_spy_inputs(inputs, END)
    assert sum(holdings["eligible"].to_pylist()) == 5
    assert tables["raw"].num_rows == tables["split"].num_rows
    assert tables["raw"]["available_at"].null_count == tables["raw"].num_rows
    with pytest.raises(ValueError, match="pagination"):
        capture(tmp_path / "failed", broken_page=True)
    verify_artifacts(tmp_path / "failed")


def test_tampered_page_cannot_be_admitted_by_resealing_manifest(tmp_path: Path) -> None:
    import pyarrow as pa

    inputs = capture(tmp_path / "inputs")
    path = inputs / "raw/0001.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["body"] = b"changed"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    seal_artifacts(inputs)
    with pytest.raises(ValueError, match="hash"):
        read_spy_inputs(inputs, END)


def test_missing_session_remains_excluded_and_no_trade_permission(tmp_path: Path) -> None:
    inputs = capture(tmp_path / "inputs", missing=True)
    before = hashlib.sha256((inputs / "artifacts.parquet").read_bytes()).hexdigest()
    result = run_funnel(inputs, Path("configs/spy-funnel.toml"), tmp_path / "result", END)
    rows = {r["symbol"]: r for r in pq.read_table(tmp_path / "result/rankings.parquet").to_pylist()}
    assert rows["AAA"]["reason"] == "incomplete_recent_history"
    assert rows["AAA"]["score"] is None and not rows["AAA"]["focus"]
    assert all(r["trade_eligible"] is False for r in rows.values())
    assert result["trade_eligible"] is False and result["status"] == "completed"
    metadata = pq.read_schema(tmp_path / "result/focus.parquet").metadata
    assert metadata[b"source"] == b"alpaca" and metadata[b"scope"] == b"exploratory"
    assert metadata[b"snapshot_id"] and metadata[b"input_manifest_sha256"]
    assert hashlib.sha256((inputs / "artifacts.parquet").read_bytes()).hexdigest() == before
    verify_artifacts(tmp_path / "result")
    with pytest.raises(FileExistsError):
        run_funnel(inputs, Path("configs/spy-funnel.toml"), tmp_path / "result", END)


def test_correlated_names_and_weak_scores_do_not_fill_focus_quota() -> None:
    config = load_funnel_config(Path("configs/spy-funnel.toml"))
    config["min_score"] = 1.0
    rows = []
    for number in range(6):
        row: dict[str, Any] = {
            "instrument": f"S{number}",
            "reason": "",
            "excess_126": number,
            "excess_252": number,
        }
        row.update(
            {
                name: number + 1 if name not in {"volatility", "drawdown"} else 0.1
                for name in METRICS
            }
        )
        rows.append(row)
    returns = pd.DataFrame({f"S{i}": np.sin(np.arange(126)) for i in range(6)})
    frame = select_focus(pd.DataFrame(rows), returns, config)
    assert frame.focus.sum() == 1
    assert "correlated_with_higher_ranked_focus" in set(frame.reason)
    assert np.allclose(frame.score, frame[[f"{name}_points" for name in METRICS]].sum(axis=1))
    config["min_score"] = 100.0
    assert select_focus(pd.DataFrame(rows), returns, config).focus.sum() == 0


def test_equal_values_have_neutral_percentile_not_maximum_score() -> None:
    assert percentile(pd.Series([2.0, 2.0, 2.0])).tolist() == [0.5, 0.5, 0.5]
    assert percentile(pd.Series([1.0, 2.0, 3.0]), lower=True).tolist() == [1.0, 0.5, 0.0]


def test_weekly_changes_keep_removed_names_and_do_not_compare_changed_rules() -> None:
    import pyarrow as pa

    from invest.stock_funnel import focus_changes

    old = pa.Table.from_pylist(
        [
            {"instrument": "AAA", "focus": True, "score": 80.0},
            {"instrument": "BBB", "focus": False, "score": 60.0},
        ]
    )
    new = pa.Table.from_pylist([{"instrument": "BBB", "focus": True, "score": 85.0}])
    changed = focus_changes(new, old, True).to_pylist()
    assert changed[0]["change"] == "left_focus" and changed[0]["current_score"] is None
    assert changed[1]["change"] == "entered_focus" and changed[1]["score_delta"] == 25
    assert focus_changes(new, old, False)["score_delta"].null_count == 2


def test_qlib_date_slice_preserves_history_and_availability(tmp_path: Path) -> None:
    from invest.qlib_adapter import calculate_factors
    from tests.test_factor_mining import research_snapshot

    data = research_snapshot(tmp_path, length=40)
    day = data.calendar["date"][-1].as_py()
    expressions = {"momentum": "$close/Ref($close,10)-1"}
    full = calculate_factors(data, expressions, tmp_path / "cache").table
    latest = calculate_factors(data, expressions, tmp_path / "cache", start=day, end=day).table
    assert latest.to_pylist() == [r for r in full.to_pylist() if r["date"] == day]
    assert latest.schema.metadata == full.schema.metadata
    with pytest.raises(ValueError, match="range"):
        calculate_factors(data, expressions, tmp_path / "cache", start=day + timedelta(days=1))
