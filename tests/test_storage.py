from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from filelock import FileLock

from invest.storage import update_paper
from tests.helpers import BASE, make_bars


def test_repeated_updates_do_not_duplicate_and_match_full_replay(tmp_path: Path) -> None:
    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    bars = make_bars([100, 110, 120, 100, 95])
    pq.write_table(bars.slice(0, 3), data)
    first = update_paper(data, account, BASE)
    repeated = update_paper(data, account, BASE)
    assert not repeated.updated
    assert repeated.directory == first.directory
    pq.write_table(bars, data)
    second = update_paper(data, account, BASE)
    fresh = update_paper(data, tmp_path / "fresh", BASE)
    assert second.updated
    assert len(list((account / "runs").iterdir())) == 2
    for name in ["equity", "trades", "events", "metrics", "benchmark_trades"]:
        assert pq.read_table(second.directory / f"{name}.parquet").equals(
            pq.read_table(fresh.directory / f"{name}.parquet")
        )
    assert (second.directory / "report.html").is_file()
    assert (second.directory / "equity.png").stat().st_size > 1000


def test_history_and_parameters_cannot_be_rewritten(tmp_path: Path) -> None:
    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    bars = make_bars([100, 110, 120])
    pq.write_table(bars, data)
    first = update_paper(data, account, BASE)
    original_pointer = (account / "CURRENT").read_bytes()
    with pytest.raises(ValueError, match="parameters changed"):
        update_paper(data, account, replace(BASE, commission=Decimal("1")))
    pq.write_table(make_bars([101, 110, 120]), data)
    with pytest.raises(ValueError, match="history was changed"):
        update_paper(data, account, BASE)
    pq.write_table(bars.slice(0, 2), data)
    with pytest.raises(ValueError, match="truncated"):
        update_paper(data, account, BASE)
    assert (account / "CURRENT").read_bytes() == original_pointer
    assert first.directory.is_dir()


def test_report_failure_preserves_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    bars = make_bars([100, 110, 120])
    pq.write_table(bars.slice(0, 2), data)
    update_paper(data, account, BASE)
    pointer = (account / "CURRENT").read_bytes()
    pq.write_table(bars, data)

    def fail(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("invest.storage.write_report", fail)
    with pytest.raises(OSError, match="disk full"):
        update_paper(data, account, BASE)
    assert (account / "CURRENT").read_bytes() == pointer
    assert len(list((account / "runs").iterdir())) == 1


def test_account_lock_prevents_concurrent_updates(tmp_path: Path) -> None:
    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    pq.write_table(make_bars([100, 110]), data)
    account.mkdir()
    with FileLock(account / ".lock"), pytest.raises(ValueError, match="Another process"):
        update_paper(data, account, BASE)


def test_changed_engine_needs_new_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    pq.write_table(make_bars([100, 110]), data)
    update_paper(data, account, BASE)
    monkeypatch.setattr("invest.storage.engine_digest", lambda: "new-implementation")
    with pytest.raises(ValueError, match="implementation changed"):
        update_paper(data, account, BASE)


def test_reconciliation_failure_preserves_current_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from invest.paper import PaperResult, simulate

    data, account = tmp_path / "bars.parquet", tmp_path / "account"
    bars = make_bars([100, 110, 120, 121])
    pq.write_table(bars.slice(0, 3), data)
    update_paper(data, account, BASE)
    pointer = (account / "CURRENT").read_bytes()
    pq.write_table(bars, data)

    def corrupted(*args: object) -> PaperResult:
        result = simulate(bars, BASE)
        return replace(result, trades=result.trades.slice(0, 0))

    monkeypatch.setattr("invest.storage.simulate", corrupted)
    with pytest.raises(ValueError, match="reconciliation failed"):
        update_paper(data, account, BASE)
    assert (account / "CURRENT").read_bytes() == pointer
