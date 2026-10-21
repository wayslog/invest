"""GitHub runner transport. Private payloads never become Actions artifacts or log output."""

import argparse
import json
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
) -> bytes:
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
            ("permission denied (publickey", "SSH key authentication failed"),
            ("could not resolve hostname", "SSH hostname could not be resolved"),
        ):
            if needle in stderr:
                detail = message
                break
        # Only our fixed, data-free diagnostic lines can enter public workflow logs.
        markers = re.findall(r"^deploy_error: ([a-z0-9 ,;._-]+)$", stderr, re.MULTILINE)
        if markers:
            detail = markers[0]
        raise RuntimeError(f"{label}: {detail} (exit {result.returncode})")
    return bytes(result.stdout)


def execute(
    operation: str,
    artifact: Path | None,
    account: Path | None = None,
) -> None:
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
        identity = work / "identity"
        identity.write_text(key.replace("\r\n", "\n").rstrip() + "\n")
        identity.chmod(0o600)
        # The operator explicitly trusts this host; do not enroll or pin host keys.
        options = [
            "-F",
            "/dev/null",
            "-i",
            str(identity),
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "StrictHostKeyChecking=no",
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
        if operation == "inspect":
            summary = run_quiet(
                [*ssh, "bash -s"],
                "Inspect deployed runtime",
                data=(root / "inspect.sh").read_bytes(),
                timeout=300,
            )
            print(summary.decode(), end="")
            return
        if operation == "migrate" and account is not None:
            raise ValueError("Migration must use the existing authoritative host account")
        commit = required("INVEST_DEPLOY_COMMIT", r"[0-9a-f]{40}")
        run = required("INVEST_DEPLOY_RUN", r"[0-9]+-[0-9]+")
        archives = list(artifact.glob("*.tar.gz")) if artifact else []
        if len(archives) != 1:
            raise ValueError("Expected one source archive from the build job")
        payload = work / "payload"
        payload.mkdir(mode=0o700)
        shutil.copyfile(archives[0], payload / "source.tar.gz")
        if operation == "migrate":
            actor = required("GITHUB_ACTOR", r"[A-Za-z0-9_.\[\]-]{1,128}")
            reason = required("INVEST_MIGRATION_REASON")
            if len(reason) > 500:
                raise ValueError("Migration reason is too long")
            request = payload / "migration.toml"
            request.write_text(
                f"actor = {json.dumps('github:' + actor)}\nreason = {json.dumps(reason)}\n"
            )
            request.chmod(0o600)
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
            arguments = [incoming, commit, run]
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
        print("Deployment completed. The Linux host is the sole account writer; timers enabled.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["preflight", "inspect", "deploy", "migrate"])
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--account", type=Path, help="Optional existing local account to transfer")
    args = parser.parse_args()
    try:
        execute(args.operation, args.artifact, args.account)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
