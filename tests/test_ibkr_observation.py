"""Cash operational evidence is timely, restartable, and separate from broker capital."""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from invest import ibkr_observation as observation
from invest.ibkr_data import save_capture
from invest.ibkr_models import read_config
from invest.ibkr_store import EventStore
from invest.ibkr_synthetic import SyntheticBroker, demo_capture
from invest.quality import latest_completed_session, regular_sessions
from invest.research_registry import verify_inventory


@dataclass
class Harness:
    now: datetime = datetime(2026, 10, 23, 9, tzinfo=UTC)
    calls: list[Path] = field(default_factory=list)
    failure: bool = False
    source: str = "ibkr"
    broker_account: str = "DU_TEST"
    price: Decimal = Decimal("100")
    capture_duration: timedelta = timedelta(0)
    omit_last: bool = False

    def capture(self, python: Path, runner: Path, config: Path, output: Path) -> Path:
        self.calls.append(output)
        if self.failure:
            raise ValueError("Private DU_TEST account error must not escape to a service receipt")
        self.now += self.capture_duration
        broker = SyntheticBroker()
        broker.now = self.now
        capture = demo_capture(broker, read_config(config))
        capture.snapshot.source = self.source
        capture.snapshot.account = self.broker_account
        capture.snapshot.account_values = [
            {
                "account": self.broker_account,
                "tag": "TotalCashValue",
                "value": "1000000.00",
                "currency": "USD",
                "model_code": "",
            }
        ]
        end = latest_completed_session(self.now)
        dates = regular_sessions(end - timedelta(days=10), end)["date"].to_pylist()[-5:]
        capture.historical = [
            {
                **row,
                "session": session,
                "open": self.price,
                "high": self.price,
                "low": self.price,
                "close": self.price,
            }
            for row in capture.historical
            for session in dates
            if not self.omit_last or session != end
        ]
        return save_capture(capture, output)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    result = Harness()
    monkeypatch.setattr(observation, "clock", lambda: result.now)
    monkeypatch.setattr(observation, "_capture", result.capture)
    return result


def create(tmp_path: Path, harness: Harness) -> Path:
    config = tmp_path / "ibkr.toml"
    config.write_text('client_id=73\nsymbols=["SPY", "XLF"]\nduration="5 D"\n')
    account = tmp_path / "account"
    observation.initialize(
        account, config, tmp_path / "sdk-python", actor="user", reason="Explicit fresh observation"
    )
    return account


def test_new_observation_is_zero_days_and_does_not_import_broker_million(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    status = observation.status(account)
    assert status["sessions"] == status["decision_sessions"] == status["missed_sessions"] == 0
    assert status["cash"] == status["peak"] == "5000.00"
    assert status["source"] == "ibkr" and status["operations"] == "active"
    assert status["last_session"] == "2026-10-22"
    assert status["observation_start_session"] == "2026-10-23"
    assert status["registered_sessions"] == 60
    assert status["next_capture_after"] == "2026-10-23T21:00:00+00:00"
    assert status["decision_deadline"] == "2026-10-26T13:30:00+00:00"
    assert not status["coverage_met"] and not status["formal_strategy_qualified"]
    assert observation.verify(account)["reconciliation_checks"] == 4
    assert not observation.job(account, tmp_path / "data")["due"]
    assert len(harness.calls) == 1
    manifest = pq.read_metadata(account / "registration.parquet")
    assert manifest.row_group(0).column(0).compression == "ZSTD"


def test_registration_finishes_after_open_so_first_day_moves_forward(
    tmp_path: Path, harness: Harness
) -> None:
    harness.capture_duration = timedelta(hours=5)
    account = create(tmp_path, harness)
    assert observation.status(account)["observation_start_session"] == "2026-10-26"
    assert observation.status(account)["sessions"] == 0


def test_registration_retry_and_candidate_directory_move_preserve_identity(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    original = observation.status(account)
    repeated = observation.initialize(
        account,
        tmp_path / "ibkr.toml",
        tmp_path / "sdk-python",
        actor="retry",
        reason="Retry same registration",
    )
    assert repeated["account_id"] == original["account_id"]
    assert len(harness.calls) == 1
    relocated = tmp_path / "active"
    account.rename(relocated)
    assert observation.verify(relocated)["head"] == original["head"]
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    assert observation.job(relocated, tmp_path / "data")["updated"]
    assert observation.status(relocated)["sessions"] == 1


def test_daily_observation_is_idempotent_and_history_revisions_do_not_restate_cash(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    assert observation.job(account, tmp_path / "data")["updated"]
    original = observation.status(account)
    first = (account / "events" / "00000001.parquet").read_bytes()
    assert original["sessions"] == 1
    assert not observation.job(account, tmp_path / "data")["updated"]
    assert len(harness.calls) == 2
    harness.price = Decimal("123.45")
    harness.now = datetime(2026, 10, 26, 21, 10, tzinfo=UTC)
    assert observation.job(account, tmp_path / "data")["updated"]
    status = observation.status(account)
    assert status["sessions"] == 2 and status["operations"] == "active"
    assert status["cash"] == status["peak"] == original["cash"]
    assert (account / "events" / "00000001.parquet").read_bytes() == first
    assert observation.verify(account)["reconciliation_checks"] == 10
    saved = observation.backup(account, tmp_path / "backup")
    assert saved["head"] == status["head"]
    verify_inventory(tmp_path / "backup")


def test_missed_day_remains_missed_but_does_not_permanently_block_later_days(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    end = observation.status(account)["observation_end_session"]
    harness.now = datetime(2026, 10, 26, 14, tzinfo=UTC)
    result = observation.job(account, tmp_path / "data")
    assert "error" in result and result["updated"]
    status = observation.status(account)
    assert status["sessions"] == 0 and status["missed_sessions"] == 1
    assert status["missing_sessions"] == 0 and status["operations"] == "active"
    assert len(harness.calls) == 1  # No retroactive capture pretending Friday was observed.
    assert "error" not in observation.job(account, tmp_path / "data")
    harness.now = datetime(2026, 10, 26, 21, 10, tzinfo=UTC)
    assert "error" not in observation.job(account, tmp_path / "data")
    status = observation.status(account)
    assert status["sessions"] == 1 and status["missed_sessions"] == 1
    assert status["observation_end_session"] == end


def test_gateway_failure_is_recorded_without_private_details_and_next_run_recovers(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    harness.failure = True
    failed = observation.job(account, tmp_path / "data", attempts=2)
    assert "error" in failed and "DU_TEST" not in str(failed)
    assert observation.status(account)["sessions"] == 0
    events = EventStore(account).read()
    assert [e["kind"] for e in events] == ["register", "failure", "failure"]
    assert "DU_TEST" not in json.dumps([e["payload"] for e in events])
    harness.failure = False
    harness.now += timedelta(minutes=1)
    assert observation.job(account, tmp_path / "data")["updated"]
    assert observation.status(account)["sessions"] == 1
    assert observation.status(account)["operations"] == "active"


def test_capture_crossing_deadline_is_retained_but_never_counted_timely(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 26, 13, 29, tzinfo=UTC)
    harness.capture_duration = timedelta(minutes=2)
    result = observation.job(account, tmp_path / "data")
    assert "error" in result
    status = observation.status(account)
    assert status["sessions"] == 0 and status["missed_sessions"] == 1
    event = EventStore(account).read()[-1]
    assert event["kind"] == "missed" and Path(event["payload"]["capture"]).is_dir()


def test_capture_validation_crossing_deadline_cannot_be_backdated(
    tmp_path: Path, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 26, 13, 29, tzinfo=UTC)
    original = observation._validate_capture

    def delayed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        harness.now += timedelta(minutes=2)
        return result

    monkeypatch.setattr(observation, "_validate_capture", delayed)
    assert "error" in observation.job(account, tmp_path / "data")
    assert observation.status(account)["sessions"] == 0
    assert observation.status(account)["missed_sessions"] == 1
    assert EventStore(account).read()[-1]["recorded_at"] == harness.now


def test_preflight_validation_crossing_open_selects_future_start(
    tmp_path: Path, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.now = datetime(2026, 10, 23, 13, 29, tzinfo=UTC)
    original = observation._validate_capture

    def delayed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        harness.now += timedelta(minutes=2)
        return result

    monkeypatch.setattr(observation, "_validate_capture", delayed)
    account = create(tmp_path, harness)
    assert observation.status(account)["observation_start_session"] == "2026-10-26"
    assert EventStore(account).read()[0]["recorded_at"] == harness.now


@pytest.mark.parametrize("change", ["source", "account", "missing"])
def test_wrong_source_account_or_missing_day_cannot_count(
    tmp_path: Path, harness: Harness, change: str
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    if change == "source":
        harness.source = "synthetic"
    elif change == "account":
        harness.broker_account = "DU_OTHER"
    else:
        harness.omit_last = True
    assert "error" in observation.job(account, tmp_path / "data", attempts=1)
    assert observation.status(account)["sessions"] == 0


def test_clock_and_engine_change_do_not_mutate_registration(
    tmp_path: Path, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = create(tmp_path, harness)
    body = (account / "registration.parquet").read_bytes()
    harness.now -= timedelta(seconds=1)
    with pytest.raises(ValueError, match="backwards"):
        observation.job(account, tmp_path / "data")
    harness.now += timedelta(days=1)
    monkeypatch.setattr(observation, "engine_digest", lambda: "different-engine")
    assert not observation.status(account)["engine_matches"]
    with pytest.raises(ValueError, match="engine changed"):
        observation.job(account, tmp_path / "data")
    assert (account / "registration.parquet").read_bytes() == body


def test_finished_window_does_not_expand_after_misses(tmp_path: Path, harness: Harness) -> None:
    account = create(tmp_path, harness)
    schedule = pq.read_table(account / "schedule.parquet").to_pylist()
    harness.now = schedule[-1]["deadline"] + timedelta(minutes=1)
    result = observation.job(account, tmp_path / "data")
    assert "error" in result
    status = observation.status(account)
    assert status["operations"] == "completed"
    assert status["sessions"] == 0 and status["missed_sessions"] == 60
    assert not status["coverage_met"]
    assert status["next_capture_after"] is None and not status["missing_sessions"]
    assert len(harness.calls) == 1
    assert not observation.job(account, tmp_path / "data")["updated"]


def test_tampered_cash_and_duplicate_day_are_detected(tmp_path: Path, harness: Harness) -> None:
    account = create(tmp_path, harness)
    store = EventStore(account)
    with store.locked():
        store.append("failure", "bad-cash", {"cash": "1000000", "peak": "5000"}, harness.now)
    with pytest.raises(ValueError, match="project funds"):
        observation.verify(account)


def test_half_day_and_daylight_savings_capture_windows() -> None:
    previous, schedule = observation._schedule(datetime(2026, 11, 27, 8, tzinfo=UTC))
    first = schedule.to_pylist()[0]
    assert previous == date(2026, 11, 25)
    assert first["capture_after"] == datetime(2026, 11, 27, 19, tzinfo=UTC)
    assert first["deadline"] == datetime(2026, 11, 30, 14, 30, tzinfo=UTC)


def test_failed_preflight_preserves_failure_batch_and_creates_no_account(
    tmp_path: Path, harness: Harness
) -> None:
    harness.omit_last = True
    with pytest.raises(ValueError, match="incomplete"):
        create(tmp_path, harness)
    assert not (tmp_path / "account").exists()
    assert list((tmp_path / "account-captures" / "preflight").glob("*/capture.parquet"))


def test_sdk_subprocess_preserves_venv_executable_and_redacts_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[list[str]] = []

    def fail(command: list[str], **kwargs: Any) -> Any:
        recorded.append(command)
        return replace_stub(returncode=1, stdout=b"", stderr=b"DU_PRIVATE")

    def replace_stub(**values: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(**values)

    monkeypatch.setattr("invest.ibkr_observation.subprocess.run", fail)
    with pytest.raises(ValueError, match="read-only capture failed") as caught:
        observation._capture(
            tmp_path / "venv/bin/python", tmp_path / "run.py", tmp_path / "config.toml", tmp_path
        )
    assert "DU_PRIVATE" not in str(caught.value)
    assert recorded[0][0] == str(tmp_path / "venv/bin/python")
    receipt = pq.read_table(next((tmp_path / "invocations").glob("*.parquet"))).to_pylist()[0]
    assert receipt["returncode"] == 1 and receipt["stderr"] == b"DU_PRIVATE"


def test_sdk_timeout_keeps_partial_diagnostics_in_private_parquet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("sdk", 240, output=b"partial", stderr=b"DU_PRIVATE")

    monkeypatch.setattr("invest.ibkr_observation.subprocess.run", fail)
    with pytest.raises(ValueError, match="could not complete") as caught:
        observation._capture(
            tmp_path / "python", tmp_path / "run.py", tmp_path / "config.toml", tmp_path
        )
    assert "DU_PRIVATE" not in str(caught.value)
    row = pq.read_table(next((tmp_path / "invocations").glob("*.parquet"))).to_pylist()[0]
    assert row["outcome"] == "timeout" and row["returncode"] is None
    assert row["stdout"] == b"partial" and row["stderr"] == b"DU_PRIVATE"
