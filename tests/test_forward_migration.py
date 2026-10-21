"""Real archived-package replay across an append-only capital-account version boundary."""

import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.forward import (
    _load,
    _runs,
    control_forward,
    forward_status,
    run_forward,
    verify_forward,
)
from invest.forward_migration import migrate_forward
from invest.forward_ops import backup_forward, restore_forward
from invest.research_registry import seal
from invest.storage import engine_digest
from tests.test_forward import save, setup, timestamp


def legacy_account(
    tmp_path: Path, scenario: str = "pending"
) -> tuple[Path, dict[str, pa.Table], dict[str, Path]]:
    account, inputs, sources = setup(tmp_path)
    variant = tmp_path / "changed-engine"
    shutil.copytree("src/invest", variant / "invest", ignore=shutil.ignore_patterns("__pycache__"))
    strategy = variant / "invest" / "strategies.py"
    strategy.write_text(strategy.read_text() + "\n# Frozen previous release fixture\n")
    driver = """
import sys
from pathlib import Path
from decimal import Decimal
import pyarrow as pa
from tests.test_forward import setup, initialize, tick
root, scenario = Path(sys.argv[1]), sys.argv[2]
account, inputs, sources = setup(root)
if scenario == 'receivable':
    for symbol, table in inputs.items():
        rows = table.to_pylist()
        rows[6]['dividend'] = Decimal('1')
        rows[6]['dividend_pay_date'] = rows[8]['date']
        inputs[symbol] = pa.Table.from_pylist(rows, schema=table.schema)
if scenario == 'risk':
    for symbol, table in inputs.items():
        rows = table.to_pylist()
        rows[6].update(open=Decimal(30), high=Decimal(31), low=Decimal(29), close=Decimal(30))
        inputs[symbol] = pa.Table.from_pylist(rows, schema=table.schema)
initialize(root, account, sources)
end = 8 if scenario in {'risk', 'receivable'} else 7 if scenario == 'held' else 6
for length in range(5, end):
    tick(account, inputs, sources, length)
"""
    result = subprocess.run(
        [sys.executable, "-c", driver, str(tmp_path), scenario],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(variant), str(Path.cwd())])},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return account, inputs, sources


def migrate(account: Path, tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    status = forward_status(account, at=timestamp(date(2024, 1, 10)))
    return migrate_forward(
        account,
        kwargs.get("expected_head", status["head"]),
        kwargs.get("from_engine", status["active_engine_sha256"]),
        tmp_path / "pre-migration",
        "owner",
        "Verified release transition, preserve all capital history",
        at=timestamp(date(2024, 1, 10)),
    )


@pytest.mark.parametrize("scenario", ["pending", "held", "receivable", "risk"])
def test_migration_keeps_capital_obligations_risk_and_original_events(
    tmp_path: Path, scenario: str
) -> None:
    account, _, sources = legacy_account(tmp_path, scenario)
    runs, _, _, state = _load(account)
    old = state.tables()
    preserved = {
        path: path.read_bytes() for run in runs for path in run.rglob("*") if path.is_file()
    }
    original = forward_status(account, at=timestamp(date(2024, 1, 10)))
    if scenario == "pending":
        assert state.pending
    elif scenario == "held":
        assert any(a.shares for a in state.ledgers.values())
    elif scenario == "receivable":
        assert any(a.receivables for a in state.ledgers.values())
    else:
        assert state.risk_status == "halted" and state.peak > state.cash
    result = migrate(account, tmp_path)
    assert result["updated"] is True and result["status"] == "paused"
    current = forward_status(account, at=timestamp(date(2024, 1, 10)))
    assert current["account_id"] == original["account_id"]
    assert current["sessions"] == original["sessions"]
    assert current["migrations"] == 1 and current["engine_matches"]
    for path, body in preserved.items():
        assert path.read_bytes() == body
    tables = _load(account)[-1].tables()
    assert tables["ledgers"].equals(old["ledgers"], check_metadata=True)
    assert tables["pending"].equals(old["pending"], check_metadata=True)
    assert (
        tables["state"]
        .drop(["operations"])
        .equals(old["state"].drop(["operations"]), check_metadata=True)
    )
    assert verify_forward(account)["status"] == "verified"
    assert (
        migrate_forward(
            account,
            original["head"],
            original["active_engine_sha256"],
            tmp_path / "pre-migration",
            "owner",
            "Retry after committed transition",
            at=timestamp(date(2024, 1, 10)),
        )["updated"]
        is False
    )
    assert forward_status(account, at=timestamp(date(2024, 1, 10)))["head"] == current["head"]
    # Restoring the migrated chain also keeps the same logical account and state.
    saved = backup_forward(account, tmp_path / "post-migration")
    restored = restore_forward(
        tmp_path / "post-migration",
        tmp_path / "restored",
        saved["head"],
        "owner",
        "Recovery drill",
        at=timestamp(date(2024, 1, 10)),
    )
    assert restored["account_id"] == original["account_id"]
    assert verify_forward(tmp_path / "restored")["status"] == "verified"


@pytest.mark.parametrize("invalid", ["head", "engine"])
def test_migration_refuses_an_unexpected_parent_without_mutation(
    tmp_path: Path, invalid: str
) -> None:
    account, _, _ = legacy_account(tmp_path)
    original = _runs(account)
    kwargs = {"expected_head" if invalid == "head" else "from_engine": "0" * 64}
    with pytest.raises(ValueError, match="head|engine"):
        migrate(account, tmp_path, **kwargs)
    assert _runs(account) == original
    assert not (tmp_path / "pre-migration").exists()


def test_migration_failure_before_commit_preserves_parent_and_verified_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, _, _ = legacy_account(tmp_path)
    original = _runs(account)
    rename = Path.rename

    def crash(path: Path, target: Path) -> Path:
        if path.name.endswith(".tmp") and target.parent == account / "journal":
            raise OSError("Power loss before version commit")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", crash)
    with pytest.raises(OSError, match="Power loss"):
        migrate(account, tmp_path)
    assert _runs(account) == original
    assert (tmp_path / "pre-migration" / "backup.parquet").exists()
    assert not list((account / "journal").glob(".*.tmp"))


@pytest.mark.parametrize("field", ["cash", "peak", "risk_status", "sessions"])
def test_resealed_migration_cannot_reset_account_state(tmp_path: Path, field: str) -> None:
    account, _, _ = legacy_account(tmp_path)
    migrate(account, tmp_path)
    boundary = _runs(account)[-1]
    table = pq.read_table(boundary / "state.parquet")
    rows = table.to_pylist()
    rows[0][field] = {"cash": 9999, "peak": 1, "risk_status": "terminated", "sessions": 0}[field]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        boundary / "state.parquet",
        compression="zstd",
    )
    (boundary / "files.parquet").unlink()
    seal(boundary)
    with pytest.raises(ValueError, match="capital, risk or obligations"):
        verify_forward(account)


def test_new_epoch_accounts_existing_orders_without_backfilling_missed_decisions(
    tmp_path: Path,
) -> None:
    account, inputs, sources = legacy_account(tmp_path)
    migrate(account, tmp_path)
    save(inputs, sources, 7)
    result = run_forward(account, sources, at=timestamp(date(2024, 1, 10)) + timedelta(minutes=1))
    assert result["status"] == "paused"
    assert forward_status(account, at=timestamp(date(2024, 1, 10)))["fills"] == 1
    control_forward(
        account,
        "resume",
        "owner",
        "Reviewed migration and missed task",
        at=timestamp(date(2024, 1, 10)) + timedelta(minutes=2),
    )
    assert verify_forward(account)["status"] == "verified"
    assert (
        forward_status(account, at=timestamp(date(2024, 1, 10)))["active_engine_sha256"]
        == engine_digest()
    )


def test_migration_replays_the_old_engine_instead_of_trusting_a_resealed_snapshot(
    tmp_path: Path,
) -> None:
    account, _, _ = legacy_account(tmp_path)
    last = _runs(account)[-1]
    table = pq.read_table(last / "state.parquet")
    rows = table.to_pylist()
    rows[0]["cash"] += 100
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema), last / "state.parquet", compression="zstd"
    )
    (last / "files.parquet").unlink()
    seal(last)
    before = _runs(account)
    with pytest.raises(ValueError, match="Archived-engine replay failed"):
        migrate(account, tmp_path)
    assert _runs(account) == before
    assert not (tmp_path / "pre-migration").exists()


def test_two_engine_boundaries_replay_each_prefix_with_its_own_archived_source(
    tmp_path: Path,
) -> None:
    account, _, _ = legacy_account(tmp_path)
    migrate(account, tmp_path)
    original = forward_status(account, at=timestamp(date(2024, 1, 10)))
    variant = tmp_path / "next" / "changed-engine"
    shutil.copytree("src/invest", variant / "invest", ignore=shutil.ignore_patterns("__pycache__"))
    source = variant / "invest" / "strategies.py"
    source.write_text(source.read_text() + "\n# Third frozen release fixture\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest",
            "forward-migrate",
            "--account",
            str(account),
            "--expected-head",
            original["head"],
            "--from-engine",
            original["active_engine_sha256"],
            "--backup",
            str(tmp_path / "second-backup"),
            "--actor",
            "owner",
            "--reason",
            "Second audited transition",
            "--at",
            "2024-01-10T22:00:00Z",
        ],
        env={**os.environ, "PYTHONPATH": str(variant)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    verification = subprocess.run(
        [sys.executable, "-m", "invest", "forward-verify", "--account", str(account)],
        env={**os.environ, "PYTHONPATH": str(variant)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert verification.returncode == 0, verification.stdout + verification.stderr
    status = forward_status(account, at=timestamp(date(2024, 1, 10)) + timedelta(hours=1))
    assert status["migrations"] == 2 and status["account_id"] == original["account_id"]
