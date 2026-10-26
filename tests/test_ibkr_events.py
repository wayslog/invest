"""企业行动的离线协议替身；不把查询成功或空响应当作覆盖证明。"""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest import ibkr_cli, ibkr_events
from invest.ibkr_data import save_capture
from invest.ibkr_gateway import IBKRGateway
from invest.ibkr_models import IBKRConfig
from invest.ibkr_synthetic import SyntheticBroker, demo_capture
from invest.research_artifacts import verify_artifacts
from invest.research_data import digest, load_snapshot
from tests.test_ibkr_data import FakeIB


@dataclass
class EventRequest:
    filter: str
    totalLimit: int


class EventIB(FakeIB):
    def __init__(self) -> None:
        super().__init__()
        self.account = "DU_SYNTHETIC"
        self.metadata = '{"event_types":["wshe_div","wshe_splits"]}'
        self.response = "[]"
        self.requests: list[EventRequest] = []
        self.fail = False
        self.cancels = 0

    def connect(self, host: str, port: int, **kwargs: Any) -> None:
        assert kwargs["clientId"] == 74

    def getWshMetaData(self) -> str:
        return self.metadata

    def getWshEventData(self, request: EventRequest) -> str:
        self.requests.append(request)
        if self.fail:
            raise TimeoutError("Synthetic WSH timeout")
        return self.response

    def cancelWshEventData(self) -> None:
        self.cancels += 1


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, EventIB]:
    broker = SyntheticBroker()
    # 协议替身仅用于检验真实入口的来源检查，不是下载的 IBKR 数据。
    broker.source = "ibkr"
    capture = save_capture(demo_capture(broker, IBKRConfig()), tmp_path / "market")
    sdk_broker = EventIB()
    sdk = SimpleNamespace(IB=lambda: sdk_broker, WshEventData=EventRequest)
    monkeypatch.setattr(ibkr_events, "IBKRGateway", lambda config: IBKRGateway(config, sdk))
    monkeypatch.setattr(ibkr_events, "version", lambda name: "2.1.0-test-double")
    return capture, sdk_broker


def test_event_capture_keeps_empty_responses_unverified_and_requests_read_only(
    case: tuple[Path, EventIB], tmp_path: Path
) -> None:
    capture, broker = case
    original = {path: digest(path) for path in capture.iterdir()}
    output = tmp_path / "events"
    result = ibkr_events.capture_events(replace(IBKRConfig(), client_id=74), capture, output)
    assert result["status"] == "captured" and result["received_requests"] == 4
    assert not result["corporate_actions_complete"]
    verify_artifacts(output)
    assert {path: digest(path) for path in original} == original
    assert broker.disconnected and not broker.calls
    assert len(broker.requests) == 4
    for request in broker.requests:
        filters = json.loads(request.filter)
        assert len(set(filters) & set(ibkr_events.EVENT_TYPES)) == 1
        assert filters["watchlist"] in (["1"], ["2"])
        assert request.totalLimit == 100
    rows = pq.read_table(output / "requests.parquet").to_pylist()
    assert {row["coverage_status"] for row in rows} == {"unverified"}
    assert {p.name for p in (output / "market_capture").iterdir()} == {
        "capture.parquet",
        "contracts.parquet",
        "historical.parquet",
    }
    raw = pq.read_table(output / "raw.parquet")
    assert set(raw["method"].to_pylist()) == {"getWshMetaData", "getWshEventData"}
    assert raw.schema.metadata[b"upstream_provider"] == b"wall_street_horizon"
    with pytest.raises(FileExistsError):
        ibkr_events.capture_events(replace(IBKRConfig(), client_id=74), capture, output)


@pytest.mark.parametrize("failure", ["timeout", "malformed", "unsupported", "wrong_account"])
def test_event_failure_preserves_receipts_without_claiming_complete_coverage(
    case: tuple[Path, EventIB], tmp_path: Path, failure: str
) -> None:
    capture, broker = case
    if failure == "timeout":
        broker.fail = True
    elif failure == "malformed":
        broker.response = "null"
    elif failure == "unsupported":
        broker.metadata = '{"event_types":["wshe_ed"]}'
    else:
        broker.account = "DU_OTHER"
    output = tmp_path / "blocked"
    result = ibkr_events.capture_events(replace(IBKRConfig(), client_id=74), capture, output)
    assert result["status"] == "blocked" and not result["corporate_actions_complete"]
    assert broker.disconnected
    if failure == "timeout":
        assert broker.cancels == 4
        assert not all(pq.read_table(output / "raw.parquet")["complete"].to_pylist())
    if failure in {"unsupported", "wrong_account"}:
        assert not broker.requests
    verify_artifacts(output)


@pytest.mark.parametrize("invalid", ["source", "identity", "incomplete", "client", "history"])
def test_event_capture_rejects_bad_provenance_and_history_destinations_before_connecting(
    case: tuple[Path, EventIB], tmp_path: Path, invalid: str
) -> None:
    capture, broker = case
    config = replace(IBKRConfig(), client_id=74)
    output = tmp_path / "events"
    if invalid == "source":
        path = capture / "contracts.parquet"
        table = pq.read_table(path)
        pq.write_table(
            table.replace_schema_metadata({**table.schema.metadata, b"source": b"alpaca"}), path
        )
    elif invalid == "identity":
        path = capture / "contracts.parquet"
        table = pq.read_table(path)
        rows = table.to_pylist()
        rows[0]["con_id"] = rows[1]["con_id"]
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    elif invalid == "incomplete":
        path = capture / "capture.parquet"
        table = pq.read_table(path)
        rows = table.to_pylist()
        rows[0]["complete"] = False
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    elif invalid == "client":
        config = replace(config, client_id=73)
    else:
        folder = tmp_path / "account"
        folder.mkdir()
        (folder / "registration.parquet").write_bytes(b"historical-account")
        output = folder / "events"
    with pytest.raises(ValueError):
        ibkr_events.capture_events(config, capture, output)
    assert not output.exists() and not broker.requests


def test_event_cli_uses_independent_client_and_preserves_config(
    case: tuple[Path, EventIB], tmp_path: Path
) -> None:
    capture, _ = case
    args = ibkr_cli.parser().parse_args(
        ["events-capture", "--capture", str(capture), "--output", str(tmp_path / "events")]
    )
    assert args.client_id == 74
    assert ibkr_cli.run(args)["status"] == "captured"


def test_market_cli_requires_exploratory_opt_in_without_relabeling_prices(
    case: tuple[Path, EventIB], tmp_path: Path
) -> None:
    capture, broker = case
    output = tmp_path / "snapshot"
    args = ibkr_cli.parser().parse_args(
        ["market-import", "--capture", str(capture), "--output", str(output)]
    )
    with pytest.raises(ValueError, match="opt-in"):
        ibkr_cli.run(args)
    args.allow_exploratory = True
    result = ibkr_cli.run(args)
    assert result["scope"] == "exploratory" and result["source"] == "ibkr"
    saved = load_snapshot(output)
    assert saved.spec.price_basis == "split_adjusted"
    assert saved.spec.volume_unit == "provider_reported"
    assert saved.spec.universe_basis == "current_sample"
    assert saved.bars["available_at"].null_count == saved.bars.num_rows
    assert not broker.requests
