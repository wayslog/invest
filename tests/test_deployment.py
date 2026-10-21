"""Offline deployment gates: identity, unsafe archives, private transport and redaction."""

import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
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
handover = load_tool("handoff")


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
    ("name", "kind"),
    [
        ("/account/journal/00000000/x", tarfile.REGTYPE),
        ("account/journal/../../escape", tarfile.REGTYPE),
        ("account/invest.env", tarfile.REGTYPE),
        ("account/journal/00000000/link", tarfile.SYMTYPE),
        ("account/journal/00000000/link", tarfile.LNKTYPE),
        ("account/journal/00000000/pipe", tarfile.FIFOTYPE),
    ],
)
def test_unsafe_account_archive_is_rejected_before_extraction(
    tmp_path: Path, name: str, kind: bytes
) -> None:
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.linkname = "../../outside"
    archive = bundle(tmp_path, [entry])
    destination = tmp_path / "new"
    with pytest.raises(ValueError, match="Unsafe"):
        release.extract_account(archive, destination)
    assert not destination.exists()


def test_duplicate_archive_paths_are_rejected(tmp_path: Path) -> None:
    entry = tarfile.TarInfo("account/journal/00000000/x")
    archive = bundle(tmp_path, [entry, entry])
    with pytest.raises(ValueError, match="Unsafe"):
        release.extract_account(archive, tmp_path / "new")
    assert not (tmp_path / "new").exists()


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
    ("with_account", "with_handoff"), [(False, False), (True, False), (False, True)]
)
def test_ssh_transport_records_first_host_key_and_keeps_secrets_in_private_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    with_account: bool,
    with_handoff: bool,
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
        "INVEST_RELEASE_SHA256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "APCA_API_KEY_ID": "secret-market-key",
        "APCA_API_SECRET_KEY": "secret-market-value",
        "INVEST_TELEGRAM_BOT_TOKEN": "123:secret-bot-token",
        "INVEST_TELEGRAM_ALLOWED_UID": "12345",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    calls: list[str] = []
    envelope = json.dumps(
        {
            "cms": base64.b64encode(b"signed and encrypted account").decode(),
            "signer_certificate": "-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n",
        }
    ).encode()
    monkeypatch.setattr(runner, "download_handoff", lambda blob: envelope)

    def fake_run(command: list[str], label: str, **kwargs: Any) -> None:
        calls.append(label)
        if label == "Prepare existing local account":
            assert command[2] == "pack-account"
            Path(command[-1]).write_bytes(b"private account bytes")
            return
        assert "StrictHostKeyChecking=accept-new" in command
        assert "GlobalKnownHostsFile=/dev/null" in command
        assert "ForwardAgent=no" in command and "BatchMode=yes" in command
        hosts = Path(
            next(
                value.split("=", 1)[1]
                for value in command
                if value.startswith("UserKnownHostsFile=")
            )
        )
        assert hosts.stat().st_mode & 0o777 == 0o600
        if label == "Host preflight":
            assert hosts.read_text() == ""
            hosts.write_text("automatically recorded host key")
        else:
            assert hosts.read_text() == "automatically recorded host key"
        key = Path(command[command.index("-i") + 1])
        assert key.stat().st_mode & 0o777 == 0o600
        assert key.read_text().strip() == "private-key-material"
        assert "secret-market-value" not in " ".join(command)
        if command[0] == "scp":
            with tarfile.open(command[-2]) as archive:
                expected = {"source.tar.gz", "invest.env"}
                if with_account:
                    expected.add("account.tar.gz")
                if with_handoff:
                    expected.update({"account.cms", "account-signer.pem"})
                assert set(archive.getnames()) == expected
                runtime = archive.extractfile("invest.env")
                assert runtime is not None and b"secret-market-value" in runtime.read()
        if label == "Apply deployment":
            assert kwargs["data"].startswith(b"#!/usr/bin/env bash")
            raise RuntimeError("simulated deployment failure")

    monkeypatch.setattr(runner, "run_quiet", fake_run)
    with pytest.raises(RuntimeError, match="simulated"):
        runner.execute(
            "deploy",
            artifact,
            tmp_path / "existing-account" if with_account else None,
            "d" * 40 if with_handoff else "",
        )
    assert calls[-1] == "Clean private staging"
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err


def test_handoff_download_checks_object_identity_without_leaking_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"encrypted private account"
    blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    record = {"encoding": "base64", "content": base64.b64encode(data).decode()}
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/invest")
    monkeypatch.setenv("GITHUB_TOKEN", "private-api-token")

    class Opener:
        def open(self, request: Any, timeout: int) -> io.BytesIO:
            assert request.full_url == f"https://api.github.com/repos/owner/invest/git/blobs/{blob}"
            assert request.headers["Authorization"] == "Bearer private-api-token"
            assert timeout == 30
            return io.BytesIO(json.dumps(record).encode())

    monkeypatch.setattr(runner, "build_opener", lambda *args: Opener())
    assert runner.download_handoff(blob) == data
    record["content"] = base64.b64encode(b"changed ciphertext").decode()
    with pytest.raises(ValueError, match="object changed"):
        runner.download_handoff(blob)
    with pytest.raises(ValueError, match="Invalid encrypted"):
        runner.download_handoff("../other")
    assert runner.NoRedirect().redirect_request(None) is None


def test_handoff_certificate_keeps_private_key_on_host_and_authenticates_ciphertext(
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "host"
    prefix.mkdir()
    script = (ROOT / "deploy/prepare-handoff.sh").read_text()
    script = script.replace("$(id -u)", "0").replace("/opt/invest", str(prefix))
    script = script.replace("/var/lib/invest/account", str(prefix / "account"))

    def prepare() -> bytes:
        return subprocess.run(
            ["bash"], input=script.encode(), capture_output=True, check=True
        ).stdout

    certificate = prepare()
    key = prefix / "bootstrap/handoff.key"
    assert key.stat().st_mode & 0o777 == 0o600
    assert certificate.startswith(b"-----BEGIN CERTIFICATE-----")
    assert b"PRIVATE KEY" not in certificate
    assert prepare() == certificate  # A retry cannot rotate the recipient behind the sender.
    source = tmp_path / "account.tar.gz"
    source.write_bytes(b"private immutable account journal")
    envelope = json.loads(
        handover.encrypt_archive(source, prefix / "bootstrap/handoff.pem", tmp_path)
    )
    cipher = tmp_path / "account.cms"
    assert cipher.read_bytes() == base64.b64decode(envelope["cms"])
    signer = tmp_path / "signer.pem"
    assert signer.read_text() == envelope["signer_certificate"]
    decrypt = [
        "openssl",
        "cms",
        "-decrypt",
        "-binary",
        "-inform",
        "DER",
        "-in",
        str(cipher),
        "-recip",
        str(prefix / "bootstrap/handoff.pem"),
        "-inkey",
        str(key),
    ]
    signed = subprocess.run(decrypt, capture_output=True, check=True).stdout
    verify = [
        "openssl",
        "cms",
        "-verify",
        "-binary",
        "-inform",
        "DER",
        "-nointern",
        "-certfile",
        str(signer),
        "-noverify",
    ]
    plain = subprocess.run(verify, input=signed, capture_output=True, check=True).stdout
    assert plain == source.read_bytes()
    wrong_signer = verify.copy()
    wrong_signer[wrong_signer.index("-certfile") + 1] = str(prefix / "bootstrap/handoff.pem")
    assert subprocess.run(wrong_signer, input=signed, capture_output=True).returncode != 0
    content = bytearray(cipher.read_bytes())
    # Tamper with a CBC block while leaving padding intact: signature verification must fail.
    content[-64] ^= 1
    cipher.write_bytes(content)
    changed = subprocess.run(decrypt, capture_output=True, check=True).stdout
    assert subprocess.run(verify, input=changed, capture_output=True).returncode != 0
    (prefix / "account").mkdir()
    refused = subprocess.run(["bash"], input=script.encode(), capture_output=True, check=False)
    assert refused.returncode != 0 and b"already has an account" in refused.stderr


def test_handoff_uploader_sends_only_ciphertext_and_automates_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    private_files: list[Path] = []
    encrypted = b"authenticated ciphertext"
    blob = hashlib.sha1(f"blob {len(encrypted)}\0".encode() + encrypted).hexdigest()

    def fake_quiet(command: list[str], data: bytes | None = None) -> bytes:
        commands.append(command)
        if "pack-account" in command:
            path = Path(command[-1])
            path.write_bytes(b"private-account-journal")
            private_files.append(path)
        elif command[:2] == ["gh", "api"]:
            assert data is not None and b"private-account-journal" not in data
            request = json.loads(data)
            assert base64.b64decode(request["content"]) == encrypted
            return json.dumps({"sha": blob}).encode()
        return b""

    monkeypatch.setattr(handover, "quiet", fake_quiet)
    monkeypatch.setattr(handover, "encrypt_archive", lambda *args: encrypted)
    assert handover.handoff(tmp_path / "account", tmp_path / "public.pem", "owner/invest") == blob
    assert commands[-1][-2:] == ["-f", f"handoff_blob={blob}"]
    assert "main" in commands[-1]
    assert private_files and all(not path.exists() for path in private_files)


def test_runtime_inspection_never_prints_or_exports_plain_private_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name, value in {
        "INVEST_SSH_HOST": "host.example",
        "INVEST_SSH_PRIVATE_KEY": "private-ssh-key",
        "INVEST_INSPECTION_RECIPIENT": (
            "-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----"
        ),
    }.items():
        monkeypatch.setenv(name, value)

    def fake_run(command: list[str], label: str, **kwargs: Any) -> bytes:
        assert "private-ssh-key" not in " ".join(command)
        assert b"private-ssh-key" not in kwargs["data"]
        if label == "Inspect deployed runtime":
            assert kwargs["data"].startswith(b"recipient_base64=")
            return b"encrypted runtime receipts"
        return b""

    monkeypatch.setattr(runner, "run_quiet", fake_run)
    runner.execute("inspect", None)
    artifact = tmp_path / "runtime-inspection.cms"
    assert artifact.read_bytes() == b"encrypted runtime receipts"
    assert artifact.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert "private-ssh-key" not in output.out + output.err
    assert "encrypted runtime receipts" not in output.out + output.err


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


@pytest.mark.parametrize("failure", ["verify", "handover", "changed", "activate", "none"])
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
    managed_python = prefix / "python/bin/python"
    managed_python.parent.mkdir(parents=True)
    managed_python.write_text("not executed; privilege boundary is mocked")
    (release_dir / ".venv/bin/python").symlink_to(managed_python)
    (release_dir / "deploy/install-systemd.sh").write_text(
        'echo activate >> "$HOST_EVENTS"\n[[ $HOST_FAILURE != activate ]]\n'
    )
    source = incoming / "source.tar.gz"
    source.write_bytes(b"tested source already installed in immutable release cache")
    source_sha = release.digest(source)
    (release_dir / ".source-sha256").write_text(source_sha)
    payload = incoming / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        archive.add(source, arcname="source.tar.gz")
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
    if "identity" in command:
        assert not state["active"], "Metadata must be discovered after quiescence"
        log("identity")
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
        log("receipt")
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
    for name in ("id", "install", "runuser", "systemctl"):
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
    }
    result = subprocess.run(
        [
            "bash",
            str(script_path),
            str(incoming),
            release.digest(payload),
            source_sha,
            "c" * 40,
            "123-1",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) == (failure == "none"), result.stderr
    assert original.read_bytes() == b"immutable capital history"
    final = json.loads(state.read_text())
    assert final["active"] == (failure != "activate")
    sequence = events.read_text().splitlines()
    if failure == "none":
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
