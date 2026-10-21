"""GitHub runner transport. Private payloads never become Actions artifacts or log output."""

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

RUNTIME_KEYS = (
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
    "INVEST_TELEGRAM_BOT_TOKEN",
    "INVEST_TELEGRAM_ALLOWED_UID",
)


def required(name: str, pattern: str | None = None) -> str:
    value = os.environ.get(name, "")
    if not value or (pattern and not re.fullmatch(pattern, value)):
        raise ValueError(f"Missing or invalid {name}")
    return value


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_environment() -> str | None:
    values = {key: os.environ.get(key, "") for key in RUNTIME_KEYS}
    if not any(values.values()):
        return None  # An existing protected server EnvironmentFile can be reused.
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_./:+-]+", value):
            raise ValueError(f"Missing or unsafe runtime secret {key}")
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", values["INVEST_TELEGRAM_BOT_TOKEN"]):
        raise ValueError("Invalid Telegram bot token format")
    if not re.fullmatch(r"[1-9][0-9]*", values["INVEST_TELEGRAM_ALLOWED_UID"]):
        raise ValueError("Telegram recipient must be a positive private user ID")
    return "".join(f"{key}={value}\n" for key, value in values.items())


def run_quiet(
    command: list[str], label: str, *, data: bytes | None = None, timeout: int = 120
) -> None:
    try:
        result = subprocess.run(
            command, input=data, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{label}: operation timed out; command and output withheld") from None
    if result.returncode:
        detail = "remote command failed; inspect the protected host logs"
        stderr = result.stderr.decode(errors="replace").lower()
        for needle, message in (
            ("connection refused", "SSH port refused the connection"),
            ("connection timed out", "SSH connection timed out"),
            ("no route to host", "SSH host is unreachable"),
            ("host key verification failed", "SSH host key verification failed"),
            ("remote host identification has changed", "SSH host key changed"),
            ("permission denied (publickey", "SSH key authentication failed"),
            ("could not resolve hostname", "SSH hostname could not be resolved"),
        ):
            if needle in stderr:
                detail = message
                break
        # Only our fixed, data-free diagnostic lines can enter public workflow logs.
        markers = re.findall(r"^deploy_error: ([a-z0-9 ,;._-]+)$", stderr, re.MULTILINE)
        if markers:
            detail = markers[-1]
        raise RuntimeError(f"{label}: {detail} (exit {result.returncode})")


def execute(operation: str, artifact: Path | None, account: Path | None = None) -> None:
    root = Path(__file__).resolve().parent
    host = required("INVEST_SSH_HOST", r"[A-Za-z0-9][A-Za-z0-9.-]*")
    user = os.environ.get("INVEST_SSH_USER", "root")
    port = os.environ.get("INVEST_SSH_PORT", "22")
    if (
        not re.fullmatch(r"[a-z_][a-z0-9_-]*", user)
        or not port.isdigit()
        or not 1 <= int(port) <= 65535
    ):
        raise ValueError("Invalid SSH user or port")
    key = required("INVEST_SSH_PRIVATE_KEY")
    with tempfile.TemporaryDirectory(prefix="invest-deploy-") as temporary:
        work = Path(temporary)
        identity, hosts = work / "identity", work / "known_hosts"
        identity.write_text(key.replace("\r\n", "\n").rstrip() + "\n")
        identity.chmod(0o600)
        hosts.touch(mode=0o600)
        options = [
            "-F",
            "/dev/null",
            "-i",
            str(identity),
            "-o",
            f"UserKnownHostsFile={hosts}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "VerifyHostKeyDNS=no",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ]
        target = f"{user}@{host}"
        ssh = ["ssh", "-T", *options, "-p", port, target]
        run_quiet([*ssh, "bash -s"], "Host preflight", data=(root / "preflight.sh").read_bytes())
        if operation == "preflight":
            print("SSH, systemd, clock and uv checks passed; host unchanged.")
            return
        commit = required("INVEST_DEPLOY_COMMIT", r"[0-9a-f]{40}")
        run = required("INVEST_DEPLOY_RUN", r"[0-9]+-[0-9]+")
        source_sha = required("INVEST_RELEASE_SHA256", r"[0-9a-f]{64}")
        archives = list(artifact.glob("*.tar.gz")) if artifact else []
        if len(archives) != 1 or digest(archives[0]) != source_sha:
            raise ValueError("Tested source artifact is missing or its checksum changed")
        payload = work / "payload"
        payload.mkdir(mode=0o700)
        shutil.copyfile(archives[0], payload / "source.tar.gz")
        environment = runtime_environment()
        if environment is not None:
            (payload / "invest.env").write_text(environment)
            (payload / "invest.env").chmod(0o600)
        if account is not None:
            run_quiet(
                [
                    sys.executable,
                    str(root / "release.py"),
                    "pack-account",
                    str(account),
                    str(payload / "account.tar.gz"),
                ],
                "Prepare existing local account",
                timeout=300,
            )
        bundle = work / "payload.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            for path in sorted(payload.iterdir()):
                archive.add(path, arcname=path.name, recursive=False)
        incoming = f"/opt/invest/incoming/{run}"
        run_quiet(
            [
                *ssh,
                f"umask 077; install -d -m 755 /opt/invest; "
                f"install -d -m 700 /opt/invest/incoming; mkdir {incoming}",
            ],
            "Prepare private staging",
        )
        try:
            run_quiet(
                [
                    "scp",
                    "-q",
                    *options,
                    "-P",
                    port,
                    str(bundle),
                    f"{target}:{incoming}/payload.tar.gz",
                ],
                "Transfer private deployment payload",
            )
            arguments = [
                incoming,
                digest(bundle),
                source_sha,
                commit,
                run,
            ]
            command = "bash -s -- " + " ".join(shlex.quote(value) for value in arguments)
            run_quiet(
                [*ssh, command],
                "Apply deployment",
                data=(root / "apply.sh").read_bytes(),
                timeout=1500,
            )
        finally:
            # Failure of cleanup must not hide the deployment result. Staging is root-only.
            try:
                run_quiet([*ssh, f"rm -rf -- {incoming}"], "Clean private staging", timeout=45)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                print("Private host staging cleanup needs checking.", file=sys.stderr)
        print("Deployment gates passed. The Linux host is the sole account writer; timers enabled.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["preflight", "deploy"])
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--account", type=Path, help="Optional existing local account to transfer")
    args = parser.parse_args()
    try:
        account = args.account
        local = Path(__file__).resolve().parents[1] / "reports/m3-cash-account"
        if account is None and local.is_dir():
            account = local
        execute(args.operation, args.artifact, account)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
