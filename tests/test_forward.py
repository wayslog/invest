import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from filelock import FileLock

from invest.cli import main
from invest.forward import (
    _collect,
    _load,
    _runs,
    control_forward,
    forward_status,
    init_forward,
    run_forward,
    verify_forward,
)
from invest.forward_engine import next_session
from invest.forward_ops import backup_forward, forward_job, restore_forward
from invest.quality import regular_sessions
from invest.research_registry import seal
from tests.test_portfolio import bars


def timestamp(session: date) -> datetime:
    return regular_sessions(session, session)["close_at"][0].as_py() + timedelta(minutes=5)  # type: ignore[no-any-return]


def setup(
    tmp_path: Path, *, sessions: int = 60, mode: str = "drill", candidate: str = "trend-2"
) -> tuple[Path, dict[str, pa.Table], dict[str, Path]]:
    policy = tmp_path / "policy.toml"
    policy.write_text(
        Path("configs/m2.toml")
        .read_text()
        .replace("[40, 60, 80]", "[2, 3]")
        .replace("correlation_window = 60", "correlation_window = 3")
        .replace("rebalance_sessions = 21", "rebalance_sessions = 3")
    )
    observation = tmp_path / "observation.toml"
    observation.write_text(
        f'name="test-observation"\nmode="{mode}"\nsymbols=["SPY","XLF"]\n'
        f'candidate="{candidate}"\nstart_session=2024-01-08\nsessions={sessions}\n'
        "minimum_fills=0\nmax_capture_age_minutes=120\n"
    )
    inputs = {
        "SPY": bars("SPY", [100, 101, 103, 102, 105, 104, 107, 108, 110, 109, 112, 111]),
        "XLF": bars("XLF", [90, 93, 91, 94, 92, 95, 93, 96, 94, 97, 95, 98]),
    }
    sources = {s: tmp_path / f"{s}.parquet" for s in inputs}
    save(inputs, sources, 4)
    return tmp_path / "account", inputs, sources


def save(inputs: dict[str, pa.Table], sources: dict[str, Path], length: int) -> None:
    for s, table in inputs.items():
        pq.write_table(table.slice(0, length), sources[s], compression="zstd")


def initialize(tmp_path: Path, account: Path, sources: dict[str, Path]) -> None:
    init_forward(
        account,
        tmp_path / "observation.toml",
        tmp_path / "policy.toml",
        sources,
        at=timestamp(date(2024, 1, 5)),
    )


def tick(
    account: Path, inputs: dict[str, pa.Table], sources: dict[str, Path], length: int
) -> dict[str, Any]:
    save(inputs, sources, length)
    return run_forward(account, sources, at=timestamp(inputs["SPY"]["date"][length - 1].as_py()))


def test_orders_are_committed_before_delayed_fills_and_retry_is_idempotent(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    runs = _runs(account)
    orders = _collect(runs, "orders").to_pylist()
    assert orders and not _collect(runs, "trades").num_rows
    assert all(r["decided_at"] < r["effective_at"] for r in orders)
    tick(account, inputs, sources, 6)
    head = forward_status(account, at=timestamp(date(2024, 1, 9)))["head"]
    assert tick(account, inputs, sources, 6)["updated"] is False
    assert forward_status(account, at=timestamp(date(2024, 1, 9)))["head"] == head
    fills = _collect(_runs(account), "trades").to_pylist()
    assert fills and all(r["decided_at"] < r["proxy_at"] < r["recorded_at"] for r in fills)
    assert set(r["order_id"] for r in fills) <= set(r["order_id"] for r in orders)
    assert verify_forward(account)["reconciliation_checks"] > 0


def test_missed_runs_account_for_existing_orders_without_backfilling_decisions(
    tmp_path: Path,
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    assert tick(account, inputs, sources, 8)["status"] == "paused"
    runs = _runs(account)
    assert set(_collect(runs, "orders")["decision_date"].to_pylist()) == {date(2024, 1, 8)}
    assert set(_collect(runs, "trades")["date"].to_pylist()) == {date(2024, 1, 9)}
    assert _collect(runs, "equity").num_rows == 4
    assert "missed_decision" in _collect(runs, "events")["kind"].to_pylist()
    control_forward(
        account, "resume", "tester", "Reviewed missed tasks", at=timestamp(date(2024, 1, 11))
    )
    assert tick(account, inputs, sources, 8)["updated"] is False
    assert verify_forward(account)["status"] == "verified"


def test_revision_and_stale_data_pause_without_rewriting_original_decisions(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    original = (account / "journal" / "00000001" / "files.parquet").read_bytes()
    revised = inputs["SPY"].to_pylist()
    revised[4]["close"] += Decimal(".1")
    revised[4]["high"] += Decimal(".1")
    changed = {**inputs, "SPY": pa.Table.from_pylist(revised, schema=inputs["SPY"].schema)}
    assert "revision" in tick(account, changed, sources, 6)["error"]
    assert (account / "journal" / "00000001" / "files.parquet").read_bytes() == original
    assert _load(account)[-1].last_session == date(2024, 1, 8)
    with pytest.raises(ValueError, match="Catch up"):
        control_forward(account, "resume", "tester", "too soon", at=timestamp(date(2024, 1, 9)))
    tick(account, inputs, sources, 6)
    assert verify_forward(account)["status"] == "verified"
    # Missing latest bar is a failure even if the supplied data is unchanged.
    result = run_forward(account, sources, at=timestamp(date(2024, 1, 10)))
    assert "Missing latest" in result["error"]


def test_pause_before_open_cancels_but_pause_after_open_keeps_obligations(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    control_forward(
        account,
        "pause",
        "tester",
        "before open",
        at=timestamp(date(2024, 1, 8)) + timedelta(minutes=1),
    )
    assert not _load(account)[-1].pending
    tick(account, inputs, sources, 6)
    assert not _collect(_runs(account), "trades").num_rows
    control_forward(account, "resume", "tester", "review complete", at=timestamp(date(2024, 1, 9)))
    tick(account, inputs, sources, 7)
    tick(account, inputs, sources, 8)
    pending = _load(account)[-1].pending
    assert pending
    opening = next_session(date(2024, 1, 11))["open_at"]
    control_forward(account, "pause", "tester", "after open", at=opening + timedelta(minutes=1))
    assert _load(account)[-1].pending == pending
    tick(account, inputs, sources, 9)
    assert _collect(_runs(account), "trades").num_rows
    assert verify_forward(account)["status"] == "verified"


def test_risk_latch_and_high_water_mark_survive_pause_resume_and_restore(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    tick(account, inputs, sources, 6)
    crash = {s: t.to_pylist() for s, t in inputs.items()}
    for rows in crash.values():
        rows[6].update(open=Decimal(30), high=Decimal(31), low=Decimal(29), close=Decimal(30))
    falling = {s: pa.Table.from_pylist(rows, schema=inputs[s].schema) for s, rows in crash.items()}
    tick(account, falling, sources, 7)
    state = _load(account)[-1]
    assert state.risk_status in {"halted", "terminated"} and state.peak >= 5000
    risk, peak, cash = state.risk_status, state.peak, state.cash
    control_forward(account, "pause", "tester", "review drawdown", at=timestamp(date(2024, 1, 10)))
    control_forward(
        account, "resume", "tester", "operations recovered", at=timestamp(date(2024, 1, 10))
    )
    assert (_load(account)[-1].risk_status, _load(account)[-1].peak) == (risk, peak)
    backup = backup_forward(account, tmp_path / "backup")
    restored = tmp_path / "restored"
    status = restore_forward(
        tmp_path / "backup",
        restored,
        backup["head"],
        "tester",
        "fault drill",
        at=timestamp(date(2024, 1, 10)),
    )
    assert status["risk_status"] == risk and Decimal(status["peak"]) == peak
    assert Decimal(status["cash"]) == cash and status["operations"] == "paused"
    assert (
        status["account_id"]
        == forward_status(account, at=timestamp(date(2024, 1, 10)))["account_id"]
    )
    assert verify_forward(restored)["status"] == "verified"


def test_publication_crash_and_process_restart_do_not_duplicate_fills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    rename = Path.rename

    def fail_before(self: Path, target: Path) -> Path:
        if target.name == "00000002":
            raise OSError("simulated crash before commit")
        return rename(self, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_before)
        with pytest.raises(OSError, match="simulated"):
            tick(account, inputs, sources, 6)
    assert len(_runs(account)) == 2
    assert not _collect(_runs(account), "trades").num_rows

    def fail_after(self: Path, target: Path) -> Path:
        result = rename(self, target)
        if target.name == "00000002":
            raise OSError("simulated crash after commit")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_after)
        with pytest.raises(OSError, match="after commit"):
            tick(account, inputs, sources, 6)
    assert len(_runs(account)) == 3
    trades = _collect(_runs(account), "trades")
    assert tick(account, inputs, sources, 6)["updated"] is False
    assert _collect(_runs(account), "trades").equals(trades)
    assert verify_forward(account)["status"] == "verified"


def test_lock_engine_change_and_existing_capital_account_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    with pytest.raises(ValueError, match="already exists"):
        initialize(tmp_path, account, sources)
    with (
        FileLock(account / ".lock", timeout=0),
        pytest.raises(ValueError, match="Another process"),
    ):
        tick(account, inputs, sources, 5)
    monkeypatch.setattr("invest.forward.engine_digest", lambda: "changed")
    with pytest.raises(ValueError, match="engine changed"):
        tick(account, inputs, sources, 5)
    assert len(_runs(account)) == 1


def test_registered_observation_end_liquidates_and_requires_event_coverage(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path, sessions=2)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    tick(account, inputs, sources, 6)
    state = _load(account)[-1]
    assert state.pending and all(p["reason"] == "observation_end" for p in state.pending)
    tick(account, inputs, sources, 7)
    assert _load(account)[-1].operations == "completed"
    with pytest.raises(ValueError, match="stopped/completed"):
        tick(account, inputs, sources, 8)
    assert verify_forward(account)["status"] == "verified"


def test_split_dividend_and_restart_reconcile_exactly(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    rows = inputs["SPY"].to_pylist()
    rows[6].update(
        open=Decimal(54),
        close=Decimal(53),
        high=Decimal(55),
        low=Decimal(52),
        split_ratio=2,
        dividend=Decimal(".5"),
        dividend_pay_date=rows[8]["date"],
    )
    for i in range(7, len(rows)):
        for key in ["open", "close", "high", "low"]:
            rows[i][key] /= 2
    inputs["SPY"] = pa.Table.from_pylist(rows, schema=inputs["SPY"].schema)
    initialize(tmp_path, account, sources)
    for length in range(5, 10):
        tick(account, inputs, sources, length)
    events = _collect(_runs(account), "events").to_pylist()
    assert {"split", "dividend_entitlement", "dividend_payment"} <= {r["kind"] for r in events}
    assert verify_forward(account)["status"] == "verified"


def test_replay_detects_state_corruption_even_if_inventory_is_resealed(tmp_path: Path) -> None:
    account, inputs, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    tick(account, inputs, sources, 5)
    run = _runs(account)[-1]
    table = pq.read_table(run / "state.parquet")
    rows = table.to_pylist()
    rows[0]["peak"] = Decimal(9000)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), run / "state.parquet")
    (run / "files.parquet").unlink()
    seal(run)
    with pytest.raises(ValueError, match="replay mismatch"):
        verify_forward(account)


def test_cash_mode_cannot_trade_or_accept_a_simulated_clock(tmp_path: Path) -> None:
    account, _, sources = setup(tmp_path, mode="cash_observation", candidate="cash")
    with pytest.raises(ValueError, match="explicit clock"):
        initialize(tmp_path, account, sources)
    body = (
        (tmp_path / "observation.toml")
        .read_text()
        .replace('candidate="cash"', 'candidate="trend-2"')
    )
    (tmp_path / "observation.toml").write_text(body)
    with pytest.raises(ValueError, match="Cash observation"):
        initialize(tmp_path, account, sources)


def test_failed_m2_candidate_cannot_enter_formal_observation(tmp_path: Path) -> None:
    from invest.forward import _qualify
    from invest.forward_config import parse_observation
    from invest.study_config import parse_study

    setup(tmp_path, mode="qualified_strategy")
    evidence = tmp_path / "study"
    evidence.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [{"m3_research_eligible": False, "scope": "historical_research_only"}]
        ),
        evidence / "manifest.parquet",
    )
    seal(evidence)
    staging = tmp_path / "qualification-test"
    staging.mkdir()
    with pytest.raises(ValueError, match="did not pass"):
        _qualify(
            evidence,
            staging,
            parse_study((tmp_path / "policy.toml").read_bytes()),
            parse_observation((tmp_path / "observation.toml").read_bytes()),
        )


def test_calendar_deadlines_cover_dst_holidays_and_half_days() -> None:
    assert next_session(date(2024, 3, 8))["open_at"] == datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    assert next_session(date(2024, 11, 1))["open_at"] == datetime(2024, 11, 4, 14, 30, tzinfo=UTC)
    assert next_session(date(2024, 7, 3))["date"] == date(2024, 7, 5)
    assert timestamp(date(2024, 7, 3)).hour == 17


def test_backup_head_and_cli_status_and_worker_drill_rejection(tmp_path: Path) -> None:
    account, _, sources = setup(tmp_path)
    initialize(tmp_path, account, sources)
    backup_forward(account, tmp_path / "backup")
    with pytest.raises(ValueError, match="expected journal head"):
        restore_forward(
            tmp_path / "backup",
            tmp_path / "restored",
            "wrong",
            "tester",
            "restore",
            at=timestamp(date(2024, 1, 5)),
        )
    assert main(["forward-status", "--account", str(account), "--at", "2024-01-05T22:00:00Z"]) == 0
    assert main(["forward-verify", "--account", str(account)]) == 0
    with pytest.raises(ValueError, match="network worker"):
        forward_job(account, tmp_path / "data", tmp_path / "issuer")
    with pytest.raises(ValueError, match="new path"):
        backup_forward(account, account / "backup")
    # A directory copy retains the logical account, it does not mint new capital.
    shutil.copytree(account, tmp_path / "copy")
    assert _load(tmp_path / "copy")[-1].cash == _load(account)[-1].cash
