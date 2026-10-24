"""The authorized fresh observation archives legacy evidence and resumes one restart on retries."""

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.test_deployment import ROOT, load_tool


@pytest.fixture
def restart(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = load_tool("restart")

    def status(account: Path) -> dict[str, Any]:
        identity = pq.read_table(account / "registration.parquet")["account_id"][0].as_py()
        return {
            "account_id": identity,
            "observation_start_session": "2030-10-23",
            "head": "head-new",
            "sessions": 0,
        }

    monkeypatch.setattr(module.ibkr_observation, "status", status)
    monkeypatch.setattr(module.ibkr_observation, "verify", status)
    return module


def legacy(root: Path) -> Path:
    genesis = root / "account/journal/00000000"
    genesis.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "account_id": "old-account",
                    "observation_body": b'mode="cash_observation"\ncandidate="cash"\n',
                }
            ]
        ),
        genesis / "registration.parquet",
    )
    (genesis / "history.parquet").write_bytes(b"unchanged historical decisions")
    (root / "operations").mkdir()
    (root / "operations/old.parquet").write_bytes(b"old failed run evidence")
    (root / "backups").mkdir()
    (root / "backups/old.parquet").write_bytes(b"old backup")
    operations = root / "old-operations.toml"
    operations.write_text('backend = "legacy_forward"\n')
    return operations


def provision(module: ModuleType, root: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def initialize(account: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(account)
        account.mkdir()
        pq.write_table(
            pa.Table.from_pylist([{"account_id": "new-account"}]), account / "registration.parquet"
        )
        return {}

    monkeypatch.setattr(module.ibkr_observation, "initialize", initialize)
    request = root / "request.toml"
    request.write_text('actor = "github:owner"\nreason = "user requested a new observation"\n')
    module.prepare(root, root / "release", request, root / "old-release")
    return calls


def test_restart_archives_every_old_record_and_retry_keeps_new_account(
    tmp_path: Path, restart: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = legacy(tmp_path)
    calls = provision(restart, tmp_path, monkeypatch)
    assert (tmp_path / "account/journal/00000000/history.parquet").is_file()
    restart.activate(tmp_path, operations)
    archive = tmp_path / "archives" / restart.NAME
    assert (
        archive / "account/journal/00000000/history.parquet"
    ).read_bytes() == b"unchanged historical decisions"
    assert (archive / "operations/old.parquet").read_bytes() == b"old failed run evidence"
    assert (archive / "operations.toml").read_text() == operations.read_text()
    assert (tmp_path / "backups/old.parquet").read_bytes() == b"old backup"
    (tmp_path / "operations/new.parquet").write_bytes(b"new observation evidence")
    restart.prepare(
        tmp_path, tmp_path / "release", tmp_path / "request.toml", tmp_path / "old-release"
    )
    restart.activate(tmp_path, operations)
    restart.receipt(tmp_path, tmp_path / "release", "123-1")
    restart.receipt(tmp_path, tmp_path / "release", "123-1")
    assert len(calls) == 1
    assert (tmp_path / "operations/new.parquet").read_bytes() == b"new observation evidence"
    assert not (archive / "operations/new.parquet").exists()
    assert restart.request_at(tmp_path)["old_account_id"] == "old-account"
    assert restart.request_at(tmp_path)["new_account_id"] == "new-account"


@pytest.mark.parametrize("failed_move", ["legacy", "new"])
def test_restart_recovers_interrupted_directory_handover_without_another_initialization(
    tmp_path: Path, restart: ModuleType, monkeypatch: pytest.MonkeyPatch, failed_move: str
) -> None:
    operations = legacy(tmp_path)
    calls = provision(restart, tmp_path, monkeypatch)
    original = Path.rename
    target = (
        tmp_path / "account"
        if failed_move == "legacy"
        else tmp_path / "restarts" / restart.NAME / "account"
    )

    def interrupted(path: Path, destination: Path) -> Path:
        if path == target:
            raise OSError("simulated interruption")
        return original(path, destination)

    with monkeypatch.context() as local:
        local.setattr(Path, "rename", interrupted)
        with pytest.raises(OSError, match="interruption"):
            restart.activate(tmp_path, operations)
    restart.prepare(
        tmp_path, tmp_path / "release", tmp_path / "request.toml", tmp_path / "old-release"
    )
    restart.activate(tmp_path, operations)
    assert len(calls) == 1
    assert restart.ibkr_observation.status(tmp_path / "account")["account_id"] == "new-account"
    assert (
        tmp_path / "archives" / restart.NAME / "account/journal/00000000/history.parquet"
    ).is_file()


def test_first_open_missed_before_handover_leaves_legacy_account_untouched(
    tmp_path: Path, restart: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = legacy(tmp_path)
    provision(restart, tmp_path, monkeypatch)

    def missed(status: dict[str, Any]) -> None:
        raise ValueError("missed activation before its first open")

    monkeypatch.setattr(restart, "before_open", missed)
    with pytest.raises(ValueError, match="first open"):
        restart.activate(tmp_path, operations)
    assert (tmp_path / "account/journal/00000000/history.parquet").is_file()
    assert (tmp_path / "operations/old.parquet").is_file()
    assert not (tmp_path / "archives").exists()


def test_restart_cannot_repurpose_authorization_for_another_account_mode(
    tmp_path: Path, restart: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy(tmp_path)
    genesis = tmp_path / "account/journal/00000000/registration.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "account_id": "old-account",
                    "observation_body": b'mode="qualified_strategy"\ncandidate="trend-20"\n',
                }
            ]
        ),
        genesis,
    )
    with pytest.raises(ValueError, match="only to the legacy cash observation"):
        provision(restart, tmp_path, monkeypatch)
    assert (tmp_path / "account/journal/00000000/history.parquet").is_file()
    assert not (tmp_path / "archives").exists()


def test_restart_preflight_failure_does_not_touch_old_records(
    tmp_path: Path, restart: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy(tmp_path)
    request = tmp_path / "request.toml"
    request.write_text('actor="owner"\nreason="authorized restart"\n')

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise ValueError("IBKR unavailable")

    monkeypatch.setattr(restart.ibkr_observation, "initialize", unavailable)
    with pytest.raises(ValueError, match="IBKR unavailable"):
        restart.prepare(tmp_path, tmp_path / "release", request, tmp_path / "old-release")
    assert (tmp_path / "account/journal/00000000/history.parquet").is_file()
    assert (tmp_path / "operations/old.parquet").is_file()
    assert not (tmp_path / "restarts" / restart.NAME / "request.parquet").exists()


def test_restart_transport_needs_only_telegram_and_keeps_request_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_tool("github_actions")
    for name in runner.RUNTIME_KEYS:
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "INVEST_SSH_HOST": "host.example",
        "INVEST_SSH_PRIVATE_KEY": "private-key",
        "INVEST_DEPLOY_COMMIT": "c" * 40,
        "INVEST_DEPLOY_RUN": "123-1",
        "INVEST_TELEGRAM_BOT_TOKEN": "123:private-token",
        "INVEST_TELEGRAM_ALLOWED_UID": "1234",
        "GITHUB_ACTOR": "owner",
    }.items():
        monkeypatch.setenv(name, value)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "source.tar.gz").write_bytes(b"tested-source")
    applied = []

    def run(command: list[str], label: str, **kwargs: Any) -> bytes:
        assert "private-key" not in " ".join(command)
        if command[0] == "scp":
            with tarfile.open(command[-2]) as archive:
                assert set(archive.getnames()) == {"source.tar.gz", "restart.toml", "invest.env"}
                data = archive.extractfile("invest.env")
                assert data is not None
                body = data.read()
                assert b"APCA" not in body and b"private-token" in body
        if label == "Apply deployment":
            applied.append(label)
            assert kwargs["data"] == (ROOT / "deploy/restart.sh").read_bytes()
        return b""

    monkeypatch.setattr(runner, "run_quiet", run)
    runner.execute("restart", artifact)
    assert applied == ["Apply deployment"]
    assert "private" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["install", "initialize", "activate", "validate", "none"])
def test_restart_shell_failure_recovery_and_successful_activation_order(
    tmp_path: Path, failure: str
) -> None:
    host = tmp_path / "host"
    prefix = host / "opt/invest"
    incoming = prefix / "incoming/123-1"
    release = prefix / ("releases/" + "c" * 40)
    incoming.mkdir(parents=True)
    (release / ".venv/bin").mkdir(parents=True)
    (release / ".source-ready").touch()
    managed = prefix / "python/bin/python"
    managed.parent.mkdir(parents=True)
    managed.touch()
    (release / ".venv/bin/python").symlink_to(managed)
    (release / "deploy/systemd").mkdir(parents=True)
    (release / "deploy/systemd/invest-forward.service").write_text("unit")
    (release / "deploy/operations-ibkr.toml").write_text('backend="ibkr_cash"')
    (host / "etc/invest").mkdir(parents=True)
    (host / "etc/invest/invest.env").write_text("host-secret")
    (host / "etc/systemd/system").mkdir(parents=True)
    (host / "var/lib/invest").mkdir(parents=True)
    with tarfile.open(incoming / "payload.tar.gz", "w:gz") as archive:
        entry = tarfile.TarInfo("restart.toml")
        body = b'actor="owner"\nreason="authorized restart"\n'
        entry.size = len(body)
        archive.addfile(entry, io.BytesIO(body))
    tools = tmp_path / "tools"
    tools.mkdir()
    events = tmp_path / "events"
    mock = tools / "mock.py"
    mock.write_text(
        f"#!{sys.executable}\n"
        + r"""
import os, subprocess, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
def log(message):
    with Path(os.environ["HOST_EVENTS"]).open("a") as stream:
        stream.write(message + "\n")
if name == "id":
    if args == ["-u"]: print("0")
elif name == "install":
    filtered, index = [], 0
    while index < len(args):
        if args[index] in {"-o", "-g"}: index += 2
        else: filtered.append(args[index]); index += 1
    sys.exit(subprocess.call(["/usr/bin/install", *filtered]))
elif name == "runuser":
    action = next(word for word in args if word in {"prepare", "activate", "receipt"})
    log(action)
    if os.environ["HOST_FAILURE"] == {"prepare":"initialize", "activate":"activate"}.get(action):
        sys.exit(1)
elif name == "systemctl":
    log("systemctl " + " ".join(args))
    if args[0] == "show": print("inactive")
    if args[:2] == ["start", "invest-forward.service"] and os.environ["HOST_FAILURE"] == "validate":
        sys.exit(1)
elif name == "flock":
    import fcntl
    assert args == ["-n", "9"]
    try:
        fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
elif name == "uv":
    kind = "sdk" if "--project" in args else "core"
    log("uv " + kind)
    if kind == "core" and os.environ["HOST_FAILURE"] == "install": sys.exit(1)
else: sys.exit(99)
"""
    )
    mock.chmod(0o755)
    for name in ("id", "install", "runuser", "systemctl", "uv", "flock"):
        (tools / name).symlink_to(mock)
    script = (ROOT / "deploy/restart.sh").read_text()
    for directory in ("/opt/invest", "/var/lib/invest", "/etc/invest", "/etc/systemd"):
        script = script.replace(directory, str(host) + directory)
    path = tmp_path / "restart.sh"
    path.write_text(script)
    result = subprocess.run(
        ["bash", str(path), str(incoming), "c" * 40, "123-1"],
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "HOST_EVENTS": str(events),
            "HOST_FAILURE": failure,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert (result.returncode == 0) == (failure == "none"), result.stderr
    sequence = events.read_text().splitlines()
    if failure == "install":
        assert sequence == ["uv core"]
        # A partial .venv survives the first failure; retry must sync it again.
        retried = subprocess.run(
            ["bash", str(path), str(incoming), "c" * 40, "123-1"],
            env={
                **os.environ,
                "PATH": f"{tools}:{os.environ['PATH']}",
                "HOST_EVENTS": str(events),
                "HOST_FAILURE": "none",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert retried.returncode == 0, retried.stderr
        assert events.read_text().splitlines().count("uv core") == 2
        return
    assert sequence.index("uv core") < sequence.index("prepare")
    assert sequence.index("prepare") < (
        sequence.index("activate") if "activate" in sequence else len(sequence)
    )
    if failure == "none":
        assert (
            sequence.index("activate")
            < sequence.index("systemctl start invest-forward.service")
            < sequence.index("receipt")
        )
        assert (
            sequence[-1]
            == "systemctl enable --now invest-forward.timer invest-forward-health.timer"
        )
    elif failure == "initialize":
        assert not any(line.startswith("systemctl stop") for line in sequence)
    else:
        assert (
            sequence[-1]
            == "systemctl disable --now invest-forward.timer invest-forward-health.timer"
        )
        assert "receipt" not in sequence
