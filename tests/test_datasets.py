import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import FetchSpec, RequestData, authenticated_request, fetch_pages
from invest.cli import main
from invest.datasets import fetch_dataset, verify_dataset
from invest.storage import update_paper
from tests.helpers import BASE

SPEC = FetchSpec("DEMO", date(2024, 1, 2), date(2024, 1, 9), "sip")


def provider(
    *,
    actions: dict[str, list[dict[str, object]]] | None = None,
    omit: int | None = None,
    duplicate: bool = False,
) -> RequestData:
    """Artificial API responses, never evidence of live provider compatibility."""
    bars = [
        {
            "t": f"2024-01-{day:02}T05:00:00Z",
            "o": str(price - 1),
            "h": str(price + 1),
            "l": str(price - 2),
            "c": str(price),
            "v": 1000,
        }
        for day, price in [(2, 100), (3, 110), (4, 120), (5, 121), (8, 122), (9, 123)]
        if day != omit
    ]
    if duplicate:
        bars.append(bars[-1])
    if actions is None:
        actions = {
            "cash_dividends": [
                {
                    "symbol": "DEMO",
                    "rate": "1",
                    "ex_date": "2024-01-05",
                    "payable_date": "2024-01-09",
                    "special": False,
                    "foreign": False,
                }
            ]
        }

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        page: dict[str, Any]
        if endpoint == "/v2/stocks/bars":
            assert query["adjustment"] == "raw" and query["feed"] == "sip"
            assert query["start"] == "2024-01-02T00:00:00-05:00"
            assert query["end"] == "2024-01-09T23:59:59.999999-05:00"
            page = {
                "bars": {"DEMO": bars[:2] if "page_token" not in query else bars[2:]},
                "next_page_token": "second" if "page_token" not in query else None,
            }
        else:
            assert endpoint == "/v1/corporate-actions"
            assert "types" not in query  # Unsupported actions must not be filtered out.
            assert query["start"] == "1970-01-01"
            assert query["end"] == SPEC.actions_through.isoformat()
            page = {"corporate_actions": actions, "next_page_token": None}
        return json.dumps(page).encode()

    return get


def test_capture_is_reproducible_and_carries_conservative_availability(tmp_path: Path) -> None:
    directory = fetch_dataset(SPEC, tmp_path, provider())
    bars = verify_dataset(directory)
    assert bars.num_rows == 6
    assert bars["dividend"].to_pylist()[3] == 1
    assert bars["dividend_pay_date"].to_pylist()[3] == date(2024, 1, 9)
    manifest = pq.read_table(directory / "manifest.parquet").to_pylist()[0]
    assert manifest["status"] == "research_only"
    observed = pq.read_table(directory / "availability.parquet")
    assert set(observed["observed_at"].to_pylist()) == {manifest["observed_at"]}
    assert observed["published_at"].null_count == 6
    raw = pq.read_table(directory / "raw.parquet")
    assert raw.num_rows == 3
    assert all(hashlib.sha256(row["body"]).hexdigest() == row["sha256"] for row in raw.to_pylist())
    assert not list(directory.glob("*.json"))
    assert main(["verify-data", "--dataset", str(directory)]) == 0


@pytest.mark.parametrize(
    "problem",
    [
        "missing_head",
        "missing_tail",
        "duplicate",
        "payment",
        "reverse",
        "unknown",
        "fractional",
        "special",
        "precision",
    ],
)
def test_incomplete_or_unsupported_data_is_quarantined(tmp_path: Path, problem: str) -> None:
    get = provider()
    if problem == "missing_head":
        get = provider(omit=2)
    elif problem == "missing_tail":
        get = provider(omit=9)
    elif problem == "duplicate":
        get = provider(duplicate=True)
    elif problem in {"reverse", "unknown"}:
        get = provider(actions={"reverse_splits" if problem == "reverse" else "delistings": [{}]})
    elif problem == "fractional":
        get = provider(
            actions={
                "forward_splits": [
                    {"symbol": "DEMO", "ex_date": "2024-01-05", "new_rate": "3", "old_rate": "2"}
                ]
            }
        )
    else:
        get = provider(
            actions={
                "cash_dividends": [
                    {
                        "symbol": "DEMO",
                        "ex_date": "2024-01-05",
                        "rate": "1.3662419" if problem == "precision" else "1",
                        "payable_date": None if problem == "payment" else "2024-01-09",
                        "special": problem == "special",
                        "foreign": False,
                    }
                ]
            }
        )
    directory = fetch_dataset(SPEC, tmp_path, get)
    assert "error" in pq.read_table(directory / "quality.parquet")["status"].to_pylist()
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)
    account = tmp_path / "account"
    with pytest.raises(ValueError, match="quarantined"):
        update_paper(directory / "bars.parquet", account, BASE, dataset=directory)
    assert not account.exists()


def test_failed_pagination_retains_evidence_but_cannot_run(tmp_path: Path) -> None:
    original = provider()

    def failed(endpoint: str, query: dict[str, str]) -> bytes:
        if "page_token" in query:
            raise ValueError("Alpaca HTTP 429")
        return original(endpoint, query)

    directory = fetch_dataset(SPEC, tmp_path, failed)
    assert pq.read_table(directory / "raw.parquet").num_rows == 1
    assert "429" in pq.read_table(directory / "quality.parquet")["detail"][0].as_py()
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)


def test_repeated_tokens_fail_without_unbounded_requests(tmp_path: Path) -> None:
    calls = 0

    def repeated(endpoint: str, query: dict[str, str]) -> bytes:
        nonlocal calls
        calls += 1
        return b'{"bars": {}, "next_page_token": "same"}'

    directory = fetch_dataset(SPEC, tmp_path, repeated)
    assert calls == 2
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)


def test_changes_are_new_versions_and_old_accounts_refuse_revisions(tmp_path: Path) -> None:
    first = fetch_dataset(SPEC, tmp_path / "data", provider())
    original_bytes = (first / "bars.parquet").read_bytes()
    account = tmp_path / "account"
    result = update_paper(first / "bars.parquet", account, BASE, dataset=first)
    assert (
        "error"
        not in pq.read_table(result.directory / "reconciliation.parquet")["status"].to_pylist()
    )
    second = fetch_dataset(SPEC, tmp_path / "data", provider())
    assert first != second and (first / "bars.parquet").read_bytes() == original_bytes
    assert not update_paper(second / "bars.parquet", account, BASE, dataset=second).updated
    revised = fetch_dataset(SPEC, tmp_path / "data", provider(actions={}))
    pointer = (account / "CURRENT").read_bytes()
    with pytest.raises(ValueError, match="history was changed"):
        update_paper(revised / "bars.parquet", account, BASE, dataset=revised)
    with pytest.raises(ValueError, match="quality failed"):
        update_paper(
            second / "bars.parquet",
            account,
            BASE,
            dataset=second,
            required_through=date(2024, 1, 10),
        )
    assert (account / "CURRENT").read_bytes() == pointer
    with pytest.raises(ValueError, match="symbol"):
        update_paper(
            second / "bars.parquet", tmp_path / "wrong", replace(BASE, symbol="SPY"), dataset=second
        )


def test_tampering_and_bypassing_provenance_fail(tmp_path: Path) -> None:
    directory = fetch_dataset(SPEC, tmp_path / "data", provider())
    with pytest.raises(ValueError, match="verified --dataset"):
        update_paper(directory / "bars.parquet", tmp_path / "bypass", BASE)
    bars = pq.read_table(directory / "bars.parquet")
    pq.write_table(bars.slice(0, 4), directory / "bars.parquet")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_dataset(directory)


def test_no_credentials_do_not_print_secrets_or_create_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="secure environment"):
        authenticated_request()
    with pytest.raises(SystemExit) as error:
        main(
            [
                "fetch",
                "--symbol",
                "SPY",
                "--start",
                "2024-01-02",
                "--end",
                "2024-01-09",
                "--feed",
                "sip",
                "--output",
                str(tmp_path / "data"),
            ]
        )
    assert error.value.code == 2
    assert "APCA_API_KEY_ID" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_bad_response_shape_is_retained_without_traceback(tmp_path: Path) -> None:
    directory = fetch_dataset(SPEC, tmp_path, lambda endpoint, query: b'{"next_page_token": null}')
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)
    assert pq.read_table(directory / "raw.parquet").num_rows == 2


def test_action_pages_are_not_silently_dropped(tmp_path: Path) -> None:
    original = provider(actions={})

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        if endpoint == "/v1/corporate-actions":
            if "page_token" not in query:
                return b'{"corporate_actions": {}, "next_page_token": "actions2"}'
            return b'{"corporate_actions": {"reverse_splits": [{}]}, "next_page_token": null}'
        return original(endpoint, query)

    directory = fetch_dataset(SPEC, tmp_path, get)
    assert pq.read_table(directory / "raw.parquet").num_rows == 4
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)


def test_recomputed_file_hash_does_not_hide_normalization_changes(tmp_path: Path) -> None:
    directory = fetch_dataset(SPEC, tmp_path, provider())
    path = directory / "actions.parquet"
    pq.write_table(pq.read_table(path).slice(0, 0), path)
    files = pq.read_table(directory / "files.parquet")
    rows = files.to_pylist()
    for row in rows:
        if row["file"] == path.name:
            row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    pq.write_table(pa.Table.from_pylist(rows, schema=files.schema), directory / "files.parquet")
    with pytest.raises(ValueError, match="normalization mismatch"):
        verify_dataset(directory)


def test_integer_split_from_capture_preserves_shares_and_value(tmp_path: Path) -> None:
    original = provider(
        actions={
            "forward_splits": [
                {"symbol": "DEMO", "ex_date": "2024-01-05", "new_rate": "2", "old_rate": "1"}
            ]
        }
    )

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        response = json.loads(original(endpoint, query))
        if endpoint == "/v2/stocks/bars":
            for row in response["bars"]["DEMO"]:
                if row["t"] >= "2024-01-05":
                    for field in ["o", "h", "l", "c"]:
                        row[field] = str(Decimal(row[field]) / 2)
        return json.dumps(response).encode()

    directory = fetch_dataset(SPEC, tmp_path / "data", get)
    bars = verify_dataset(directory)
    assert bars["split_ratio"].to_pylist() == [1, 1, 1, 2, 1, 1]
    result = update_paper(directory / "bars.parquet", tmp_path / "account", BASE, dataset=directory)
    equity = pq.read_table(result.directory / "equity.parquet").to_pylist()
    assert equity[3]["shares"] == equity[2]["shares"] * 2
    assert equity[3]["equity"] - equity[2]["equity"] == equity[2]["shares"]
    assert (
        "error"
        not in pq.read_table(result.directory / "reconciliation.parquet")["status"].to_pylist()
    )


def test_unfinished_provider_bar_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def early_capture(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
        for page in fetch_pages(spec, request):
            yield {**page, "received_at": datetime(2024, 1, 9, 20, tzinfo=UTC)}

    monkeypatch.setattr("invest.datasets.fetch_pages", early_capture)
    directory = fetch_dataset(SPEC, tmp_path, provider())
    quality = pq.read_table(directory / "quality.parquet")
    assert "unfinished_session" in quality["check"].to_pylist()
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)


def test_ex_date_controls_entitlement_when_payment_crosses_research_boundary(
    tmp_path: Path,
) -> None:
    def dividend(ex_date: str, payment: str) -> dict[str, object]:
        return {
            "symbol": "DEMO",
            "ex_date": ex_date,
            "payable_date": payment,
            "process_date": payment,
            "rate": "1",
            "special": False,
            "foreign": False,
        }

    directory = fetch_dataset(
        SPEC,
        tmp_path,
        provider(
            actions={
                "cash_dividends": [
                    dividend("2023-12-15", "2024-01-05"),
                    dividend("2024-01-05", "2024-01-09"),
                    dividend("2024-01-09", "2024-02-01"),
                    dividend("2024-03-15", "2024-04-30"),
                ]
            }
        ),
    )
    bars = verify_dataset(directory)
    assert bars["dividend"].to_pylist() == [0, 0, 0, 1, 0, 1]
    assert bars["dividend_pay_date"].to_pylist()[-1] == date(2024, 2, 1)
    assert pq.read_table(directory / "actions.parquet").num_rows == 2
    result = update_paper(directory / "bars.parquet", tmp_path / "account", BASE, dataset=directory)
    equity = pq.read_table(result.directory / "equity.parquet").to_pylist()
    assert equity[0]["receivables"] == 0  # No entitlement from before account inception.
    assert equity[-1]["receivables"] == equity[-1]["shares"]  # Tail dividend stays receivable.


def test_capture_cutoff_is_preserved_in_manifest(tmp_path: Path) -> None:
    spec = replace(SPEC, actions_through=date(2025, 1, 31))
    original = provider()

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        if endpoint == "/v1/corporate-actions":
            assert query["end"] == "2025-01-31"
            return b'{"corporate_actions": {}, "next_page_token": null}'
        return original(endpoint, query)

    directory = fetch_dataset(spec, tmp_path, get)
    assert verify_dataset(directory).num_rows == 6
    assert (
        pq.read_table(directory / "manifest.parquet")["actions_through"][0].as_py()
        == spec.actions_through
    )


def test_late_action_response_cannot_admit_premature_bar_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mixed_capture(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
        for page in fetch_pages(spec, request):
            observed = (
                datetime(2024, 1, 9, 22, tzinfo=UTC)
                if page["kind"] == "bars"
                else datetime(2024, 1, 10, 6, tzinfo=UTC)
            )
            yield {**page, "received_at": observed}

    monkeypatch.setattr("invest.datasets.fetch_pages", mixed_capture)
    directory = fetch_dataset(SPEC, tmp_path, provider())
    assert (
        "unfinished_provider_capture"
        in pq.read_table(directory / "quality.parquet")["check"].to_pylist()
    )
    with pytest.raises(ValueError, match="quarantined"):
        verify_dataset(directory)


def test_weekend_range_end_does_not_delay_completed_friday_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = FetchSpec("DEMO", date(2024, 1, 5), date(2024, 1, 6), "sip")

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        if endpoint == "/v2/stocks/bars":
            return (
                b'{"bars":{"DEMO":[{"t":"2024-01-05T05:00:00Z","o":100,"h":101,'
                b'"l":99,"c":100,"v":100}]},"next_page_token":null}'
            )
        return b'{"corporate_actions":{},"next_page_token":null}'

    def saturday_capture(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
        for page in fetch_pages(spec, request):
            yield {**page, "received_at": datetime(2024, 1, 6, 6, tzinfo=UTC)}

    monkeypatch.setattr("invest.datasets.fetch_pages", saturday_capture)
    directory = fetch_dataset(spec, tmp_path, get)
    assert verify_dataset(directory).num_rows == 1
