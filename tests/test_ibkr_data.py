"""IBKR provenance, precision, adjustment boundaries and offline adapter contracts."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pyarrow.parquet as pq
import pytest

from invest.ibkr_data import quality, save_capture
from invest.ibkr_gateway import IBKRGateway, serializable
from invest.ibkr_models import IBKRConfig, decimal, number, read_config, timestamp
from invest.ibkr_synthetic import SyntheticBroker, demo_capture
from invest.market import read_bars
from invest.quality import latest_completed_session


def test_capture_has_typed_provenance_and_does_not_mislabel_adjusted_bars(tmp_path: Path) -> None:
    capture = demo_capture(SyntheticBroker(), IBKRConfig())
    assert not any(row["status"] == "error" for row in quality(capture))
    path = save_capture(capture, tmp_path)
    for file in path.glob("*.parquet"):
        table = pq.read_table(file)
        assert table.schema.metadata[b"source"] == b"synthetic"
        assert table.schema.metadata[b"environment"] == b"paper"
    manifest = pq.read_table(path / "capture.parquet").to_pylist()[0]
    assert manifest["complete"] and not manifest["legacy_engine_admitted"]
    assert "not TCP wire" in manifest["raw_level"]
    with pytest.raises(ValueError, match="schema"):
        read_bars(path / "historical.parquet", "SPY")
    checks = {r["check"] for r in pq.read_table(path / "quality.parquet").to_pylist()}
    assert {"corporate_actions", "price_basis", "volume_unit", "quote_delayed_or_frozen"} <= checks


@pytest.mark.parametrize(
    "change,check",
    [
        ("quote_type", "quote_type"),
        ("quote_empty", "quote_available"),
        ("duplicate", "duplicate_bar"),
        ("bad_price", "ohlcv"),
        ("missing_history", "historical_available"),
        ("stale", "stale_daily"),
        ("incomplete", "snapshot_complete"),
        ("currency", "qualified_contract"),
    ],
)
def test_bad_or_missing_provider_data_is_saved_as_incomplete(
    tmp_path: Path, change: str, check: str
) -> None:
    capture = demo_capture(SyntheticBroker(), IBKRConfig())
    if change == "quote_type":
        capture.quotes[0]["actual_type"] = None
    elif change == "quote_empty":
        capture.quotes[0].update(bid=None, ask=None, last=None)
    elif change == "duplicate":
        capture.historical.append(dict(capture.historical[0]))
    elif change == "bad_price":
        capture.historical[0]["low"] = Decimal(1000)
    elif change == "missing_history":
        capture.historical.clear()
    elif change == "stale":
        capture.snapshot.captured_at = datetime(2024, 1, 4, 22, tzinfo=UTC)
    elif change == "currency":
        capture.contracts[0]["currency"] = "EUR"
    else:
        capture.snapshot.complete = False
        capture.snapshot.errors = ["Synthetic query timeout"]
    path = save_capture(capture, tmp_path)
    assert not pq.read_table(path / "capture.parquet").to_pylist()[0]["complete"]
    assert check in {r["check"] for r in quality(capture) if r["status"] == "error"}


def test_config_precision_and_time_conventions(tmp_path: Path) -> None:
    path = tmp_path / "ibkr.toml"
    path.write_text('symbols=["SPY"]\nmax_order_notional="700"\n')
    config = read_config(path)
    assert config.client_id == 72 and config.max_order_notional == Decimal(700)
    with pytest.raises(ValueError, match="Paper"):
        replace(config, account="U_LIVE")
    path.write_text("unknown_key=1\n")
    with pytest.raises(ValueError, match="Unknown"):
        read_config(path)
    assert decimal("99.123456789012345678") == Decimal("99.123456789012345678")
    with pytest.raises(ValueError, match="18 decimal"):
        decimal("0.1234567890123456789")
    assert number(float("nan"), optional=True) is None
    with pytest.raises(ValueError, match="timezone"):
        timestamp(datetime(2024, 1, 2))
    assert serializable(float("nan")) is None
    assert serializable(99.1) == "99.1"
    with pytest.raises(ValueError, match="Unsupported"):
        serializable(object())


class Event:
    def __iadd__(self, callback: Any) -> Self:
        self.callback = callback
        return self


@dataclass
class Contract:
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    conId: int = 1
    secType: str = "STK"
    primaryExchange: str = "ARCA"


@dataclass
class Detail:
    minTick: float = 0.01


@dataclass
class AccountValue:
    account: str
    tag: str
    value: str
    currency: str = "USD"
    modelCode: str = ""


@dataclass
class Filter:
    acctCode: str


@dataclass
class Bar:
    date: Any
    open: float = 100
    high: float = 101
    low: float = 99
    close: float = 100
    volume: int = 1000


class FakeIB:
    def __init__(self) -> None:
        self.errorEvent = Event()
        self.accountValueEvent = Event()
        self.client = SimpleNamespace(
            reqAccountUpdates=lambda *args: None, serverVersion=lambda: 178, connect=self.connect
        )
        self.wrapper = SimpleNamespace(marketDataType=lambda *args: None, reqId2Ticker={})
        self.account = "DU_TEST"
        self.disconnected = False
        self.callback = True
        self.calls: list[str] = []
        self.fail_positions = False
        self.fail_history = False

    def connect(self, host: str, port: int, **kwargs: Any) -> None:
        assert kwargs["clientId"] == 72

    def disconnect(self) -> None:
        self.disconnected = True

    def managedAccounts(self) -> list[str]:
        return [self.account]

    def reqAccountUpdates(self, account: str) -> None:
        self.calls.append("account_updates")
        for value in self.accountValues(account):
            self.accountValueEvent.callback(value)

    def reqPositions(self) -> list[Any]:
        if self.fail_positions:
            raise TimeoutError("Synthetic request failure")
        return []

    def reqAllOpenOrders(self) -> list[Any]:
        return []

    def reqCompletedOrders(self, api_only: bool) -> list[Any]:
        return []

    def reqExecutions(self, query: Filter) -> list[Any]:
        return []

    def trades(self) -> list[Any]:
        return []

    def sleep(self, seconds: float) -> None:
        pass

    def accountValues(self, account: str) -> list[AccountValue]:
        return [
            AccountValue(account, "TotalCashValue", "5000"),
            AccountValue(account, "SettledCash", "5000"),
        ]

    def qualifyContracts(self, contract: Contract) -> list[Contract]:
        contract.conId = 1 if contract.symbol == "SPY" else 2
        return [contract]

    def reqContractDetails(self, contract: Contract) -> list[Detail]:
        return [Detail()]

    def reqHistoricalData(self, contract: Contract, **kwargs: Any) -> list[Bar]:
        if self.fail_history:
            raise ValueError("Synthetic history permission failure")
        assert kwargs["formatDate"] == 2 and kwargs["useRTH"]
        return [Bar(latest_completed_session(datetime.now(UTC)))]

    def reqMarketDataType(self, value: int) -> None:
        assert value == 3

    def reqMktData(self, contract: Contract, *args: Any) -> Any:
        ticker = SimpleNamespace(
            contract=contract,
            marketDataType=1,
            time=datetime.now(UTC),
            rtTime=None,
            bid=100.0,
            ask=float("nan"),
            last=100.0,
            bidSize=10,
            askSize=-1,
            lastSize=10,
        )
        self.wrapper.reqId2Ticker[contract.conId] = ticker
        if self.callback:
            self.wrapper.marketDataType(contract.conId, 3)
        return ticker

    def cancelMktData(self, contract: Contract) -> None:
        self.calls.append("cancel_market_data")


@pytest.mark.parametrize("callback", [True, False])
def test_adapter_uses_actual_quote_callback_and_retains_request_response_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, callback: bool
) -> None:
    monkeypatch.setattr("invest.ibkr_gateway.version", lambda name: "2.1.0")
    ib = FakeIB()
    ib.callback = callback
    sdk = SimpleNamespace(IB=lambda: ib, Stock=Contract, ExecutionFilter=Filter)
    with IBKRGateway(IBKRConfig(), sdk) as gateway:
        capture = gateway.capture()
    assert ib.disconnected
    assert capture.snapshot.complete
    assert all(r["actual_type"] == (3 if callback else None) for r in capture.quotes)
    assert all(r["ask"] is None and r["ask_size"] is None for r in capture.quotes)
    assert ib.calls.count("cancel_market_data") == 2
    raw = [json.loads(r["payload"]) for r in capture.raw if r["method"] == "reqHistoricalData"]
    assert raw[0]["kwargs"]["whatToShow"] == "TRADES" and raw[0]["args"][0]["symbol"] == "SPY"
    saved = save_capture(capture, tmp_path)
    assert pq.read_table(saved / "capture.parquet").to_pylist()[0]["complete"] == callback


def test_adapter_rejects_live_accounts_and_retains_partial_query_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ib = FakeIB()
    sdk = SimpleNamespace(IB=lambda: ib, Stock=Contract, ExecutionFilter=Filter)
    ib.account = "U_LIVE"
    with pytest.raises(ValueError, match="live accounts"), IBKRGateway(IBKRConfig(), sdk):
        pass
    assert ib.disconnected
    ib.account = "DU_TEST"
    ib.fail_positions = True
    with IBKRGateway(IBKRConfig(), sdk) as gateway:
        snapshot = gateway.snapshot()
        assert not snapshot.complete and snapshot.cash() == 5000
        assert any(not r["complete"] and r["method"] == "reqPositions" for r in gateway.raw)


def test_history_failure_does_not_hide_available_quotes_or_mark_account_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("invest.ibkr_gateway.version", lambda name: "2.1.0")
    ib = FakeIB()
    ib.fail_history = True
    with IBKRGateway(
        IBKRConfig(), SimpleNamespace(IB=lambda: ib, Stock=Contract, ExecutionFilter=Filter)
    ) as gateway:
        capture = gateway.capture()
    assert capture.snapshot.complete and len(capture.quotes) == 2
    assert capture.errors and not capture.historical


def test_intraday_utc_session_and_completion_are_checked() -> None:
    capture = demo_capture(SyntheticBroker(), IBKRConfig(bar_size="1 min", duration="1 D"))
    for bar in capture.historical:
        bar.update(bar_size="1 min", bar_at=datetime(2024, 1, 2, 20, 59, tzinfo=UTC))
    assert not any(r["status"] == "error" for r in quality(capture))
    capture.historical[0]["bar_at"] = datetime(2024, 1, 2, 3, tzinfo=UTC)
    assert "intraday_timestamp" in {r["check"] for r in quality(capture)}
