"""One explicitly authorized replacement of the legacy cash observation, resumable by name."""

import argparse
import shutil
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest import ibkr_observation
from invest.ibkr_store import publish
from invest.quality import regular_sessions

NAME = "m3-ibkr-cash-v1"
REQUEST_SCHEMA = pa.schema(
    [
        ("name", pa.string()),
        ("recorded_at", pa.timestamp("us", tz="UTC")),
        ("actor", pa.string()),
        ("reason", pa.string()),
        ("old_account_id", pa.string()),
        ("new_account_id", pa.string()),
        ("old_release", pa.string()),
    ],
    metadata={b"schema_version": b"invest.cash-restart.v1"},
)


def request_at(root: Path) -> dict[str, Any]:
    table = pq.read_table(root / "restarts" / NAME / "request.parquet")
    if table.num_rows != 1 or not table.schema.equals(REQUEST_SCHEMA, check_metadata=True):
        raise ValueError("Invalid cash restart request")
    request = dict(table.to_pylist()[0])
    if request["name"] != NAME:
        raise ValueError("Unexpected cash restart identity")
    return request


def before_open(status: dict[str, Any]) -> None:
    start = status["observation_start_session"]
    if isinstance(start, str):
        start = date.fromisoformat(start)
    opens = regular_sessions(start, start)["open_at"][0].as_py()
    if datetime.now(UTC) >= opens:
        raise ValueError("Prepared cash observation missed activation before its first open")


def prepare(root: Path, release: Path, metadata: Path, current: Path) -> dict[str, Any]:
    location = root / "restarts" / NAME
    location.mkdir(parents=True, exist_ok=True)
    account, candidate = root / "account", location / "account"
    if (location / "request.parquet").exists():
        request = request_at(root)
        selected = account if (account / "registration.parquet").exists() else candidate
        state = ibkr_observation.status(selected)
        ibkr_observation.verify(selected)
        if state["account_id"] != request["new_account_id"]:
            raise ValueError("Cash restart account differs from the prepared identity")
        if selected == candidate:
            before_open(state)
        return request
    if not (account / "journal").is_dir() or (account / "registration.parquet").exists():
        raise ValueError("First cash restart requires the existing legacy account")
    values = tomllib.loads(metadata.read_text())
    if set(values) != {"actor", "reason"} or any(
        not isinstance(value, str) or not value.strip() or len(value) > 500
        for value in values.values()
    ):
        raise ValueError("Cash restart requires its authorized actor and reason")
    old = pq.read_table(account / "journal" / "00000000" / "registration.parquet").to_pylist()[0]
    plan = tomllib.loads(old["observation_body"].decode())
    if plan.get("mode") != "cash_observation" or plan.get("candidate") != "cash":
        raise ValueError("This authorized restart applies only to the legacy cash observation")
    if not (candidate / "registration.parquet").exists():
        ibkr_observation.initialize(
            candidate,
            release / "configs" / "ibkr-cash.toml",
            release / "integrations" / "ibkr" / ".venv" / "bin" / "python",
            actor=values["actor"],
            reason=values["reason"],
        )
    ibkr_observation.verify(candidate)
    state = ibkr_observation.status(candidate)
    before_open(state)
    request = {
        "name": NAME,
        "recorded_at": datetime.now(UTC),
        **values,
        "old_account_id": old["account_id"],
        "new_account_id": state["account_id"],
        "old_release": str(current.resolve()),
    }
    publish(pa.Table.from_pylist([request], schema=REQUEST_SCHEMA), location / "request.parquet")
    return request


def activate(root: Path, operations: Path) -> None:
    """Called only while timers are stopped and all services have finished."""
    request = request_at(root)
    location = root / "restarts" / NAME
    account, candidate = root / "account", location / "account"
    archive = root / "archives" / NAME
    if (account / "registration.parquet").exists():
        state = ibkr_observation.status(account)
        ibkr_observation.verify(account)
        if state["account_id"] != request["new_account_id"] or not (archive / "account").is_dir():
            raise ValueError("Existing replacement is not this cash restart")
        return
    state = ibkr_observation.status(candidate)
    ibkr_observation.verify(candidate)
    if state["account_id"] != request["new_account_id"]:
        raise ValueError("Prepared cash restart account changed")
    before_open(state)
    archive.mkdir(parents=True, exist_ok=True)
    if not (archive / "request.parquet").exists():
        shutil.copy2(location / "request.parquet", archive / "request.parquet")
    if operations.exists() and not (archive / "operations.toml").exists():
        shutil.copy2(operations, archive / "operations.toml")
    if (root / "operations").exists():
        if (archive / "operations").exists():
            raise ValueError("Unexpected active service records during cash restart")
        (root / "operations").rename(archive / "operations")
    if account.exists():
        old = pq.read_table(account / "journal" / "00000000" / "registration.parquet").to_pylist()[
            0
        ]
        if old["account_id"] != request["old_account_id"] or (archive / "account").exists():
            raise ValueError("Legacy account changed before cash restart")
        account.rename(archive / "account")
    if not (archive / "account" / "journal").is_dir():
        raise ValueError("Legacy account archive is missing")
    candidate.rename(account)
    (root / "operations").mkdir(exist_ok=True)


def receipt(root: Path, release: Path, run: str) -> None:
    request = request_at(root)
    state = ibkr_observation.status(root / "account")
    ibkr_observation.verify(root / "account")
    if state["account_id"] != request["new_account_id"]:
        raise ValueError("Restart receipt account differs from the new observation")
    directory = root / "operations" / "deployments"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{run}.parquet"
    if not output.exists():
        publish(
            pa.Table.from_pylist(
                [
                    {
                        **request,
                        "recorded_at": datetime.now(UTC),
                        "run": run,
                        "commit": release.name,
                        "verified_head": state["head"],
                    }
                ],
            ),
            output,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate", "receipt"])
    parser.add_argument("--root", type=Path, default=Path("/var/lib/invest"))
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--current", type=Path, default=Path("/opt/invest/current"))
    parser.add_argument("--operations", type=Path, default=Path("/etc/invest/operations.toml"))
    parser.add_argument("--run")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.root, args.release, args.metadata, args.current)
    elif args.action == "activate":
        activate(args.root, args.operations)
    else:
        receipt(args.root, args.release, args.run)


if __name__ == "__main__":
    main()
