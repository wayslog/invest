"""Artificial provider/issuer captures exercise the real admission and worker paths."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import FetchSpec, RequestData, fetch_pages
from invest.datasets import fetch_dataset
from invest.forward import forward_status, init_forward, run_forward, verify_forward
from invest.forward_ops import forward_job
from tests.test_dividends import source_capture
from tests.test_forward import setup


def test_real_contract_requires_timely_evidence_and_worker_retries_without_duplicate_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, inputs, _ = setup(tmp_path, mode="cash_observation", candidate="cash")
    now = datetime(2024, 1, 8, 6, tzinfo=UTC)
    old_bar_page = False
    future_issuer = False

    def captured(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
        for page in fetch_pages(spec, request):
            page["received_at"] = now - (
                timedelta(hours=3)
                if old_bar_page and page["kind"] == "bars"
                else timedelta(minutes=1)
            )
            yield page

    monkeypatch.setattr("invest.datasets.fetch_pages", captured)
    monkeypatch.setattr("invest.forward.clock", lambda: now)

    def batch(spec: FetchSpec, root: Path, *, fail: bool = False) -> Path:
        def request(endpoint: str, query: dict[str, str]) -> bytes:
            if fail:
                raise ValueError("Temporary provider outage")
            if endpoint == "/v2/stocks/bars":
                values = []
                for row in inputs[spec.symbol].to_pylist():
                    if row["date"] > spec.end:
                        continue
                    values.append(
                        {
                            "t": f"{row['date']}T05:00:00Z",
                            "v": row["volume"],
                            **{
                                short: str(row[long])
                                for short, long in [
                                    ("o", "open"),
                                    ("h", "high"),
                                    ("l", "low"),
                                    ("c", "close"),
                                ]
                            },
                        }
                    )
                return json.dumps({"bars": {spec.symbol: values}, "next_page_token": None}).encode()
            return json.dumps(
                {
                    "corporate_actions": {
                        "cash_dividends": [
                            {
                                "symbol": spec.symbol,
                                "rate": "1",
                                "ex_date": "2024-01-05",
                                "payable_date": "2024-01-09",
                                "special": False,
                                "foreign": False,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            ).encode()

        return fetch_dataset(spec, root, request)

    def issuer_capture(output: Path) -> None:
        source = source_capture(
            tmp_path,
            [
                ["Test fund", s, "test", "01/05/2024", "01/05/2024", "01/09/2024", "1", "", ""]
                for s in inputs
            ],
        )
        table = pq.read_table(source)
        rows = table.to_pylist()
        rows[0]["observed_at"] = now + (
            timedelta(days=1) if future_issuer else -timedelta(minutes=2)
        )
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), output, compression="zstd")

    issuer = tmp_path / "source.parquet"
    issuer_capture(issuer)
    sources = {
        s: batch(FetchSpec(s, date(2024, 1, 2), date(2024, 1, 5), "sip"), tmp_path / "data")
        for s in inputs
    }
    init_forward(
        account, tmp_path / "observation.toml", tmp_path / "policy.toml", sources, issuer=issuer
    )
    calls: list[tuple[str, bool]] = []

    def fetch(spec: FetchSpec, root: Path) -> Path:
        failure = not any(s == spec.symbol for s, _ in calls)
        calls.append((spec.symbol, failure))
        return batch(spec, root, fail=failure)

    monkeypatch.setattr("invest.forward_ops.fetch_dataset", fetch)
    monkeypatch.setattr("invest.forward_ops.capture_distributions", issuer_capture)
    assert forward_job(account, tmp_path / "data")["due"] is False
    assert not calls
    now = datetime(2024, 1, 9, 6, tzinfo=UTC)
    assert forward_job(account, tmp_path / "data")["status"] == "active"
    assert len(calls) == 4  # Both failures retained and retried; no fallback feed.
    assert forward_job(account, tmp_path / "data")["due"] is False
    assert forward_status(account)["cash"] == "5000.000000"
    assert verify_forward(account)["status"] == "verified"

    # A recent action response cannot hide bars captured three hours ago.
    now = datetime(2024, 1, 10, 10, tzinfo=UTC)
    old_bar_page = True
    result = forward_job(account, tmp_path / "data")
    assert result["status"] == "paused" and "stale" in result["error"]
    assert forward_status(account)["sessions"] == 1
    old_bar_page = False
    future_issuer = True
    issuer_capture(issuer)
    sources = {
        s: batch(FetchSpec(s, date(2024, 1, 2), date(2024, 1, 9), "sip"), tmp_path / "data")
        for s in inputs
    }
    result = run_forward(account, sources, issuer=issuer)
    assert "not available" in result["error"]
    assert verify_forward(account)["status"] == "verified"


def test_late_task_records_no_backdated_orders(tmp_path: Path) -> None:
    from tests.test_forward import initialize, save

    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    save(inputs, sources, 5)
    now = datetime(2024, 1, 9, 15, tzinfo=UTC)
    result = run_forward(account, sources, at=now)
    assert result["status"] == "paused"
    status = forward_status(account, at=now)
    assert status["pending_orders"] == 0
    assert status["sessions"] == 1
    assert verify_forward(account)["status"] == "verified"
