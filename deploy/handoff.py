"""Encrypt the existing local account and dispatch its first handover through Actions."""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def quiet(command: list[str], data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(command, input=data, capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(
            "Handover preparation command could not complete; output withheld"
        ) from None
    if result.returncode:
        raise ValueError("Handover preparation command failed; private output withheld")
    return bytes(result.stdout)


def handoff(account: Path, certificate: Path, repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    with tempfile.TemporaryDirectory(prefix="invest-handoff-") as directory:
        work = Path(directory)
        archive, cipher = work / "account.tar.gz", work / "account.cms"
        quiet(["openssl", "x509", "-in", str(certificate), "-noout", "-checkend", "0"])
        quiet(
            [
                sys.executable,
                str(Path(__file__).with_name("release.py")),
                "pack-account",
                str(account),
                str(archive),
            ]
        )
        quiet(
            [
                "openssl",
                "cms",
                "-encrypt",
                "-binary",
                "-aes-256-gcm",
                "-recip",
                str(certificate),
                "-keyopt",
                "rsa_padding_mode:oaep",
                "-keyopt",
                "rsa_oaep_md:sha256",
                "-in",
                str(archive),
                "-out",
                str(cipher),
                "-outform",
                "DER",
            ]
        )
        encrypted = cipher.read_bytes()
        request = json.dumps(
            {"encoding": "base64", "content": base64.b64encode(encrypted).decode()}
        ).encode()
        response = quiet(
            ["gh", "api", "--method", "POST", f"repos/{repository}/git/blobs", "--input", "-"],
            request,
        )
        blob = json.loads(response)["sha"]
        expected = hashlib.sha1(f"blob {len(encrypted)}\0".encode() + encrypted).hexdigest()
        if blob != expected:
            raise ValueError("Uploaded encrypted object identity mismatch")
        quiet(
            [
                "gh",
                "workflow",
                "run",
                "deploy.yml",
                "--repo",
                repository,
                "--ref",
                "main",
                "-f",
                "operation=deploy",
                "-f",
                f"handoff_blob={blob}",
            ]
        )
        return str(blob)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=Path, default=Path("reports/m3-cash-account"))
    parser.add_argument("--recipient", type=Path, required=True)
    parser.add_argument("--repo", default="wayslog/invest")
    args = parser.parse_args()
    try:
        handoff(args.account, args.recipient, args.repo)
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "Encrypted handover preparation failed; private command output withheld.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print("Encrypted account handed to the deployment workflow; follow Deploy to Linux in Actions.")


if __name__ == "__main__":
    main()
