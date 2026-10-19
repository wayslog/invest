import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_cli_analyzes_csv_from_another_directory(tmp_path: Path) -> None:
    csv = tmp_path / "prices.csv"
    csv.write_text("date,adjusted_close\n2024-01-02,100\n2024-01-03,110\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "invest", "analyze", str(csv)],
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


@pytest.mark.parametrize("contents", [None, "date,adjusted_close\n2024-01-02,100\n"])
def test_cli_reports_bad_inputs_without_tracebacks(tmp_path: Path, contents: str | None) -> None:
    csv = tmp_path / "prices.csv"
    if contents is not None:
        csv.write_text(contents, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "invest", "analyze", str(csv)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not result.stdout
    assert result.stderr.startswith("invest: ")
    assert "Traceback" not in result.stderr
