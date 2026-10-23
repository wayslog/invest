"""Real-command idempotence without time injection exposed to CLI users."""

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

import pytest

from invest import ibkr_cli
from invest import ibkr_execution as execution
from invest.ibkr_data import save_capture
from invest.ibkr_models import IBKRConfig
from invest.ibkr_store import EventStore
from invest.ibkr_synthetic import SyntheticBroker, demo_capture


def test_intent_retry_keeps_the_original_decision_time_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock(datetime):
        current = datetime(2024, 1, 2, 22, tzinfo=UTC)

        @classmethod
        def now(cls, tz: object = None) -> Self:
            return cls.fromtimestamp(cls.current.timestamp(), UTC)

    monkeypatch.setattr(ibkr_cli, "datetime", Clock)
    monkeypatch.setattr(execution, "datetime", Clock)
    broker = SyntheticBroker()
    broker.source = "ibkr"  # A test double; no external connection in this test.
    store = EventStore(tmp_path / "journal")
    execution.initialize(store, broker, IBKRConfig())
    capture = demo_capture(broker, IBKRConfig())
    batch = save_capture(capture, tmp_path / "captures")
    args = ibkr_cli.parser().parse_args(
        [
            "intent",
            "--journal",
            str(store.directory),
            "--capture",
            str(batch),
            "--intent-id",
            "buy",
            "--symbol",
            "SPY",
            "--side",
            "BUY",
            "--quantity",
            "1",
            "--limit-price",
            "100",
        ]
    )
    assert ibkr_cli.run(args)["updated"]
    before = [e for e in store.read() if e["kind"] == "intent"]
    Clock.current += timedelta(days=1)
    assert not ibkr_cli.run(args)["updated"]
    assert [e for e in store.read() if e["kind"] == "intent"] == before
    args.limit_price = "100.001"
    with pytest.raises(ValueError, match="minimum tick"):
        ibkr_cli.run(args)


def test_synthetic_demo_cli_and_missing_sdk_are_actionable(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "invest-ibkr",
            "demo",
            "--output",
            str(tmp_path / "demo"),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"source": "synthetic"' in result.stdout
    assert '"reconciled": true' in result.stdout
    failed = subprocess.run(
        [
            "invest-ibkr",
            "capture",
            "--config",
            "configs/ibkr.toml",
            "--output",
            str(tmp_path / "real"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert failed.returncode and "make ibkr-install" in failed.stderr


def test_capital_directory_cannot_be_used_for_an_execution_drill(tmp_path: Path) -> None:
    directory = tmp_path / "m3-account"
    directory.mkdir()
    registration = directory / "registration.parquet"
    registration.write_bytes(b"M3 private registration")
    broker = SyntheticBroker()
    with pytest.raises(ValueError, match="preserve M3"):
        execution.initialize(EventStore(directory), broker, IBKRConfig(), at=broker.now)
    assert registration.read_bytes() == b"M3 private registration"
