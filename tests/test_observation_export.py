"""权威现金观察状态只读导出，不得重置观察或冒充券商资金。"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from invest import ibkr_cli, ibkr_observation, observation_export
from invest.decision_io import read_decision_contexts
from invest.ibkr_store import EventStore
from invest.research_artifacts import verify_artifacts
from invest.research_data import digest
from tests.test_ibkr_observation import Harness, create


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    result = Harness()
    monkeypatch.setattr(ibkr_observation, "clock", lambda: result.now)
    monkeypatch.setattr(ibkr_observation, "_capture", result.capture)
    return result


def test_observation_export_preserves_identity_cash_window_and_history(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    ibkr_observation.job(account, tmp_path / "captures")
    original = {path: digest(path) for path in account.rglob("*") if path.is_file()}
    expected = ibkr_observation.status(account)
    output = tmp_path / "export"
    result = observation_export.export_observation(account, output)
    assert result["sessions"] == 1 and not result["broker_context_eligible"]
    table = pq.read_table(output / "observation_state.parquet")
    row = table.to_pylist()[0]
    assert row["account_id"] == expected["account_id"] and row["head"] == expected["head"]
    assert row["cash"] == row["initial_cash"] == row["peak_equity"] == Decimal(5000)
    assert str(row["observation_end_session"]) == expected["observation_end_session"]
    assert row["registration_engine_sha256"] == expected["registration_engine_sha256"]
    assert table.schema.metadata[b"context_kind"] == b"observation_state"
    assert not (output / "source_account" / ".writer.lock").exists()
    assert {path: digest(path) for path in original} == original
    verify_artifacts(output)
    with pytest.raises(ValueError, match="decision context schema"):
        read_decision_contexts(table)
    with pytest.raises(FileExistsError):
        observation_export.export_observation(account, output)


def test_export_rejects_a_concurrent_advance_without_touching_the_account(
    tmp_path: Path, harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = create(tmp_path, harness)
    real_status = ibkr_observation._status

    def advancing_status(frozen: Path, now: datetime) -> dict[str, Any]:
        result = real_status(frozen, now)
        with EventStore(account).locked() as store:
            store.append(
                "failure", "concurrent_writer", {"cash": "5000", "peak": "5000"}, at=harness.now
            )
        return result

    monkeypatch.setattr(ibkr_observation, "_status", advancing_status)
    output = tmp_path / "concurrent"
    with pytest.raises(ValueError, match="changed during export"):
        observation_export.export_observation(account, output)
    assert not (output / "observation_state.parquet").exists()
    assert len(EventStore(account).read()) == 2


def test_export_cli_refuses_history_destinations_and_retains_missed_sessions(
    tmp_path: Path, harness: Harness
) -> None:
    account = create(tmp_path, harness)
    harness.now = datetime(2026, 10, 26, 14, tzinfo=UTC)
    ibkr_observation.job(account, tmp_path / "captures")
    with pytest.raises(ValueError, match="historical input"):
        observation_export.export_observation(account, account / "export")
    args = ibkr_cli.parser().parse_args(
        ["observation-export", "--account", str(account), "--output", str(tmp_path / "export")]
    )
    result = ibkr_cli.run(args)
    assert result["missed_sessions"] == 1 and result["sessions"] == 0
    assert result["capital_scope"] == "project_cash_observation"
