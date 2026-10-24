"""P4 公开研究入口：因子贡献、冻结策略和只读动作输出。"""

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def frozen_case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return decision_case(tmp_path_factory.mktemp("decision_case"))


def decision_case(root: Path) -> tuple[Path, Path]:
    from decimal import Decimal

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.backtest_study import run_backtest
    from invest.factor_mining import run_mining
    from invest.market import BAR_SCHEMA
    from tests.test_factor_mining import mining_config, research_snapshot

    snapshot = research_snapshot(root)
    run_mining(mining_config(root, snapshot), root / "mine", cache_root=root / "cache")
    days = snapshot.calendar["date"].to_pylist()
    mapping = []
    for instrument in snapshot.universe["instrument"].to_pylist():
        rows = [
            {
                "date": row["date"],
                "symbol": instrument,
                **{
                    name: row[name].quantize(Decimal(".000001"))
                    for name in ("open", "high", "low", "close")
                },
                "volume": int(row["volume"]),
                "split_ratio": 1,
                "dividend": Decimal(0),
                "dividend_pay_date": None,
            }
            for row in snapshot.bars.to_pylist()
            if row["instrument"] == instrument
        ]
        pq.write_table(
            pa.Table.from_pylist(
                rows,
                schema=BAR_SCHEMA.with_metadata(
                    {
                        **(BAR_SCHEMA.metadata or {}),
                        b"source": b"synthetic",
                    }
                ),
            ),
            root / f"{instrument}.parquet",
            compression="zstd",
        )
        mapping.append(f'{instrument} = "{instrument}.parquet"')
    path = root / "backtest.toml"
    path.write_text(f"""snapshot = "snapshot"
factor_pool = "mine/factor_pool.parquet"
start = {days[120]}
end = {days[125]}
known_through = {days[139]}
initial_cash = "5000"
[execution]
{chr(10).join(mapping)}
[policy]
top_k = 2
allocation = "0.8"
position_cap = "0.4"
""")
    study = run_backtest(path, root / "backtest", cache_root=root / "cache")
    config = root / "decide.toml"
    config.write_text(f"""strategy = "backtest"
snapshot = "backtest/inference"
context = "backtest/decision_contexts.parquet"
known_through = {days[139]}
""")
    return study.directory, config


def test_factor_contributions_explain_the_exact_signal_score(tmp_path: Path) -> None:
    from invest.signals import evaluate_signals, freeze_factor_pool
    from tests.test_factor_mining import research_snapshot

    data = research_snapshot(tmp_path)
    day = data.calendar["date"][119].as_py()
    pool = freeze_factor_pool(
        [
            {
                "factor": "price",
                "expression": "$close",
                "direction": 1,
                "weight": 0.5,
                "trial_id": 0,
            },
            {
                "factor": "inverse",
                "expression": "0-$close",
                "direction": -1,
                "weight": 0.5,
                "trial_id": 1,
            },
        ],
        {
            "snapshot_id": data.snapshot_id,
            "source": "synthetic",
            "price_basis": "raw",
            "scope": "synthetic",
            "volume_unit": "shares",
            "currency": "USD",
            "knowledge_through": day.isoformat(),
            "horizon": "3",
            "run_id": "test_run",
        },
    )
    result = evaluate_signals(pool, data, day, day, cache_root=tmp_path / "cache")
    rows = result.contributions.to_pylist()
    strongest = [row for row in rows if row["instrument"] == "SYNTH8"]
    assert [row["contribution"] for row in strongest] == [0.5, 0.5]
    assert [row["scaled_rank"] for row in strongest] == [1.0, -1.0]
    for signal in result.signals.table.to_pylist():
        assert signal["score"] == pytest.approx(
            sum(row["contribution"] for row in rows if row["instrument"] == signal["instrument"])
        )
    assert result.factors.table.num_rows == 16


def test_current_plan_matches_backtest_and_replays_without_account_writes(
    tmp_path: Path, frozen_case: tuple[Path, Path]
) -> None:
    import pyarrow.parquet as pq

    from invest.decision_study import run_decision, verify_decision
    from invest.research_data import digest

    study, config = frozen_case
    historical = pq.read_table(study / "actions.parquet").to_pylist()
    day = min(row["date"] for row in historical)
    before = {str(path): digest(path) for path in study.parent.rglob("*") if path.is_file()}
    result = run_decision(config, tmp_path / "decision", day, cache_root=tmp_path / "cache")
    assert result.status == "completed"
    actions = pq.read_table(result.directory / "actions.parquet").to_pylist()
    assert actions == [row for row in historical if row["date"] == day]
    rankings = pq.read_table(result.directory / "rankings.parquet").to_pylist()
    assert len(rankings) == 8
    assert sum(row["selected"] for row in rankings) == 2
    assert all(row["evidence_status"] == "research_only" for row in rankings)
    assert all(row["price_type"] == "next_session_open" for row in actions)
    assert all(row["max_holding_sessions"] == 60 for row in actions)
    for directory in (study, result.directory, study.parent / "mine"):
        report = (directory / "report.html").read_text()
        assert "研究用途" in report and "Parquet" in report
        assert '<html lang="zh-CN"' in report
    assert not (result.directory / "orders.parquet").exists()
    assert not (result.directory / "fills.parquet").exists()
    assert verify_decision(result.directory, cache_root=tmp_path / "cache")["status"] == "verified"
    assert all(digest(Path(path)) == expected for path, expected in before.items())
    with pytest.raises(FileExistsError):
        run_decision(config, result.directory, day, cache_root=tmp_path / "cache")


def test_decision_cli_outputs_parseable_json_and_preserves_pending_risk(
    tmp_path: Path, frozen_case: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    import json
    from dataclasses import replace

    import pyarrow.parquet as pq

    from invest.cli import main
    from invest.contracts import PendingOrder
    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.research_data import digest

    study, _ = frozen_case
    table = pq.read_table(study / "decision_contexts.parquet")
    account, state = next((a, s) for a, s in read_decision_contexts(table) if a.holdings)
    holding = account.holdings[0]
    quote = next(q for q in account.quotes if q.instrument == holding.instrument)
    account = replace(
        account,
        operations="paused",
        pending=(
            PendingOrder(
                holding.instrument,
                "buy",
                1,
                quote.close,
            ),
        ),
    )
    state = replace(state, risk_status="halted")
    context = tmp_path / "context.parquet"
    pq.write_table(
        decision_contexts(((account, state),)).replace_schema_metadata(table.schema.metadata),
        context,
        compression="zstd",
    )
    config = tmp_path / "decide.toml"
    config.write_text(f'''strategy = "{study}"
snapshot = "{study / "inference"}"
context = "context.parquet"
known_through = {account.as_of}
''')
    before = digest(context)
    capsys.readouterr()
    output = tmp_path / "decision"
    assert (
        main(
            [
                "decide",
                "--config",
                str(config),
                "--output",
                str(output),
                "--as-of",
                str(account.as_of),
            ]
        )
        == 0
    )
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "completed" and response["report"] == str(output / "report.html")
    actions = pq.read_table(output / "actions.parquet").to_pylist()
    assert all(row["quantity"] == 0 for row in actions)
    blocked = next(row for row in actions if row["instrument"] == holding.instrument)
    assert blocked["action"] == "WAIT" and blocked["cancel_pending"]
    assert blocked["exit_reason"] == "halted"
    restored, proposed = read_decision_contexts(pq.read_table(output / "proposed_context.parquet"))[
        0
    ]
    assert (
        restored.account_id == account.account_id and restored.initial_cash == account.initial_cash
    )
    assert restored.pending == account.pending and proposed.risk_status == "halted"
    assert digest(context) == before


def test_stale_data_produces_visible_waits_and_no_false_plan(
    tmp_path: Path, frozen_case: tuple[Path, Path]
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.decision_study import run_decision, verify_decision
    from invest.research_data import create_snapshot, load_snapshot

    study, _ = frozen_case
    source = load_snapshot(study / "inference")
    table = pq.read_table(study / "decision_contexts.parquet")
    account, state = next((a, s) for a, s in read_decision_contexts(table) if a.holdings)
    rows = source.bars.to_pylist()
    for row in rows:
        if row["date"] == account.as_of:
            row["available_at"] += timedelta(seconds=1)
    late = create_snapshot(
        pa.Table.from_pylist(rows, schema=source.bars.schema),
        source.universe,
        tmp_path / "late",
        source.spec,
    )
    account = replace(account, snapshot_id=late.snapshot_id)
    pq.write_table(
        decision_contexts(((account, state),)).replace_schema_metadata(table.schema.metadata),
        tmp_path / "context.parquet",
        compression="zstd",
    )
    config = tmp_path / "decide.toml"
    config.write_text(f'''strategy = "{study}"
snapshot = "late"
context = "context.parquet"
known_through = {account.as_of}
''')
    result = run_decision(
        config, tmp_path / "decision", account.as_of, cache_root=tmp_path / "cache"
    )
    assert result.status == "insufficient_evidence"
    actions = pq.read_table(result.directory / "actions.parquet").to_pylist()
    assert all(row["action"] == "WAIT" and row["quantity"] == 0 for row in actions)
    assert all(
        row["coverage"] == 0
        for row in pq.read_table(result.directory / "rankings.parquet").to_pylist()
    )
    assert verify_decision(result.directory, cache_root=tmp_path / "cache")["status"] == "verified"


def test_input_history_cannot_be_used_as_decision_output_or_cache(
    tmp_path: Path, frozen_case: tuple[Path, Path]
) -> None:
    import pyarrow.parquet as pq

    from invest.decision_study import run_decision

    study, config = frozen_case
    day = pq.read_table(study / "decision_contexts.parquet")["date"][0].as_py()
    with pytest.raises(ValueError, match="historical"):
        run_decision(config, study / "new_decision", day, cache_root=tmp_path / "cache")
    with pytest.raises(ValueError, match="historical"):
        run_decision(config, tmp_path / "decision", day, cache_root=study / "cache")
    assert not (study / "new_decision").exists() and not (study / "cache").exists()
    assert not (tmp_path / "decision").exists()


def test_display_changes_keep_financial_version_but_strategy_changes_do_not(tmp_path: Path) -> None:
    import json
    import os
    import shutil
    import subprocess
    import sys

    from invest.engine import engine_digest, research_engine_digest

    variant = tmp_path / "changed-engine"
    package = variant / "invest"
    shutil.copytree("src/invest", package, ignore=shutil.ignore_patterns("__pycache__"))
    initial = {"source": engine_digest(), "financial": research_engine_digest()}
    driver = (
        "import json; from invest.engine import engine_digest, research_engine_digest; "
        "print(json.dumps({'source': engine_digest(), 'financial': research_engine_digest()}))"
    )
    report = package / "quant_report.py"
    report.write_text(report.read_text() + "\n# 展示修改不改变金融规则。\n")
    result = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(variant)},
        text=True,
        capture_output=True,
        check=True,
    )
    changed = json.loads(result.stdout)
    assert changed["source"] != initial["source"]
    assert changed["financial"] == initial["financial"]
    strategy = package / "strategies.py"
    strategy.write_text(strategy.read_text().replace('Decimal("0.08")', 'Decimal("0.09")'))
    result = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(variant)},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout)["financial"] != initial["financial"]


@pytest.mark.parametrize("invalid", ["policy", "source", "price", "cutoff", "duplicate"])
def test_decision_rejects_mismatched_account_inputs_before_writing(
    tmp_path: Path, frozen_case: tuple[Path, Path], invalid: str
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.decision_study import run_decision

    study, _ = frozen_case
    original = pq.read_table(study / "decision_contexts.parquet")
    account, state = read_decision_contexts(original)[0]
    day = account.as_of
    metadata = dict(original.schema.metadata or {})
    if invalid == "policy":
        metadata[b"policy_id"] = b"unrelated_policy"
    elif invalid == "source":
        account = replace(account, source="ibkr")
    elif invalid == "price":
        account = replace(
            account,
            quotes=(
                replace(account.quotes[0], close=account.quotes[0].close + 1),
                *account.quotes[1:],
            ),
        )
    elif invalid == "cutoff":
        day -= timedelta(days=1)
    table = decision_contexts(((account, state),)).replace_schema_metadata(metadata)
    if invalid == "duplicate":
        table = pa.concat_tables([table, table])
    pq.write_table(table, tmp_path / "context.parquet", compression="zstd")
    config = tmp_path / "decide.toml"
    config.write_text(f'''strategy = "{study}"
snapshot = "{study / "inference"}"
context = "context.parquet"
known_through = {day}
''')
    with pytest.raises(ValueError):
        run_decision(config, tmp_path / "decision", day, cache_root=tmp_path / "cache")
    assert not (tmp_path / "decision").exists()


def test_future_data_gaps_keep_past_actions_and_origin_limitations(
    tmp_path: Path, frozen_case: tuple[Path, Path]
) -> None:
    from dataclasses import replace

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.decision_io import decision_contexts, read_decision_contexts
    from invest.decision_study import run_decision, verify_decision
    from invest.research_data import create_snapshot, load_snapshot

    study, _ = frozen_case
    snapshot = load_snapshot(study / "inference")
    context = pq.read_table(study / "decision_contexts.parquet")
    account, state = read_decision_contexts(context)[0]
    rows = snapshot.bars.to_pylist()
    for row in rows:
        if row["date"] > account.as_of:
            row["available_at"] = None
    changed = create_snapshot(
        pa.Table.from_pylist(rows, schema=snapshot.bars.schema),
        snapshot.universe,
        tmp_path / "future",
        snapshot.spec,
        allow_exploratory=True,
    )
    account = replace(
        account, snapshot_id=changed.snapshot_id, account_id='<script>alert("x")</script>'
    )
    pq.write_table(
        decision_contexts(((account, state),)).replace_schema_metadata(context.schema.metadata),
        tmp_path / "context.parquet",
        compression="zstd",
    )
    config = tmp_path / "decide.toml"
    config.write_text(f'''strategy = "{study}"
snapshot = "future"
context = "context.parquet"
known_through = 2020-01-01
''')
    result = run_decision(
        config, tmp_path / "decision", account.as_of, cache_root=tmp_path / "cache"
    )
    actual = pq.read_table(result.directory / "actions.parquet")
    expected = pq.read_table(study / "actions.parquet")
    columns = [name for name in actual.column_names if name != "action_id"]
    assert actual.select(columns).to_pylist() == [
        row for row in expected.select(columns).to_pylist() if row["date"] == account.as_of
    ]
    record = pq.read_table(result.directory / "run.parquet").to_pylist()[0]
    origin = pq.read_table(study / "run.parquet").to_pylist()[0]
    assert record["known_through"] == max(origin["known_through"], origin["consumed_through"])
    assert "historical_availability_unknown" in record["source_limitations"]
    assert record["scope"] == "synthetic" and record["account_eligible"] is False
    report = (result.directory / "report.html").read_text()
    assert "<script>alert" not in report and "&lt;script&gt;" in report
    assert verify_decision(result.directory, cache_root=tmp_path / "cache")["status"] == "verified"
    (result.directory / "report.html").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        verify_decision(result.directory, cache_root=tmp_path / "cache")


def test_strategy_replacement_during_freezing_is_rejected(
    tmp_path: Path, frozen_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    from typing import Any

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.decision_study import run_decision
    from invest.research_artifacts import seal_artifacts

    study, config = frozen_case
    alternate = tmp_path / "alternate"
    shutil.copytree(study, alternate)
    table = pq.read_table(alternate / "run.parquet")
    record = table.to_pylist()[0]
    record["run_id"] = "different_research_run"
    pq.write_table(
        pa.Table.from_pylist([record], schema=table.schema),
        alternate / "run.parquet",
        compression="zstd",
    )
    seal_artifacts(alternate)
    original_copy = shutil.copytree

    def changed_copy(source: Any, target: Any, *args: Any, **kwargs: Any) -> str:
        # 模拟文件复制边界上原目录被替换；不改动原始研究或账户。
        return str(
            original_copy(alternate if Path(source) == study else source, target, *args, **kwargs)
        )

    monkeypatch.setattr(shutil, "copytree", changed_copy)
    day = pq.read_table(study / "decision_contexts.parquet")["date"][0].as_py()
    with pytest.raises(ValueError, match="inputs changed"):
        run_decision(config, tmp_path / "decision", day, cache_root=tmp_path / "cache")
    failed = pq.read_table(tmp_path / "decision" / "run.parquet").to_pylist()[0]
    assert failed["status"] == "failed"
    assert not (tmp_path / "decision" / "actions.parquet").exists()


@pytest.mark.parametrize(
    "filename", ["run.parquet", "registration.parquet", "config.toml", "artifacts.parquet"]
)
def test_mining_input_changes_during_backtest_freezing_are_rejected(
    tmp_path: Path, frozen_case: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    import shutil
    from typing import Any

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.backtest_study import run_backtest
    from invest.research_data import digest

    study, _ = frozen_case
    source_file = study.parent / "mine" / filename
    before = digest(source_file)
    original_copy = shutil.copy2

    def changed_copy(source: Any, target: Any, *args: Any, **kwargs: Any) -> str:
        copied = original_copy(source, target, *args, **kwargs)
        if Path(source) == source_file:
            target = Path(target)
            if filename == "config.toml":
                target.write_text(target.read_text() + "\n# 复制边界中的配置变化。\n")
            else:
                table = pq.read_table(target)
                rows = table.to_pylist()
                if filename == "artifacts.parquet":
                    rows[0]["sha256"] = "0" * 64
                else:
                    rows[0]["run_id"] = "different_mining_run"
                pq.write_table(
                    pa.Table.from_pylist(rows, schema=table.schema), target, compression="zstd"
                )
        return str(copied)

    monkeypatch.setattr(shutil, "copy2", changed_copy)
    output = tmp_path / "backtest"
    with pytest.raises(ValueError, match="mining|freezing"):
        run_backtest(study.parent / "backtest.toml", output, cache_root=tmp_path / "cache")
    assert digest(source_file) == before
    assert pq.read_table(output / "run.parquet")["status"].to_pylist() == ["failed"]
    assert not (output / "actions.parquet").exists()


@pytest.mark.parametrize("reseal_mining", [False, True])
def test_backtest_replay_revalidates_the_registered_mining_source(
    tmp_path: Path, frozen_case: tuple[Path, Path], reseal_mining: bool
) -> None:
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    from invest.backtest_study import read_backtest, verify_backtest
    from invest.research_artifacts import seal_artifacts
    from invest.research_data import digest

    study, _ = frozen_case
    copied = tmp_path / "backtest"
    shutil.copytree(study, copied)
    path = copied / "mining" / "run.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["run_id"] = "different_mining_run"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path, compression="zstd")
    if reseal_mining:
        manifest_path = copied / "mining" / "artifacts.parquet"
        manifest = pq.read_table(manifest_path)
        entries = manifest.to_pylist()
        for entry in entries:
            if entry["path"] == "run.parquet":
                entry["sha256"] = digest(path)
        pq.write_table(
            pa.Table.from_pylist(entries, schema=manifest.schema), manifest_path, compression="zstd"
        )
    # 外层目录清单自洽也不能覆盖最初登记的来源绑定。
    seal_artifacts(copied)
    with pytest.raises(ValueError, match="mining"):
        read_backtest(copied)
    with pytest.raises(ValueError, match="mining"):
        verify_backtest(copied, cache_root=tmp_path / "cache")
