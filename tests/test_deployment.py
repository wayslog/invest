"""Account continuity, trusted-host deployment, private transport and redaction."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(filename, ROOT / "deploy" / f"{filename}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_tool("release")
runner = load_tool("github_actions")


def test_ibkr_capture_transports_tested_source_and_keeps_financial_deploy_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in {
        "INVEST_SSH_HOST": "host.example",
        "INVEST_SSH_PRIVATE_KEY": "private-key",
        "INVEST_DEPLOY_COMMIT": "c" * 40,
        "INVEST_DEPLOY_RUN": "555-1",
    }.items():
        monkeypatch.setenv(name, value)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "source.tar.gz").write_bytes(b"tested source")
    calls = []

    def run(command: list[str], label: str, **kwargs: Any) -> bytes:
        calls.append(label)
        assert "private-key" not in " ".join(command)
        if label == "Capture IBKR Paper data":
            assert kwargs["data"] == (ROOT / "deploy/ibkr_capture.sh").read_bytes()
            return b'{"complete":true,"kind":"daily"}\n{"complete":true,"kind":"minute"}\n'
        return b""

    monkeypatch.setattr(runner, "run_quiet", run)
    runner.execute("ibkr-capture", artifact)
    assert calls == [
        "Host preflight",
        "Prepare M4 staging",
        "Transfer tested M4 source",
        "Capture IBKR Paper data",
        "Clean M4 staging",
    ]
    assert '"kind":"daily"' in capsys.readouterr().out
    script = (ROOT / "deploy/ibkr_capture.sh").read_text()
    assert "/opt/invest-ibkr/releases" in script and "systemctl" not in script
    assert "forward-migrate" not in script and "forward-run" not in script


def bundle(tmp_path: Path, members: list[tarfile.TarInfo]) -> Path:
    output = tmp_path / "account.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        for member in members:
            archive.addfile(member, io.BytesIO(b"x" * member.size) if member.size else None)
    return output


def test_account_archive_round_trip_is_private_and_exclusive(tmp_path: Path) -> None:
    entry = tarfile.TarInfo("account/journal/00000000/journal.parquet")
    entry.size = 8
    entry.mode = 0o777
    archive = bundle(tmp_path, [entry])
    destination = tmp_path / "new"
    account = release.extract_account(archive, destination)
    record = account / "journal/00000000/journal.parquet"
    assert record.read_bytes() == b"xxxxxxxx"
    assert record.stat().st_mode & 0o777 == 0o600
    assert account.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match="must not exist"):
        release.extract_account(archive, destination)
    assert record.read_bytes() == b"xxxxxxxx"


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": "other"},
        {"head": "c" * 64},
        {"engine_matches": False},
        {"operations": "paused"},
        {"operations": "stopped"},
        {"operations": "completed"},
        {"mode": "qualified_strategy"},
        {"mode": "drill"},
    ],
)
def test_deployment_gate_cannot_replace_or_resume_an_account(change: dict[str, Any]) -> None:
    status = {
        "account_id": "a" * 32,
        "head": "b" * 64,
        "engine_matches": True,
        "operations": "active",
        "mode": "cash_observation",
    }
    release.check_identity(status)
    status.update(change)
    original = status.copy()
    with pytest.raises(ValueError):
        release.check_identity(status, "a" * 32, "b" * 64)
    assert status == original


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "qualified_strategy"},
        {"operations": "paused"},
        {"operations": "stopped"},
        {"risk_status": "halted"},
        {"missing_sessions": 1},
        {"engine_matches": True},
    ],
)
def test_explicit_migration_cannot_resume_unready_or_risk_halted_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    status = {
        "mode": "cash_observation",
        "operations": "active",
        "risk_status": "active",
        "missing_sessions": 0,
        "engine_matches": False,
    }
    status.update(change)
    monkeypatch.setattr("invest.forward.forward_status", lambda account: status)
    with pytest.raises(ValueError, match="Explicit migration requires"):
        release.migration_identity(tmp_path / "account")


@pytest.mark.parametrize("tamper", [False, True])
def test_explicit_migration_reads_private_request_and_checks_capital_equivalence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: bool
) -> None:
    import pyarrow as pa

    state = {"cash": 5000, "peak": 5000, "operations": "active", "risk_status": "active"}
    original = {
        "account_id": "a" * 32,
        "head": "b" * 64,
        "active_engine_sha256": "c" * 64,
        "engine_matches": False,
        "mode": "cash_observation",
        "operations": "active",
    }
    current = original.copy()
    calls: list[str] = []
    history = tmp_path / "account/journal/0"
    history.mkdir(parents=True)
    inventory = history / "files.parquet"
    inventory.write_bytes(b"original immutable inventory")

    class State:
        def tables(self) -> dict[str, Any]:
            return {"state": pa.Table.from_pylist([state.copy()])}

    monkeypatch.setattr(release, "migration_identity", lambda account: original.copy())
    monkeypatch.setattr("invest.forward.account_lock", lambda account: nullcontext())
    monkeypatch.setattr("invest.forward._load", lambda account: ([history], None, None, State()))
    monkeypatch.setattr("invest.forward.forward_status", lambda account: current.copy())
    monkeypatch.setattr("invest.forward.verify_forward", lambda account: {"head": current["head"]})

    def migrate(*args: Any) -> dict[str, Any]:
        assert args[1:3] == ("b" * 64, "c" * 64)
        assert args[-2:] == ("owner", "Fix CLI timestamp output")
        calls.append("migrate")
        current.update(head="d" * 64, engine_matches=True, operations="paused")
        state["operations"] = "paused"
        return {"head": "d" * 64}

    def resume(*args: Any) -> None:
        assert args[1:3] == ("resume", "owner")
        calls.append("resume")
        current.update(head="e" * 64, operations="active")
        state["operations"] = "active"
        if tamper:
            state["cash"] = 9999

    monkeypatch.setattr("invest.forward_migration.migrate_forward", migrate)
    monkeypatch.setattr("invest.forward.control_forward", resume)
    monkeypatch.setattr(
        release.sys, "stdin", io.StringIO('actor="owner"\nreason="Fix CLI timestamp output"\n')
    )
    arguments = (tmp_path / "account", "a" * 32, "b" * 64, Path("-"), tmp_path / "backup")
    if tamper:
        with pytest.raises(ValueError, match="capital, risk, obligations"):
            release.migrate_account(*arguments)
    else:
        release.migrate_account(*arguments)
    assert calls == ["migrate", "resume"]
    assert inventory.read_bytes() == b"original immutable inventory"


@pytest.mark.parametrize(
    ("with_account", "with_migration"),
    [(False, False), (True, False), (False, True)],
)
def test_ssh_transport_trusts_host_and_keeps_secrets_in_private_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    with_account: bool,
    with_migration: bool,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    source = artifact / "tested.tar.gz"
    source.write_bytes(b"tested source bytes")
    environment = {
        "INVEST_SSH_HOST": "host.example",
        "INVEST_SSH_USER": "root",
        "INVEST_SSH_PORT": "22",
        "INVEST_SSH_PRIVATE_KEY": "private-key-material",
        "INVEST_DEPLOY_COMMIT": "c" * 40,
        "INVEST_DEPLOY_RUN": "123-1",
        "APCA_API_KEY_ID": "secret-market-key",
        "APCA_API_SECRET_KEY": "secret-market-value",
        "INVEST_TELEGRAM_BOT_TOKEN": "123:secret-bot-token",
        "INVEST_TELEGRAM_ALLOWED_UID": "12345",
        "INVEST_MIGRATION_REASON": "Fix CLI receipt timestamps without changing accounting",
        "GITHUB_ACTOR": "owner",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    calls: list[str] = []

    def fake_run(command: list[str], label: str, **kwargs: Any) -> None:
        calls.append(label)
        if label == "Prepare existing local account":
            assert command[2] == "pack-account"
            Path(command[-1]).write_bytes(b"private account bytes")
            return
        assert "StrictHostKeyChecking=no" in command
        assert "UserKnownHostsFile=/dev/null" in command
        assert "GlobalKnownHostsFile=/dev/null" in command
        assert "ForwardAgent=no" in command and "BatchMode=yes" in command
        key = Path(command[command.index("-i") + 1])
        assert key.stat().st_mode & 0o777 == 0o600
        assert key.read_text().strip() == "private-key-material"
        assert "secret-market-value" not in " ".join(command)
        if command[0] == "scp":
            with tarfile.open(command[-2]) as archive:
                expected = {"source.tar.gz", "invest.env"}
                if with_account:
                    expected.add("account.tar.gz")
                if with_migration:
                    expected.add("migration.toml")
                assert set(archive.getnames()) == expected
                runtime = archive.extractfile("invest.env")
                assert runtime is not None and b"secret-market-value" in runtime.read()
        if label == "Apply deployment":
            assert kwargs["data"].startswith(b"#!/usr/bin/env bash")
            assert command[-1] == "bash -s -- /opt/invest/incoming/123-1 " + "c" * 40 + " 123-1"
            raise RuntimeError("simulated deployment failure")

    monkeypatch.setattr(runner, "run_quiet", fake_run)
    with pytest.raises(RuntimeError, match="simulated"):
        runner.execute(
            "migrate" if with_migration else "deploy",
            artifact,
            tmp_path / "existing-account" if with_account else None,
        )
    assert calls[-1] == "Clean private staging"
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


def test_runtime_inspection_needs_no_certificate_or_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name, value in {
        "INVEST_SSH_HOST": "host.example",
        "INVEST_SSH_PRIVATE_KEY": "private-ssh-key",
    }.items():
        monkeypatch.setenv(name, value)

    def fake_run(command: list[str], label: str, **kwargs: Any) -> bytes:
        assert "private-ssh-key" not in " ".join(command)
        assert b"private-ssh-key" not in kwargs["data"]
        if label == "Inspect deployed runtime":
            assert kwargs["data"] == (ROOT / "deploy/inspect.sh").read_bytes()
            return b"Account: active; sessions=1; missing_sessions=0\n"
        return b""

    monkeypatch.setattr(runner, "run_quiet", fake_run)
    runner.execute("inspect", None)
    assert list(tmp_path.iterdir()) == []
    output = capsys.readouterr()
    assert "private-ssh-key" not in output.out + output.err
    assert "Account: active; sessions=1; missing_sessions=0" in output.out


def test_inspection_summarizes_actual_receipt_schemas_without_exporting_account_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.forward_service import ALERT_SCHEMA, SERVICE_SCHEMA

    account = tmp_path / "account"
    operations = tmp_path / "operations"
    for name in ("runs", "alerts", "health", "deployments"):
        (operations / name).mkdir(parents=True)
    stamp = datetime.now(UTC)
    backup = tmp_path / "backups/current"
    backup.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([{"head": "private-head"}]), backup / "backup.parquet")
    run = {
        "finished_at": stamp,
        "outcome": "ok",
        "sessions": 1,
        "missing_sessions": 0,
        "account_id": "private-account",
        "head": "private-head",
        "error": "private-log",
        "backup": str(backup),
        "updated": True,
    }
    pq.write_table(
        pa.Table.from_pylist([run], schema=SERVICE_SCHEMA), operations / "runs/1.parquet"
    )
    old = {**run, "finished_at": stamp - timedelta(hours=25), "outcome": "error"}
    pq.write_table(
        pa.Table.from_pylist([old], schema=SERVICE_SCHEMA), operations / "runs/0.parquet"
    )
    alert = {
        "recorded_at": stamp,
        "kind": "systemd",
        "delivery": "sent",
        "detail": "private-message",
    }
    pq.write_table(
        pa.Table.from_pylist([alert], schema=ALERT_SCHEMA), operations / "alerts/0.parquet"
    )
    pq.write_table(
        pa.Table.from_pylist([{"recorded_at": stamp, "healthy": True}]),
        operations / "health/0.parquet",
    )
    status = {
        "mode": "cash_observation",
        "operations": "active",
        "risk_status": "active",
        "engine_matches": True,
        "sessions": 1,
        "missing_sessions": 0,
        "last_session": "2026-10-20",
        "account_id": "private-account",
        "cash": "5000",
        "head": "private-head",
    }
    monkeypatch.setattr("invest.forward.forward_status", lambda path: status)
    monkeypatch.setattr("invest.forward.verify_forward", lambda path: {"head": "private-head"})

    def fake_systemctl(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[0] == "systemctl" and command[1] in {"is-active", "is-enabled"}
        return subprocess.CompletedProcess(command, 0)

    # 系统服务由测试夹具模拟，不依赖开发机器是否安装 systemd。
    monkeypatch.setattr(subprocess, "run", fake_systemctl)
    script = (ROOT / "deploy/inspect.sh").read_text().split("<<'PY'\n", 1)[1].removesuffix("PY\n")
    script = script.replace("/var/lib/invest/account", str(account))
    exec(compile(script, "inspect.sh", "exec"), {})
    output = capsys.readouterr().out
    assert '"accounting_verified": true' in output
    assert '"outcome": "ok"' in output
    assert '"delivery": "sent"' in output
    assert '"healthy": true' in output
    assert '"matches_current": true' in output
    assert '"systemd_failures": 1' in output
    assert '"failed_runs": 0' in output
    assert '"runs": 1' in output
    assert "deployments: no records" in output
    assert "private-" not in output and "5000" not in output


def test_transport_errors_and_timeouts_do_not_disclose_command_or_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 255, b"private account data", b"secret-value")

    monkeypatch.setattr(runner.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="remote command failed") as failure:
        runner.run_quiet(["ssh", "secret-host"], "Deploy")
    assert "secret" not in str(failure.value)

    def timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(["ssh", "secret-host"], 1, b"private account data")

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out") as failure:
        runner.run_quiet(["ssh", "secret-host"], "Deploy")
    assert "secret" not in str(failure.value)


def test_environment_file_cannot_inject_more_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in runner.RUNTIME_KEYS:
        monkeypatch.delenv(key, raising=False)
    assert runner.runtime_environment() is None
    monkeypatch.setenv("APCA_API_KEY_ID", "key\nOTHER=unsafe")
    with pytest.raises(ValueError, match="unsafe runtime secret"):
        runner.runtime_environment()


@pytest.mark.parametrize(
    "failure",
    ["verify", "handover", "changed", "activate", "none", "fresh", "migrate", "migrate_failed"],
)
def test_host_deployment_preserves_account_and_controls_timers_on_failure(
    tmp_path: Path,
    failure: str,
) -> None:
    """Exercise the real shell coordinator against a stateful systemd/privilege sandbox."""
    host = tmp_path / "host"
    prefix = host / "opt/invest"
    incoming = prefix / "incoming/123-1"
    release_dir = prefix / ("releases/" + "c" * 40)
    account = host / "var/lib/invest/account"
    (account / "journal").mkdir(parents=True)
    original = account / "journal/history"
    original.write_bytes(b"immutable capital history")
    etc = host / "etc/invest"
    etc.mkdir(parents=True)
    (etc / "invest.env").write_text("server-existing-secret")
    incoming.mkdir(parents=True)
    (release_dir / ".venv/bin").mkdir(parents=True)
    (release_dir / "deploy").mkdir()
    (release_dir / "deploy").chmod(0o755)
    (release_dir / "deploy/release.py").write_text("public deployment code")
    (release_dir / "deploy/release.py").chmod(0o644)
    managed_python = prefix / "python/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("not executed; privilege boundary is mocked")
    (release_dir / ".venv/bin/python").symlink_to(managed_python)
    (release_dir / "deploy/install-systemd.sh").write_text(
        'echo activate >> "$HOST_EVENTS"\n[[ $HOST_FAILURE != activate ]]\n'
    )
    source = incoming / "source.tar.gz"
    source.write_bytes(b"tested source already installed in immutable release cache")
    if failure == "fresh":
        # Hatch sdists omit directory entries. Extraction must give the service access
        # to directories created implicitly, despite the surrounding private umask.
        with tarfile.open(source, "w:gz") as archive:
            for name, content in {
                "deploy/release.py": b"public deployment code",
                "src/invest/__init__.py": b"public engine code",
                "deploy/install-systemd.sh": (
                    release_dir / "deploy/install-systemd.sh"
                ).read_bytes(),
            }.items():
                entry = tarfile.TarInfo("project/" + name)
                entry.mode, entry.size = 0o644, len(content)
                archive.addfile(entry, io.BytesIO(content))
    # Existing releases are trusted, without comparing the incoming archive digest.
    (release_dir / ".source-sha256").write_text("previously recorded provenance")
    if failure == "fresh":
        shutil.rmtree(release_dir)
    payload = incoming / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        archive.add(source, arcname="source.tar.gz")
        if failure.startswith("migrate"):
            content = b'actor="owner"\nreason="CLI output fix"\n'
            entry = tarfile.TarInfo("migration.toml")
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    source.unlink()
    tools = tmp_path / "tools"
    tools.mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"active": True, "verifies": 0, "head": "b" * 64}))
    events = tmp_path / "events"
    mock = tools / "mock.py"
    mock.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import subprocess
import sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_path = Path(os.environ["HOST_STATE"])
state = json.loads(state_path.read_text())
def log(value):
    with Path(os.environ["HOST_EVENTS"]).open("a") as stream:
        stream.write(value + "\n")
if name == "id":
    if args == ["-u"]:
        print("0")
elif name == "install":
    filtered = []
    i = 0
    while i < len(args):
        if args[i] in {"-o", "-g"}:
            i += 2
        else:
            filtered.append(args[i])
            i += 1
    sys.exit(subprocess.call(["/usr/bin/install", *filtered]))
elif name == "runuser":
    command = args[args.index("--") + 1:]
    if command[:2] == ["test", "-r"]:
        path = Path(command[-1])
        assert path.stat().st_mode & 0o004, "Service must be able to read public code"
        assert path.parent.stat().st_mode & 0o001, "Implicit source directories must be traversable"
    elif "identity" in command or "migration-identity" in command:
        assert not state["active"], "Metadata must be discovered after quiescence"
        log("migration-identity" if "migration-identity" in command else "identity")
        if os.environ["HOST_FAILURE"] == "verify":
            sys.exit(1)
        print("a" * 32, state["head"])
    elif "verify" in command:
        state["verifies"] += 1
        state_path.write_text(json.dumps(state))
        log("verify")
        if command[-1] != state["head"] or (
            os.environ["HOST_FAILURE"] == "handover" and state["verifies"] == 1
        ):
            sys.exit(1)
    elif "forward-backup" in command:
        log("backup")
        if os.environ["HOST_FAILURE"] == "changed":
            state["head"] = "e" * 64
            state_path.write_text(json.dumps(state))
    elif "receipt" in command:
        assert command[command.index("receipt") + 3] == "d" * 64, "Keep the original handover head"
        log("receipt")
    elif "migrate" in command:
        assert command[-2] == "-" and "actor" in sys.stdin.read()
        log("migrate")
        state["head"] = "e" * 64
        state_path.write_text(json.dumps(state))
        if os.environ["HOST_FAILURE"] == "migrate_failed":
            sys.exit(1)
elif name == "uv":
    Path(".venv/bin").mkdir(parents=True)
    Path(".venv/bin/python").symlink_to(os.environ["HOST_MANAGED_PYTHON"])
elif name == "chown":
    pass
elif name == "flock":
    import fcntl
    assert args == ["-n", "9"]
    try:
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
elif name == "systemctl":
    log("systemctl " + " ".join(args))
    if args[0] == "is-active":
        sys.exit(0 if state["active"] else 3)
    if args[0] == "show":
        print("inactive")
    if args[0] in {"stop", "disable"}:
        state["active"] = False
        if args[0] == "stop":
            state["head"] = "d" * 64  # The previous daily task finishes during handover.
    if args[0] in {"enable", "start"} and any(arg.endswith(".timer") for arg in args):
        state["active"] = True
    state_path.write_text(json.dumps(state))
else:
    sys.exit(99)
"""
    )
    mock.chmod(0o755)
    for name in ("id", "install", "runuser", "systemctl", "uv", "chown", "flock"):
        (tools / name).symlink_to(mock)
    script = (ROOT / "deploy/apply.sh").read_text()
    for directory in ("/opt/invest", "/var/lib/invest", "/etc/invest"):
        script = script.replace(directory, str(host) + directory)
    script_path = tmp_path / "apply.sh"
    script_path.write_text(script)
    environment = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "HOST_FAILURE": failure,
        "HOST_STATE": str(state),
        "HOST_EVENTS": str(events),
        "HOST_MANAGED_PYTHON": str(managed_python),
    }
    result = subprocess.run(
        [
            "bash",
            str(script_path),
            str(incoming),
            "c" * 40,
            "123-1",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    success = failure in {"none", "fresh", "migrate"}
    assert (result.returncode == 0) == success, result.stderr
    assert original.read_bytes() == b"immutable capital history"
    final = json.loads(state.read_text())
    assert final["active"] == (failure not in {"activate", "migrate_failed"})
    sequence = events.read_text().splitlines()
    if failure == "migrate":
        assert (
            sequence.index("migration-identity")
            < sequence.index("migrate")
            < sequence.index("identity")
            < sequence.index("verify")
            < sequence.index("activate")
            < sequence.index("receipt")
        )
    elif success:
        enable = next(i for i, event in enumerate(sequence) if "systemctl enable --now" in event)
        assert (
            sequence.index("identity")
            < sequence.index("verify")
            < sequence.index("backup")
            < sequence.index("activate")
            < sequence.index("receipt")
            < enable
        )
    else:
        assert "receipt" not in sequence
        assert not any("systemctl enable --now" in event for event in sequence)
    if failure == "fresh":
        assert (release_dir / "src/invest/__init__.py").stat().st_mode & 0o004
        assert (release_dir / "src/invest").stat().st_mode & 0o001


def test_account_export_discovers_metadata_and_omits_local_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import invest.forward as forward

    account = tmp_path / "account"
    run = account / "journal/00000000"
    run.mkdir(parents=True)
    (run / "files.parquet").write_bytes(b"verified inventory")
    (run / "journal.parquet").write_bytes(b"verified journal")
    (account / ".env").write_text("private-secret")
    monkeypatch.setattr(
        release, "verify_account", lambda account: {"head": release.digest(run / "files.parquet")}
    )
    monkeypatch.setattr(forward, "_runs", lambda account: [run])
    output = tmp_path / "handover/account.tar.gz"
    release.pack_account(account, output)
    assert output.stat().st_mode & 0o777 == 0o600
    extracted = release.extract_account(output, tmp_path / "copy")
    assert (extracted / "journal/00000000/journal.parquet").read_bytes() == b"verified journal"
    assert not (extracted / ".env").exists() and not (extracted / ".lock").exists()
    with pytest.raises(FileExistsError):
        release.pack_account(account, output)
    monkeypatch.setattr(release, "verify_account", lambda account: {"head": "f" * 64})
    with pytest.raises(ValueError, match="Account changed"):
        release.pack_account(account, tmp_path / "stale.tar.gz")
    assert not (tmp_path / "stale.tar.gz").exists()
