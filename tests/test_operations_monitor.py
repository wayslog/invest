"""Read-only M3 progress, liveness, public reports and independent failure delivery."""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow.parquet as pq
import pytest

from tests.test_deployment import ROOT, load_tool


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(ROOT / "deploy"))
    return load_tool("monitor")


def snapshot(now: datetime) -> dict[str, Any]:
    return {
        "release": "c" * 40,
        "Account": {
            "observed_at": now.isoformat(),
            "operations": "active",
            "risk_status": "active",
            "accounting_verified": True,
            "engine_matches": True,
            "sessions": 1,
            "registered_sessions": 60,
            "decision_sessions": 1,
            "missing_sessions": 0,
            "last_session": "2026-10-20",
            "observation_end_session": "2027-01-14",
            "coverage_met": False,
            "next_capture_after": "2026-10-22T04:15:00+00:00",
            "decision_deadline": "2026-10-22T13:30:00+00:00",
            "account_id": "private-account",
            "cash": "private-cash",
        },
        "Timers": {
            "daily_active": True,
            "daily_enabled": True,
            "health_active": True,
            "health_enabled": True,
        },
        "runs": {"finished_at": (now - timedelta(minutes=2)).isoformat(), "outcome": "ok"},
        "health": {"recorded_at": (now - timedelta(minutes=5)).isoformat(), "healthy": True},
        "Backup": {"present": True, "matches_current": True},
        "Window": {
            "runs": 24,
            "updated_runs": 1,
            "failed_runs": 0,
            "systemd_failures": 1,
            "health_failures": 0,
            "notification_failures": 0,
        },
    }


@pytest.mark.parametrize("hour,minute", [(3, 20), (4, 16)])
def test_pending_data_is_not_reported_as_a_missed_observation(
    monitor: ModuleType, hour: int, minute: int
) -> None:
    now = datetime(2026, 10, 22, hour, minute, tzinfo=UTC)
    source = snapshot(now)
    source["Account"]["missing_sessions"] = int(hour == 4)
    row = monitor.assess(source, now)
    assert row["healthy"] and row["sessions"] == 1
    assert row["registered_sessions"] == 60
    assert row["missing_sessions"] == int(hour == 4)
    assert row["systemd_failures_24h"] == 1
    assert "private-" not in json.dumps(row, default=str)
    text = monitor.markdown(row)
    assert "1/60" in text and "2026-10-22 12:15:00" in text


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("Timers", "daily_enabled", False),
        ("Timers", "health_active", False),
        ("Account", "operations", "paused"),
        ("Account", "risk_status", "halted"),
        ("Account", "accounting_verified", False),
        ("Backup", "matches_current", False),
        ("runs", "finished_at", "2026-10-21T23:00:00+00:00"),
        ("runs", "outcome", "error"),
        ("health", "healthy", False),
        ("health", "recorded_at", "2026-10-22T01:00:00+00:00"),
        ("Account", "missing_sessions", 1),
    ],
)
def test_operation_failures_and_overdue_sessions_need_attention(
    monitor: ModuleType, section: str, field: str, value: Any
) -> None:
    now = datetime(2026, 10, 22, 4, 45, tzinfo=UTC)
    source = snapshot(now)
    source[section][field] = value
    row = monitor.assess(source, now)
    assert not row["healthy"] and row["issues"]


def test_completed_observation_does_not_require_live_timers(monitor: ModuleType) -> None:
    now = datetime(2027, 1, 16, 12, tzinfo=UTC)
    source = snapshot(now)
    source["Account"].update(operations="completed", sessions=60, coverage_met=True)
    source["Timers"] = dict.fromkeys(source["Timers"], False)
    source["runs"]["finished_at"] = (now - timedelta(days=1)).isoformat()
    source["health"]["recorded_at"] = (now - timedelta(days=1)).isoformat()
    assert monitor.assess(source, now)["healthy"]


def test_transient_overlap_is_retried_without_changing_the_account(
    monitor: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    waits: list[int] = []
    source = snapshot(datetime.now(UTC))

    def execute(operation: str, artifact: Path | None) -> None:
        calls.append(operation)
        assert artifact is None
        if len(calls) == 1:
            raise RuntimeError("writer still running")
        for name, value in source.items():
            print(name + ": " + (value if name == "release" else json.dumps(value)))
        print("Release: " + source["release"])

    monkeypatch.setattr(monitor, "execute", execute)
    monkeypatch.setattr(monitor.time, "sleep", waits.append)
    result = monitor.probe()
    assert calls == ["inspect", "inspect"] and waits == [20]
    assert result["Account"]["sessions"] == 1


@pytest.mark.parametrize("mode", ["scheduled", "manual", "recovery", "offline", "delivery_failed"])
def test_reports_and_notifications_work_even_when_the_host_is_offline(
    monitor: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    notices: list[str] = []

    def probe() -> dict[str, Any]:
        if mode == "offline":
            raise RuntimeError("private-key-and-host-details")
        return snapshot(datetime.now(UTC))

    def send(text: str, token: str, uid: str) -> None:
        assert token == "INVEST_TELEGRAM_BOT_TOKEN" and uid == "INVEST_TELEGRAM_ALLOWED_UID"
        notices.append(text)
        if mode == "delivery_failed":
            raise ValueError("private-bot-token")

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv(
        "GITHUB_EVENT_NAME", "schedule" if mode == "scheduled" else "workflow_dispatch"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/invest")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(monitor, "probe", probe)
    monkeypatch.setattr(monitor, "send_telegram", send)
    monkeypatch.setattr(monitor, "previous_failure", lambda: mode == "recovery")
    target = tmp_path / "report.parquet"
    assert monitor.run_monitor(target) == int(mode in {"offline", "delivery_failed"})
    table = pq.read_table(target)
    assert table.schema.equals(monitor.REPORT_SCHEMA, check_metadata=True)
    assert pq.read_metadata(target).row_group(0).column(0).compression == "ZSTD"
    assert bool(notices) == (mode != "scheduled")
    if mode == "recovery":
        assert "已恢复" in notices[0]
    if mode == "offline":
        assert "主机外监控异常" in notices[0] and table["sessions"][0].as_py() is None
    published = (
        summary.read_text() + capsys.readouterr().out + str(table.to_pylist()) + str(notices)
    )
    assert "private-" not in published


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_recovery_uses_the_previous_completed_monitor_run(
    monitor: ModuleType, monkeypatch: pytest.MonkeyPatch, conclusion: str
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/invest")
    monkeypatch.setenv("GH_TOKEN", "private-github-token")

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert "workflows/monitor.yml/runs" in command[-1]
        assert "private-" not in " ".join(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {"workflow_runs": [{"conclusion": "cancelled"}, {"conclusion": conclusion}]}
            ).encode(),
        )

    monkeypatch.setattr(monitor.subprocess, "run", run)
    assert monitor.previous_failure() == (conclusion == "failure")
