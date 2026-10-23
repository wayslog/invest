"""The IBKR cash worker retains the existing heartbeat, backup and alert contract."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from invest.forward_service import check_service, read_service_config, run_service
from invest.research_registry import seal, write_table
from tests.test_ibkr_observation import Harness, create
from tests.test_ibkr_observation import harness as harness


def test_new_account_cli_service_and_backup_share_one_registration(
    tmp_path: Path, harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    from invest.cli import main

    account = create(tmp_path, harness)
    config = tmp_path / "service.toml"
    config.write_text(
        'backend="ibkr_cash"\naccount="account"\ndata_root="data"\n'
        'backup_root="backups"\nstate_root="operations"\ntelegram_required=false\n'
    )
    assert main(["forward-status", "--account", str(account)]) == 0
    initial = json.loads(capsys.readouterr().out)
    assert initial["sessions"] == 0
    harness.now = datetime(2026, 10, 23, 21, 10, tzinfo=UTC)
    assert run_service(config)["outcome"] == "ok"
    assert check_service(config)["healthy"]
    assert main(["forward-status", "--account", str(account)]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["account_id"] == initial["account_id"] and observed["sessions"] == 1
    assert main(["forward-verify", "--account", str(account)]) == 0
    assert json.loads(capsys.readouterr().out)["head"] == observed["head"]
    assert run_service(config)["outcome"] == "ok"
    assert len(harness.calls) == 2  # Preflight and one due session; no duplicated capture.


def test_ibkr_service_never_uses_legacy_acquisition_and_recovers_after_an_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from invest import ibkr_observation

    account = tmp_path / "account"
    account.mkdir()
    config = tmp_path / "service.toml"
    config.write_text(
        'backend="ibkr_cash"\naccount="account"\ndata_root="data"\n'
        'backup_root="backups"\nstate_root="operations"\ntelegram_required=false\n'
    )
    alerts: list[str] = []
    calls: list[tuple[Path, Path, int]] = []
    available = False
    state = {
        "account_id": "new-ibkr-observation",
        "head": "head-0",
        "sessions": 0,
        "last_session": "2026-10-22",
        "missing_sessions": 0,
        "operations": "active",
        "risk_status": "active",
        "engine_matches": True,
    }

    def legacy(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("IBKR observation attempted to use the legacy account or source")

    def worker(path: Path, data: Path, *, attempts: int) -> dict[str, Any]:
        assert path == account
        calls.append((path, data, attempts))
        if not available:
            return {"error": "IBKR capture unavailable", "due": True, "updated": False}
        return {"due": False, "updated": False, "status": "active"}

    def backup(path: Path, output: Path) -> dict[str, Any]:
        assert path == account
        output.mkdir(parents=True)
        write_table(
            pa.Table.from_pylist([{"head": "head-0", "commits": 1}]), output / "backup.parquet"
        )
        seal(output)
        return {"backup": str(output), "head": "head-0"}

    for name in ("forward_job", "forward_status", "verify_forward", "backup_forward"):
        monkeypatch.setattr("invest.forward_service." + name, legacy)
    monkeypatch.setattr(
        "invest.forward_service.send_telegram", lambda text, *args: alerts.append(text)
    )
    monkeypatch.setattr(ibkr_observation, "status", lambda path: state)
    monkeypatch.setattr(
        ibkr_observation, "verify", lambda path: {"head": "head-0", "reconciliation_checks": 3}
    )
    monkeypatch.setattr(ibkr_observation, "job", worker)
    monkeypatch.setattr(ibkr_observation, "backup", backup)
    result = run_service(config)
    assert result["outcome"] == "attention" and result["sessions"] == 0
    assert result["notification"] == "sent" and not check_service(config)["healthy"]
    available = True
    recovered = run_service(config)
    assert recovered["outcome"] == "ok" and recovered["notification"] == "sent"
    assert check_service(config)["healthy"]
    assert len(calls) == 2 and calls[-1][2] == 2
    assert "运行已恢复" in alerts[-1]
    assert len(list((tmp_path / "backups").glob("*/*"))) == 1


def test_unknown_service_backend_is_rejected_instead_of_falling_back(tmp_path: Path) -> None:
    path = tmp_path / "service.toml"
    path.write_text(
        'backend="ibkr_typo"\naccount="account"\ndata_root="data"\n'
        'backup_root="backups"\nstate_root="operations"\n'
    )
    with pytest.raises(ValueError, match="Unknown observation service backend"):
        read_service_config(path)
