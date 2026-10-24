import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.helpers import make_bars


def test_cli_analyzes_parquet_outside_checkout(tmp_path: Path) -> None:
    path = tmp_path / "prices.parquet"
    pq.write_table(
        pa.table(
            {
                "date": pa.array([date(2024, 1, 2), date(2024, 1, 3)], type=pa.date32()),
                "adjusted_close": [100.0, 110.0],
            }
        ),
        path,
    )
    result = subprocess.run(
        [sys.executable, "-m", "invest", "legacy", "analyze", str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["observations"] == 2
    assert summary["total_return"] == pytest.approx(0.1)
    assert summary["max_drawdown"] == 0
    assert not result.stderr


def test_corrupt_parquet_reports_error_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "prices.parquet"
    path.write_bytes(b"not parquet")
    result = subprocess.run(
        [sys.executable, "-m", "invest", "legacy", "analyze", str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not result.stdout
    assert result.stderr.startswith("invest: ")
    assert "Traceback" not in result.stderr


def test_paper_cli_restarts_without_duplicate_transactions(tmp_path: Path) -> None:
    path, config = tmp_path / "bars.parquet", tmp_path / "config.toml"
    pq.write_table(make_bars([100, 110, 120, 100, 90]), path)
    config.write_text("lookback = 2\n", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "invest",
        "legacy",
        "paper",
        "--data",
        str(path),
        "--config",
        str(config),
        "--account",
        str(tmp_path / "paper"),
    ]
    first = json.loads(
        subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    )
    second = json.loads(
        subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    )
    assert first["updated"] is True
    assert second["updated"] is False
    assert first["run_directory"] == second["run_directory"]
    report = Path(first["run_directory"])
    assert pq.read_table(report / "trades.parquet").num_rows > 0
    assert not list(report.rglob("*.csv"))
