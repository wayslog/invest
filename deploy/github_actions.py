"""GitHub runner transport. Private payloads never become Actions artifacts or log output."""

import argparse
import base64
import hashlib
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
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

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
            detail = markers[0]
        raise RuntimeError(f"{label}: {detail} (exit {result.returncode})")
    return bytes(result.stdout)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def download_handoff(blob: str) -> bytes:
    """Fetch only ciphertext, pinned to its Git object ID, with a bounded response."""
    if not re.fullmatch(r"[0-9a-f]{40}", blob):
        raise ValueError("Invalid encrypted handover object")
    repository = required("GITHUB_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    token = required("GITHUB_TOKEN")
    request = Request(
        f"https://api.github.com/repos/{repository}/git/blobs/{blob}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Encrypted handover object is too large")
        record = json.loads(raw)
        if record["encoding"] != "base64":
            raise ValueError("Unexpected encrypted handover encoding")
        data = base64.b64decode("".join(record["content"].split()), validate=True)
    except (HTTPError, URLError, TimeoutError, OSError, KeyError, TypeError):
        raise ValueError("Unable to read the encrypted handover object") from None
    header = f"blob {len(data)}\0".encode()
    if hashlib.sha1(header + data).hexdigest() != blob:
        raise ValueError("Encrypted handover Git object changed")
    return data


def execute(
    operation: str,
    artifact: Path | None,
    account: Path | None = None,
    handoff_blob: str = "",
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
            version = run_quiet([*ssh, "openssl version"], "Check host cryptography")
            match = re.match(rb"OpenSSL ([0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.-]*)\b", version)
            if match:
                print("Host OpenSSL version:", match[1].decode("ascii"))
            return
        if operation == "prepare-handoff":
            certificate = run_quiet(
                [*ssh, "bash -s"],
                "Prepare encrypted handover",
                data=(root / "prepare-handoff.sh").read_bytes(),
            )
            if not re.fullmatch(
                rb"-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+-----END CERTIFICATE-----\n",
                certificate,
            ):
                raise ValueError("Invalid public handover certificate")
            Path("handoff-recipient.pem").write_bytes(certificate)
            print("Public handover certificate prepared; private key remains on the host.")
            return
        if operation == "inspect":
            certificate_text = required("INVEST_INSPECTION_RECIPIENT")
            if not re.fullmatch(
                r"-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+-----END CERTIFICATE-----\n?",
                certificate_text,
            ):
                raise ValueError("Invalid public inspection recipient")
            prefix = b"recipient_base64=" + base64.b64encode(certificate_text.encode()) + b"\n"
            encrypted = run_quiet(
                [*ssh, "bash -s"],
                "Inspect deployed runtime",
                data=prefix + (root / "inspect.sh").read_bytes(),
                timeout=300,
            )
            Path("runtime-inspection.cms").write_bytes(encrypted)
            Path("runtime-inspection.cms").chmod(0o600)
            print("Runtime inspection encrypted for the operator; private host output withheld.")
            return
        if account is not None and handoff_blob:
            raise ValueError("Choose one source for the existing account")
        if operation == "migrate" and (account is not None or handoff_blob):
            raise ValueError("Migration must use the existing authoritative host account")
        commit = required("INVEST_DEPLOY_COMMIT", r"[0-9a-f]{40}")
        run = required("INVEST_DEPLOY_RUN", r"[0-9]+-[0-9]+")
        source_sha = required("INVEST_RELEASE_SHA256", r"[0-9a-f]{64}")
        archives = list(artifact.glob("*.tar.gz")) if artifact else []
        if len(archives) != 1 or digest(archives[0]) != source_sha:
            raise ValueError("Tested source artifact is missing or its checksum changed")
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
        if handoff_blob:
            envelope = json.loads(download_handoff(handoff_blob))
            signer = envelope["signer_certificate"]
            if not isinstance(signer, str) or not re.fullmatch(
                r"-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+-----END CERTIFICATE-----\n?",
                signer,
            ):
                raise ValueError("Invalid public handover signer")
            (payload / "account-signer.pem").write_text(signer)
            (payload / "account-signer.pem").chmod(0o600)
            (payload / "account.cms").write_bytes(base64.b64decode(envelope["cms"], validate=True))
            (payload / "account.cms").chmod(0o600)
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
    parser.add_argument(
        "operation", choices=["preflight", "prepare-handoff", "inspect", "deploy", "migrate"]
    )
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--account", type=Path, help="Optional existing local account to transfer")
    parser.add_argument(
        "--handoff-blob", default="", help="Optional encrypted first-handover object"
    )
    args = parser.parse_args()
    try:
        account = args.account
        local = Path(__file__).resolve().parents[1] / "reports/m3-cash-account"
        if (
            args.operation == "deploy"
            and account is None
            and not args.handoff_blob
            and local.is_dir()
        ):
            account = local
        execute(args.operation, args.artifact, account, args.handoff_blob)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
