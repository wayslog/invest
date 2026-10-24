"""Deterministic source, clock and worker interleavings without network access."""

import os
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest import forward
from invest.alpaca import FetchSpec
from invest.forward import (
    _collect,
    _load,
    _runs,
    control_forward,
    forward_status,
    run_forward,
    verify_forward,
)
from invest.forward_config import Observation
from invest.forward_engine import ForwardState, next_session
from invest.forward_ops import forward_job
from invest.research_registry import register_study, seal
from invest.storage import engine_digest
from invest.study_config import StudyConfig
from tests.test_forward import initialize, save, setup, tick


@pytest.mark.parametrize("phase", ["_qualify", "_inputs"])
def test_init_rejects_source_change_after_admission_started(tmp_path: Path, phase: str) -> None:
    account, _, _ = setup(tmp_path)
    variant = tmp_path / "changed-engine"
    shutil.copytree("src/invest", variant / "invest", ignore=shutil.ignore_patterns("__pycache__"))
    # Actually edit a strategy in an isolated package, after the selected admission
    # phase has used the old code. Never modify the checkout or a capital account.
    driver = """
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch
from invest import forward
from invest.storage import engine_digest
from tests.test_forward import timestamp

root, phase = Path(sys.argv[1]), sys.argv[2]
original, initial = getattr(forward, phase), engine_digest()
def changed(*args, **kwargs):
    result = original(*args, **kwargs)
    source = Path(forward.__file__).with_name('legacy_strategies.py')
    body = source.read_text()
    modified = body.replace('scores[symbol] > 0', 'scores[symbol] > Decimal("0.5")')
    assert modified != body
    source.write_text(modified)
    assert engine_digest() != initial
    return result
with patch.object(forward, phase, changed):
    try:
        forward.init_forward(
            root / 'account', root / 'observation.toml', root / 'policy.toml',
            {s: root / f'{s}.parquet' for s in ['SPY', 'XLF']},
            at=timestamp(date(2024, 1, 5)),
        )
    except ValueError as exc:
        assert 'Engine changed' in str(exc), str(exc)
    else:
        raise AssertionError('Changed engine was accepted during initialization')
"""
    result = subprocess.run(
        [sys.executable, "-c", driver, str(tmp_path), phase],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(variant), str(Path.cwd())])},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not account.exists()
    assert not list(tmp_path.glob(".account.*.init"))


@pytest.mark.parametrize(
    "component", ["archive", "journal", "research_registration", "research_manifest"]
)
def test_resealed_genesis_with_inconsistent_engine_binding_is_rejected(
    tmp_path: Path, component: str
) -> None:
    account, _, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    genesis = _runs(account)[0]
    if component.startswith("research_"):
        registration = pq.read_table(genesis / "registration.parquet")
        rows = registration.to_pylist()
        rows[0]["observation_body"] = rows[0]["observation_body"].replace(
            b'mode="drill"', b'mode="shadow_research"'
        )
        pq.write_table(
            pa.Table.from_pylist(rows, schema=registration.schema),
            genesis / "registration.parquet",
            compression="zstd",
        )
        qualification = genesis / "qualification"
        qualification.mkdir()
        register_study(
            tmp_path / "policy.toml", qualification / "registration.parquet", known_history=True
        )
        pq.write_table(
            pa.table({"engine_sha256": [engine_digest()]}),
            qualification / "manifest.parquet",
            compression="zstd",
        )
        target = qualification / (
            "registration.parquet" if component == "research_registration" else "manifest.parquet"
        )
    else:
        target = genesis / (
            "engine-source.parquet" if component == "archive" else "journal.parquet"
        )
    table = pq.read_table(target)
    rows = table.to_pylist()
    if component == "archive":
        rows[0]["body"] += b"\n# Changed archive\n"
    else:
        rows[0]["engine_sha256"] = "0" * 64
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), target, compression="zstd")
    (genesis / "files.parquet").unlink()
    seal(genesis)
    with pytest.raises(ValueError, match="engine|Engine"):
        verify_forward(account)


@pytest.mark.parametrize("after_open", [False, True])
def test_failure_uses_completion_time_to_preserve_opened_orders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_open: bool
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    pending = _load(account)[-1].pending.copy()
    assert pending
    opening = next_session(date(2024, 1, 8))["open_at"]
    now = opening - timedelta(minutes=1)

    def invalid(*args: Any, **kwargs: Any) -> tuple[dict[str, pa.Table], datetime]:
        nonlocal now
        now = opening + (timedelta(minutes=1) if after_open else -timedelta(seconds=30))
        raise ValueError("Validation finished with an error")

    with monkeypatch.context() as patch:
        patch.setattr(forward, "clock", lambda: now)
        patch.setattr(forward, "_inputs", invalid)
        assert run_forward(account, sources)["status"] == "paused"
    last = _runs(account)[-1]
    assert pq.read_table(last / "journal.parquet")["recorded_at"][0].as_py() == now
    assert _load(account)[-1].pending == (pending if after_open else [])
    assert pq.read_table(last / "outcomes.parquet").num_rows == (0 if after_open else len(pending))
    tick(account, inputs, sources, 6)
    assert _collect(_runs(account), "trades").num_rows == (len(pending) if after_open else 0)
    assert verify_forward(account)["status"] == "verified"


@pytest.mark.parametrize("changed", ["clock", "engine"])
def test_failure_rechecks_clock_and_engine_before_committing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    original_runs = _runs(account)
    last_time = pq.read_table(original_runs[-1] / "journal.parquet")["recorded_at"][0].as_py()
    now = next_session(date(2024, 1, 8))["open_at"] - timedelta(minutes=1)
    digest = engine_digest()

    def invalid(*args: Any, **kwargs: Any) -> tuple[dict[str, pa.Table], datetime]:
        nonlocal now, digest
        if changed == "clock":
            now = last_time - timedelta(seconds=1)
        else:
            digest = "0" * 64
        raise ValueError("Validation failed")

    monkeypatch.setattr(forward, "clock", lambda: now)
    monkeypatch.setattr(forward, "engine_digest", lambda: digest)
    monkeypatch.setattr(forward, "_inputs", invalid)
    with pytest.raises(ValueError, match="backwards|engine changed"):
        run_forward(account, sources)
    assert _runs(account) == original_runs
    assert not list((account / "journal").glob(".*.tmp"))


def worker_plan(account: Path) -> tuple[list[Path], Observation, StudyConfig, ForwardState]:
    # Use the real drill ledger/admission for offline orchestration races. Only
    # the worker's network-mode check is substituted; no real capture is claimed.
    runs, plan, policy, state = _load(account)
    return runs, replace(plan, mode="shadow_research"), policy, state


@pytest.mark.parametrize("late_result", ["acquisition_failure", "invalid_batch"])
@pytest.mark.parametrize("winner", ["daily", "pause"])
def test_superseded_worker_cannot_change_a_newer_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_result: str, winner: str
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    save(inputs, sources, 5)
    now = datetime(2024, 1, 9, 6, tzinfo=UTC)
    monkeypatch.setattr(forward, "clock", lambda: now)
    monkeypatch.setattr("invest.forward_ops._load", worker_plan)
    batch = tmp_path / "late-batch"
    batch.mkdir()
    pq.write_table(
        pa.table({"status": ["research_only"]}), batch / "manifest.parquet", compression="zstd"
    )
    winning_status: dict[str, Any] = {}

    def delayed(spec: FetchSpec, root: Path) -> Path:
        nonlocal winning_status
        if not winning_status:
            if winner == "daily":
                assert run_forward(account, sources)["status"] == "active"
            else:
                control_forward(account, "pause", "owner", "Pause while the worker is fetching")
            winning_status = forward_status(account)
        if late_result == "acquisition_failure":
            raise ValueError("Older job finished with an acquisition error")
        return batch  # Delayed invalid data must be discarded before admission.

    monkeypatch.setattr("invest.forward_ops.fetch_dataset", delayed)
    result = forward_job(account, tmp_path / "data", tmp_path / "unused-issuer.parquet")
    assert result["updated"] is False and result["stale"] is True
    assert result["head"] == winning_status["head"]
    assert forward_status(account) == winning_status
    assert winning_status["commits"] == 2
    assert winning_status["pending_orders"] == (1 if winner == "daily" else 0)
    assert verify_forward(account)["status"] == "verified"


def test_current_worker_acquisition_failure_is_recorded_and_pauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account, _, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    monkeypatch.setattr(forward, "clock", lambda: datetime(2024, 1, 9, 6, tzinfo=UTC))
    monkeypatch.setattr("invest.forward_ops._load", worker_plan)

    def failed(spec: FetchSpec, root: Path) -> Path:
        raise OSError("Provider unavailable")

    monkeypatch.setattr("invest.forward_ops.fetch_dataset", failed)
    result = forward_job(account, tmp_path / "data", tmp_path / "unused-issuer.parquet")
    assert result["updated"] is True and result["status"] == "paused"
    assert "Provider unavailable" in result["error"]
    assert forward_status(account)["commits"] == 2
    assert verify_forward(account)["status"] == "verified"
