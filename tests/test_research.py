import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import FetchSpec, RequestData, fetch_pages
from invest.cli import main
from invest.datasets import fetch_dataset
from invest.quality import regular_sessions
from invest.research import admit_inputs, eligibility, run_study, verify_study
from invest.research_registry import (
    LEGACY_REGISTRATION_SCHEMA,
    parse_mappings,
    read_registration,
    register_study,
)
from invest.storage import engine_digest
from invest.strategies import Candidate
from invest.study_config import parse_study
from tests.test_datasets import SPEC, provider
from tests.test_dividends import RECORD, source_capture
from tests.test_portfolio import bars


def experiment(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    body = Path("configs/m2.toml").read_text()
    replacements = {
        '["SPY", "XLF", "XLK"]': '["SPY", "XLF"]',
        "[40, 60, 80]": "[2, 3]",
        "correlation_window = 60": "correlation_window = 3",
        "rebalance_sessions = 21": "rebalance_sessions = 3",
        "2022-01-03": "2024-01-08",
        "2023-12-29": "2024-01-16",
        "2024-01-02": "2024-01-17",
        "2024-12-31": "2024-01-26",
        "2025-01-02": "2024-01-29",
        "2025-12-31": "2024-02-08",
        "2026-01-02": "2024-02-09",
        "2026-06-30": "2024-02-20",
        "[2023, 2024, 2025]": "[]",
    }
    for old, new in replacements.items():
        body = body.replace(old, new)
    config = tmp_path / "config.toml"
    config.write_text(body)
    registration = tmp_path / "registered.parquet"
    assert main(["research-register", "--config", str(config), "--output", str(registration)]) == 0
    sources = {}
    length = regular_sessions(date(2024, 1, 2), date(2024, 2, 20)).num_rows
    for symbol, offset in [("SPY", 0), ("XLF", 2)]:
        values = [100 + i // 2 + (i + offset) % 3 for i in range(length)]
        sources[symbol] = tmp_path / f"{symbol}.parquet"
        pq.write_table(bars(symbol, values), sources[symbol], compression="zstd")
    return registration, sources


def test_registry_rejects_changes_duplicates_and_bad_dates(tmp_path: Path) -> None:
    registration, _ = experiment(tmp_path)
    config, registered, digest = read_registration(registration)
    assert config.warmup == 4 and registered.tzinfo and len(digest) == 64
    with pytest.raises(FileExistsError):
        register_study(tmp_path / "config.toml", registration)
    table = pq.read_table(registration)
    rows = table.to_pylist()
    rows[0]["config_sha256"] = "bad"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), registration)
    with pytest.raises(ValueError, match="mismatch"):
        read_registration(registration)
    with pytest.raises(ValueError, match="Duplicate"):
        parse_mappings(["SPY=a", "SPY=b"])
    with pytest.raises(ValueError, match="SYMBOL"):
        parse_mappings(["../SPY=a"])
    with pytest.raises(ValueError, match="nonoverlapping"):
        parse_study((tmp_path / "config.toml").read_bytes().replace(b"2024-01-26", b"2026-01-26"))


def test_entire_study_is_reproducible_and_holdout_does_not_select(tmp_path: Path) -> None:
    registration, inputs = experiment(tmp_path)
    output = run_study(registration, inputs, tmp_path / "first", synthetic=True)
    count = verify_study(output)
    assert count == 32
    manifest = pq.read_table(output / "manifest.parquet").to_pylist()[0]
    assert manifest["scope"] == "synthetic_engineering_only"
    assert not manifest["m3_research_eligible"]
    comparison = pq.read_table(output / "comparison.parquet").to_pylist()
    holdout = [r for r in comparison if r["phase"] == "holdout" and r["lookback"]]
    assert len(holdout) == 1 and holdout[0]["candidate"] == manifest["selected_candidate"]
    selection = pq.read_table(output / "holdout-selection.parquet").to_pylist()[0]
    assert selection["selection_end"] < selection["evaluation_start"]
    assert b"M2" in (output / "report.html").read_bytes()
    # Change ONLY holdout prices dramatically: validation rankings must stay identical.
    for path in inputs.values():
        table = pq.read_table(path)
        rows = table.to_pylist()
        for row in rows:
            if row["date"] >= date(2024, 2, 9):
                for key in ["open", "high", "low", "close"]:
                    row[key] /= 2
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    second = run_study(registration, inputs, tmp_path / "second", synthetic=True)
    assert pq.read_table(output / "pre-holdout-results.parquet").equals(
        pq.read_table(second / "pre-holdout-results.parquet")
    )
    assert (
        pq.read_table(second / "manifest.parquet")["selected_candidate"][0].as_py()
        == manifest["selected_candidate"]
    )
    with pytest.raises(ValueError, match="already exists"):
        run_study(registration, inputs, output, synthetic=True)
    (output / "report.html").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        verify_study(output)


def test_failed_admission_retains_evidence(tmp_path: Path) -> None:
    registration, inputs = experiment(tmp_path)
    table = pq.read_table(inputs["XLF"])
    metadata = {**(table.schema.metadata or {}), b"source": b"unknown"}
    pq.write_table(table.replace_schema_metadata(metadata), inputs["XLF"])
    output = tmp_path / "failure"
    with pytest.raises(ValueError, match="qualified"):
        run_study(registration, inputs, output, synthetic=True)
    assert not output.exists()
    failed = list(tmp_path.glob("failure.failed-*"))
    assert len(failed) == 1 and (failed[0] / "failure.parquet").exists()
    reasons = pq.read_table(failed[0] / "admission.parquet").to_pylist()
    assert any(not r["admitted"] and "metadata" in r["reason"] for r in reasons)


@pytest.mark.parametrize(
    ("original", "invalid"),
    [
        (b"lookbacks = [40, 60, 80]", b"lookbacks = [1, 2]"),
        (b"cost_multipliers = [1, 2, 4]", b"cost_multipliers = [1, 2, 2]"),
        (b"correlation_limit = 0.95", b"correlation_limit = nan"),
        (b'initial_cash = "5000"', b'initial_cash = "bad"'),
        (b"holdout_start = 2026-01-02", b"holdout_start = 2025-12-31"),
        (b"walk_forward_years = [2023, 2024, 2025]", b"walk_forward_years = [2023, 2024, 2026]"),
    ],
)
def test_invalid_research_design_rejected(original: bytes, invalid: bytes) -> None:
    with pytest.raises(ValueError):
        parse_study(Path("configs/m2.toml").read_bytes().replace(original, invalid))


def test_changed_strategy_cannot_reuse_registration(tmp_path: Path) -> None:
    registration, inputs = experiment(tmp_path)
    registered = pq.read_table(registration).to_pylist()[0]
    assert registered["engine_sha256"] == engine_digest()
    variant = tmp_path / "changed-engine"
    shutil.copytree("src/invest", variant / "invest", ignore=shutil.ignore_patterns("__pycache__"))
    strategy = variant / "invest" / "strategies.py"
    original = strategy.read_text()
    changed = original.replace("scores[symbol] > 0", 'scores[symbol] > Decimal("0.05")')
    assert changed != original
    strategy.write_text(changed)
    output = tmp_path / "must-not-run"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "invest",
            "research",
            "--registration",
            str(registration),
            "--synthetic",
            "--input",
            f"SPY={inputs['SPY']}",
            "--input",
            f"XLF={inputs['XLF']}",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(variant)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "Registered engine mismatch" in result.stderr
    assert not output.exists()
    assert pq.read_table(registration).to_pylist()[0] == registered


def test_legacy_registration_is_readable_but_cannot_start_a_new_study(tmp_path: Path) -> None:
    registration, inputs = experiment(tmp_path)
    rows = pq.read_table(registration).to_pylist()
    legacy = tmp_path / "legacy.parquet"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=LEGACY_REGISTRATION_SCHEMA), legacy, compression="zstd"
    )
    original = legacy.read_bytes()
    assert read_registration(legacy) == read_registration(registration)
    with pytest.raises(ValueError, match="Legacy registration has no engine binding"):
        run_study(legacy, inputs, tmp_path / "new-study", synthetic=True)
    assert legacy.read_bytes() == original
    assert not (tmp_path / "new-study").exists()


def test_earliest_bar_page_controls_capture_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(parse_study(Path("configs/m2.toml").read_bytes()), symbols=("SPY", "XLF"))
    early = datetime.now(UTC) - timedelta(minutes=10)
    registered = early + timedelta(minutes=1)

    def timed_pages(spec: FetchSpec, request: RequestData) -> Iterator[dict[str, object]]:
        times = iter(
            [
                early if spec.symbol == "SPY" else registered + timedelta(minutes=1),
                registered + timedelta(minutes=2),
                registered + timedelta(minutes=3),
            ]
        )
        for page in fetch_pages(spec, request):
            yield {**page, "received_at": next(times)}

    get_demo = provider()

    def get(endpoint: str, query: dict[str, str]) -> bytes:
        return get_demo(endpoint, query).replace(b'"DEMO"', f'"{query["symbols"]}"'.encode())

    monkeypatch.setattr("invest.datasets.fetch_pages", timed_pages)
    datasets = {
        symbol: fetch_dataset(replace(SPEC, symbol=symbol), tmp_path / "data", get)
        for symbol in config.symbols
    }
    source = source_capture(tmp_path, [[RECORD[0], s, *RECORD[2:]] for s in config.symbols])
    staging = tmp_path / "admission"
    staging.mkdir()
    _, admission = admit_inputs(config, datasets, staging, source, synthetic=False)
    records = {r["symbol"]: r for r in admission.to_pylist()}
    assert records["SPY"]["first_bar_received_at"] == early
    assert all(r["observed_at"] > registered for r in records.values())
    # All performance gates pass: only capture ordering may disqualify this fixture.
    candidate = Candidate("rotation", 60)
    metrics = [
        {
            "phase": phase,
            "candidate": name,
            "cost_multiplier": 1,
            "gap_bps": 0,
            "total_return": 0.1 if name == candidate.name else 0.05,
            "status": "active",
            "max_drawdown": -0.05,
        }
        for phase in ["train", "validation", "holdout"]
        for name in [candidate.name, "equal_weight"]
    ]
    metrics.append({**metrics[0], "phase": "validation_cost", "cost_multiplier": 2})
    for cutoff, expected in [
        (early - timedelta(microseconds=1), True),
        (early, False),
        (registered, False),
    ]:
        gates = eligibility(metrics, candidate, config, False, admission, cutoff)
        assert gates["passed"][0].as_py() is expected
        assert all(gates["passed"].to_pylist()) is expected
    missing = admission.drop(["first_bar_received_at"])
    assert not eligibility(metrics, candidate, config, False, missing, early)["passed"][0].as_py()
    assert not eligibility(
        metrics, candidate, config, True, admission, early - timedelta(seconds=1)
    )["passed"][0].as_py()


def test_report_reads_frozen_capital_and_risk_parameters(tmp_path: Path) -> None:
    _, inputs = experiment(tmp_path)
    config_path = tmp_path / "config.toml"
    body = config_path.read_text().replace('initial_cash = "5000"', 'initial_cash = "10000"')
    body = body.replace('allocation = "0.8"', 'allocation = "0.6"')
    body = body.replace('position_cap = "0.4"', 'position_cap = "0.3"')
    config_path.write_text(body)
    registration = tmp_path / "custom.parquet"
    register_study(config_path, registration)
    # Later edits to the source TOML must not change the registered experiment or report.
    config_path.write_text(body.replace('initial_cash = "10000"', 'initial_cash = "9999"'))
    output = run_study(registration, inputs, tmp_path / "study", synthetic=True)
    report = (output / "report.html").read_text()
    assert "登记本金 10000 美元" in report
    assert "策略目标 60% 总敞口、30% 单仓" in report
    assert "基准的目标总敞口同为 60%" in report
    assert "80% 总敞口" not in report and "40% 单仓" not in report
    assert "9999 美元" not in report
