import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from invest import forward
from invest.forward import forward_status
from invest.forward_service import (
    check_service,
    notification_test,
    read_service_config,
    run_service,
    system_failure,
)
from tests.test_forward import initialize, setup, timestamp


def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    account, _, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    config = tmp_path / "service.toml"
    config.write_text(
        'account="account"\ndata_root="data"\nbackup_root="backups"\n'
        'state_root="operations"\ntelegram_required=false\n'
    )
    alerts: list[str] = []
    monkeypatch.setattr(forward, "clock", lambda: timestamp(date(2024, 1, 5)))
    monkeypatch.setattr(
        "invest.forward_service.send_telegram", lambda text, *args: alerts.append(text)
    )
    monkeypatch.setattr(
        "invest.forward_service.forward_job",
        lambda *args, **kwargs: {"updated": False, "due": False, "status": "active"},
    )
    return config, alerts


def test_idle_service_still_reconciles_backs_up_and_records_a_healthy_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, alerts = service(tmp_path, monkeypatch)
    result = run_service(config)
    assert result["outcome"] == "ok" and not result["due"]
    receipt = pq.read_table(result["record"]).to_pylist()[0]
    assert receipt["head"] == forward_status(tmp_path / "account")["head"]
    assert Path(receipt["backup"]).is_dir()
    assert check_service(config)["healthy"]
    assert run_service(config)["outcome"] == "ok"
    assert len(list((tmp_path / "backups").glob("*/*"))) == 1
    assert not alerts


def test_service_and_health_cli_serialize_real_receipts_and_preserve_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from invest.cli import main

    config, _ = service(tmp_path, monkeypatch)
    command = ["forward-service", "--config", str(config)]
    assert main(command) == 0
    output = json.loads(capsys.readouterr().out)
    durable = pq.read_table(output["record"]).to_pylist()[0]
    assert output["started_at"] == durable["started_at"].isoformat()
    assert output["finished_at"] == durable["finished_at"].isoformat()
    assert output["head"] == durable["head"] and output["outcome"] == "ok"
    assert main(["forward-health", "--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["healthy"]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["head"] == durable["head"]

    def failure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("Acquisition unavailable")

    monkeypatch.setattr("invest.forward_service.forward_job", failure)
    assert main(command) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["outcome"] == "error" and output["error"] == "Acquisition unavailable"
    assert pq.read_table(output["record"])["outcome"][0].as_py() == "error"
    assert main(["forward-health", "--config", str(config)]) == 1
    assert not json.loads(capsys.readouterr().out)["healthy"]


def test_service_records_unexpected_failures_deduplicates_alerts_and_announces_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, alerts = service(tmp_path, monkeypatch)

    def failure(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Injected acquisition process crash")

    monkeypatch.setattr("invest.forward_service.forward_job", failure)
    first, second = run_service(config), run_service(config)
    assert first["outcome"] == "error" and first["notification"] == "sent"
    assert second["notification"] == "suppressed" and len(alerts) == 1
    assert not check_service(config)["healthy"]
    monkeypatch.setattr(
        "invest.forward_service.forward_job",
        lambda *args, **kwargs: {"updated": False, "due": False, "status": "active"},
    )
    assert run_service(config)["notification"] == "sent"
    assert "运行已恢复" in alerts[-1]
    assert check_service(config)["healthy"]


def test_watchdog_detects_missed_runs_and_missing_backup_without_changing_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, alerts = service(tmp_path, monkeypatch)
    result = run_service(config)
    head = result["head"]
    monkeypatch.setattr(forward, "clock", lambda: timestamp(date(2024, 1, 5)) + timedelta(hours=3))
    assert "stale" in check_service(config)["error"]
    monkeypatch.setattr(
        forward, "clock", lambda: timestamp(date(2024, 1, 5)) + timedelta(minutes=1)
    )
    (Path(result["backup"]) / "backup.parquet").unlink()
    assert not check_service(config)["healthy"]
    assert forward_status(tmp_path / "account")["head"] == head
    assert len(alerts) == 2


def test_backup_error_is_an_alert_and_not_a_successful_reconciliation_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, alerts = service(tmp_path, monkeypatch)

    def failed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("Independent backup storage unavailable")

    monkeypatch.setattr("invest.forward_service.backup_forward", failed)
    result = run_service(config)
    assert result["outcome"] == "error" and "storage unavailable" in result["error"]
    assert alerts and not check_service(config)["healthy"]


def test_configuration_does_not_allow_output_inside_the_capital_account(tmp_path: Path) -> None:
    config = tmp_path / "bad.toml"
    config.write_text(
        'account="account"\ndata_root="account/inputs"\nbackup_root="backups"\nstate_root="ops"\n'
    )
    with pytest.raises(ValueError, match="separate roots"):
        read_service_config(config)


def test_systemd_failure_notifies_and_deployment_test_is_never_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, alerts = service(tmp_path, monkeypatch)
    assert system_failure(config)["notification"] == "sent"
    assert system_failure(config)["notification"] == "suppressed"
    assert notification_test(config)["notification"] == "sent"
    assert notification_test(config)["notification"] == "sent"
    assert len(alerts) == 3
