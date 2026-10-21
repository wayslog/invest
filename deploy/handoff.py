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


def encrypt_archive(archive: Path, certificate: Path, work: Path) -> bytes:
    """Use signed-and-enveloped CMS, supported by the host's older OpenSSL."""
    signer, key = work / "signer.pem", work / "signer.key"
    signed, cipher = work / "account.signed", work / "account.cms"
    quiet(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-sha256",
            "-days",
            "2",
            "-subj",
            "/CN=invest-account-source",
            "-keyout",
            str(key),
            "-out",
            str(signer),
        ]
    )
    key.chmod(0o600)
    quiet(
        [
            "openssl",
            "cms",
            "-sign",
            "-binary",
            "-nodetach",
            "-md",
            "sha256",
            "-in",
            str(archive),
            "-signer",
            str(signer),
            "-inkey",
            str(key),
            "-out",
            str(signed),
            "-outform",
            "DER",
        ]
    )
    quiet(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-cbc",
            "-recip",
            str(certificate),
            "-keyopt",
            "rsa_padding_mode:oaep",
            "-keyopt",
            "rsa_oaep_md:sha256",
            "-in",
            str(signed),
            "-out",
            str(cipher),
            "-outform",
            "DER",
        ]
    )
    return json.dumps(
        {
            "cms": base64.b64encode(cipher.read_bytes()).decode(),
            "signer_certificate": signer.read_text(),
        }
    ).encode()


def handoff(account: Path, certificate: Path, repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    with tempfile.TemporaryDirectory(prefix="invest-handoff-") as directory:
        work = Path(directory)
        archive = work / "account.tar.gz"
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
        encrypted = encrypt_archive(archive, certificate, work)
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
