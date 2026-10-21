"""Deployment gates and explicitly requested cash-account engine transitions."""

import argparse
import hashlib
import os
import re
import sys
import tarfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_digest(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A lowercase SHA-256 digest is required")
    return value


def extract_account(archive: Path, destination: Path) -> Path:
    """Accept only a bounded, link-free account/journal tree into a new private directory."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("Bootstrap staging directory must not exist")
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members or len(members) > 20_000:
            raise ValueError("Account archive has an invalid entry count")
        seen: set[str] = set()
        total = 0
        for member in members:
            name = PurePosixPath(member.name)
            parts = name.parts
            if (
                name.is_absolute()
                or ".." in parts
                or not parts
                or parts[0] != "account"
                or (len(parts) > 1 and parts[1] != "journal")
                or (not member.isdir() and (not member.isfile() or len(parts) < 4))
                or name.as_posix() in seen
                or member.size > 64 * 1024 * 1024
            ):
                raise ValueError("Unsafe account archive entry")
            seen.add(name.as_posix())
            total += member.size
            if total > 512 * 1024 * 1024:
                raise ValueError("Account archive exceeds the extraction limit")
        destination.mkdir(mode=0o700, parents=True)
        bundle.extractall(destination, members=members, filter="data")
    for path in destination.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    account = destination / "account"
    if not (account / "journal").is_dir():
        raise ValueError("Account archive is missing its journal")
    return account


def check_identity(
    status: dict[str, Any], account_id: str | None = None, head: str | None = None
) -> None:
    if account_id is not None and status["account_id"] != account_id:
        raise ValueError("Deployment account identity mismatch")
    if head is not None and status["head"] != require_digest(head):
        raise ValueError("Deployment account head changed; inspect before retrying")
    if not status["engine_matches"]:
        raise ValueError("Engine migration is required before deployment")
    if status["operations"] != "active":
        raise ValueError("Deployment cannot resume a paused, stopped or completed account")
    if status["mode"] != "cash_observation":
        raise ValueError("This deployment path is for the existing cash observation only")


def verify_account(
    account: Path, account_id: str | None = None, head: str | None = None
) -> dict[str, Any]:
    from invest.forward import forward_status, verify_forward

    verified = verify_forward(account)
    status = forward_status(account)
    check_identity(status, account_id, head)
    if verified["head"] != status["head"]:
        raise ValueError("Account changed during deployment verification")
    return status


def migration_identity(account: Path) -> dict[str, Any]:
    from invest.forward import _runs, account_lock, forward_status
    from invest.forward_versions import verify_archived

    status = forward_status(account)
    if (
        status["mode"] != "cash_observation"
        or status["operations"] != "active"
        or status["risk_status"] != "active"
        or status["missing_sessions"] != 0
        or status["engine_matches"]
    ):
        raise ValueError(
            "Explicit migration requires a current, active cash account and a new engine"
        )
    with account_lock(account):
        runs = _runs(account)
        if digest(runs[-1] / "files.parquet") != status["head"]:
            raise ValueError("Account changed before archived-engine verification")
        verify_archived(runs, status["active_engine_sha256"])
    return status


def migrate_account(account: Path, account_id: str, head: str, request: Path, backup: Path) -> None:
    from invest.forward import _load, account_lock, control_forward, forward_status, verify_forward
    from invest.forward_migration import migrate_forward

    content = sys.stdin.read(16_385) if str(request) == "-" else request.read_text()
    if len(content) > 16_384:
        raise ValueError("Migration request is too large")
    metadata = tomllib.loads(content)
    if set(metadata) != {"actor", "reason"} or any(
        not isinstance(value, str) or not value.strip() or len(value) > 500
        for value in metadata.values()
    ):
        raise ValueError("Explicit migration requires an actor and a reason")
    original = migration_identity(account)
    if original["account_id"] != account_id or original["head"] != require_digest(head):
        raise ValueError("Account changed before the explicit migration")
    with account_lock(account):
        runs, _, _, state = _load(account)
        original_files = {path / "files.parquet": digest(path / "files.parquet") for path in runs}
        original_tables = state.tables()
    result = migrate_forward(
        account,
        head,
        original["active_engine_sha256"],
        backup,
        metadata["actor"],
        metadata["reason"],
    )
    verify_forward(account)
    paused = forward_status(account)
    if paused["account_id"] != account_id or paused["head"] != result["head"]:
        raise ValueError("Account changed after migration; it was not resumed")
    # The engine itself requires up-to-date accounting and preserves the risk latch.
    control_forward(
        account,
        "resume",
        metadata["actor"],
        metadata["reason"] + "; migration, capital and risk verified before resuming",
    )
    verify_account(account, account_id)
    with account_lock(account):
        current_tables = _load(account)[-1].tables()
        if any(digest(path) != value for path, value in original_files.items()) or any(
            not table.equals(current_tables[name], check_metadata=True)
            for name, table in original_tables.items()
        ):
            raise ValueError("Migration changed capital, risk, obligations or original history")


def pack_account(account: Path, output: Path) -> None:
    """Export only a fully verified journal, without asking for account metadata."""
    from invest.forward import _runs, account_lock

    status = verify_account(account)
    if output.resolve().is_relative_to(account.resolve()):
        raise ValueError("Account export must be outside the account")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with account_lock(account):
        runs = _runs(account)
        if digest(runs[-1] / "files.parquet") != status["head"]:
            raise ValueError("Account changed before export; retry after the writer finishes")
        with output.open("xb") as stream:
            output.chmod(0o600)
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                for run in runs:
                    archive.add(run, arcname=f"account/journal/{run.name}")


def write_receipt(account: Path, account_id: str, head: str, release: Path, run: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    status = verify_account(account, account_id, None)
    schema = pa.schema(
        [
            ("recorded_at", pa.timestamp("us", tz="UTC")),
            ("run", pa.string()),
            ("commit", pa.string()),
            ("source_sha256", pa.string()),
            ("engine_sha256", pa.string()),
            ("account_id", pa.string()),
            ("handover_head", pa.string()),
            ("verified_head", pa.string()),
            ("authoritative_account", pa.string()),
        ]
    )
    root = account.parent / "operations" / "deployments"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = root / f"{run}.parquet"
    row = {
        "recorded_at": datetime.now(UTC),
        "run": run,
        "commit": release.name,
        "source_sha256": (release / ".source-sha256").read_text().strip(),
        "engine_sha256": status["active_engine_sha256"],
        "account_id": account_id,
        "handover_head": require_digest(head),
        "verified_head": status["head"],
        "authoritative_account": str(account),
    }
    # Exclusive publication; never replace another deployment's audit receipt.
    with output.open("xb") as stream:
        pq.write_table(pa.Table.from_pylist([row], schema=schema), stream, compression="zstd")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("digest")
    command.add_argument("directory", type=Path)
    command = commands.add_parser("extract-account")
    command.add_argument("archive", type=Path)
    command.add_argument("destination", type=Path)
    for name in ("identity", "migration-identity"):
        command = commands.add_parser(name)
        command.add_argument("account", type=Path)
    command = commands.add_parser("pack-account")
    command.add_argument("account", type=Path)
    command.add_argument("output", type=Path)
    command = commands.add_parser("migrate")
    command.add_argument("account", type=Path)
    command.add_argument("account_id")
    command.add_argument("head")
    command.add_argument("request", type=Path)
    command.add_argument("backup", type=Path)
    for name in ("verify", "receipt"):
        command = commands.add_parser(name)
        command.add_argument("account", type=Path)
        command.add_argument("account_id")
        command.add_argument("head")
        if name == "receipt":
            command.add_argument("release", type=Path)
            command.add_argument("run")
    args = parser.parse_args()
    if args.command == "digest":
        archives = list(args.directory.glob("*.tar.gz"))
        if len(archives) != 1:
            raise ValueError("Expected exactly one source release")
        print(f"source_sha256={digest(archives[0])}")
    elif args.command == "extract-account":
        extract_account(args.archive, args.destination)
    elif args.command in {"identity", "migration-identity"}:
        status = (
            migration_identity(args.account)
            if args.command == "migration-identity"
            else verify_account(args.account)
        )
        if not re.fullmatch(r"[0-9a-f]{32}", status["account_id"]):
            raise ValueError("Invalid account identity in journal")
        print(f"{status['account_id']} {require_digest(status['head'])}")
    elif args.command == "pack-account":
        pack_account(args.account, args.output)
    elif args.command == "verify":
        verify_account(args.account, args.account_id, args.head)
    elif args.command == "migrate":
        migrate_account(args.account, args.account_id, args.head, args.request, args.backup)
    else:
        write_receipt(args.account, args.account_id, args.head, args.release, args.run)


if __name__ == "__main__":
    main()
