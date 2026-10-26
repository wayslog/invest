"""研究导入不改旧批次，真实来源和有限覆盖随冻结结果重放。"""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from invest.alpaca import RAW_SCHEMA
from invest.alpaca_research import (
    freeze_execution_evidence,
    import_alpaca_research,
    validate_alpaca_execution,
)
from invest.backtest_study import execution_inputs
from invest.datasets import fetch_dataset
from invest.research_data import load_snapshot
from tests.test_datasets import SPEC, provider
from tests.test_dividends import RECORD, source_capture


def inputs(root: Path) -> tuple[Path, Path, Path]:
    dataset = fetch_dataset(SPEC, root / "datasets", provider())
    issuer = source_capture(root, [RECORD])
    pages = []
    for row in pq.read_table(dataset / "raw.parquet").to_pylist():
        if row["kind"] == "bars":
            query = json.loads(row["query"])
            query["adjustment"] = "split"
            pages.append({**row, "kind": "split_reference", "query": json.dumps(query)})
    reference = root / "split.parquet"
    pq.write_table(pa.Table.from_pylist(pages, schema=RAW_SCHEMA), reference, compression="zstd")
    return dataset, issuer, reference


def test_import_preserves_source_unknown_timing_and_frozen_evidence(tmp_path: Path) -> None:
    dataset, issuer, reference = inputs(tmp_path)
    before = {p: p.read_bytes() for p in dataset.iterdir()}
    output = tmp_path / "imported"
    snapshot = import_alpaca_research(
        {"DEMO": dataset}, issuer, reference, output, allow_exploratory=True
    )
    assert snapshot.spec.source == "alpaca" and snapshot.scope == "exploratory"
    assert snapshot.bars["available_at"].null_count == snapshot.bars.num_rows
    assert snapshot.universe["available_at"].null_count == 1
    assert load_snapshot(snapshot.directory).snapshot_id == snapshot.snapshot_id
    path = output / "execution" / "DEMO.parquet"
    table = pq.read_table(path)
    assert table.schema.metadata[b"corporate_actions"] == b"bounded_research"
    assert table.schema.metadata[b"currency_basis"] == b"project_usd_convention"
    days = snapshot.calendar["date"].to_pylist()
    admitted = execution_inputs(snapshot, {"DEMO": path}, days[1], days[-1])["DEMO"]
    assert admitted["dividend"].to_pylist()[3] == 1
    assert before == {p: p.read_bytes() for p in dataset.iterdir()}
    frozen = tmp_path / "frozen" / "DEMO.parquet"
    frozen.parent.mkdir()
    frozen.write_bytes(path.read_bytes())
    freeze_execution_evidence(path, frozen)
    dataset.rename(tmp_path / "moved-original")
    validate_alpaca_execution(frozen, pq.read_table(frozen))
    with pytest.raises(FileExistsError):
        import_alpaca_research(
            {"DEMO": tmp_path / "moved-original"},
            issuer,
            reference,
            output,
            allow_exploratory=True,
        )


def test_import_requires_exploratory_scope_and_cannot_write_into_input(tmp_path: Path) -> None:
    dataset, issuer, reference = inputs(tmp_path)
    with pytest.raises(ValueError, match="exploratory"):
        import_alpaca_research({"DEMO": dataset}, issuer, reference, tmp_path / "denied")
    assert not (tmp_path / "denied").exists()
    with pytest.raises(ValueError, match="historical input"):
        import_alpaca_research(
            {"DEMO": dataset}, issuer, reference, dataset / "nested", allow_exploratory=True
        )


@pytest.mark.parametrize(
    "problem", ["missing_page", "price", "volume", "dividend_adjusted", "hash"]
)
def test_split_evidence_must_cover_and_match_raw_prices(tmp_path: Path, problem: str) -> None:
    dataset, issuer, reference = inputs(tmp_path)
    rows = pq.read_table(reference).to_pylist()
    if problem == "missing_page":
        rows = rows[:1]
    elif problem == "dividend_adjusted":
        query = json.loads(rows[0]["query"])
        query["adjustment"] = "all"
        rows[0]["query"] = json.dumps(query)
    elif problem == "hash":
        rows[0]["sha256"] = "0" * 64
    else:
        body = json.loads(rows[0]["body"])
        body["bars"]["DEMO"][0]["c" if problem == "price" else "v"] = 1
        rows[0]["body"] = json.dumps(body).encode()
        rows[0]["sha256"] = hashlib.sha256(rows[0]["body"]).hexdigest()
    pq.write_table(pa.Table.from_pylist(rows, schema=RAW_SCHEMA), reference, compression="zstd")
    with pytest.raises(ValueError):
        import_alpaca_research(
            {"DEMO": dataset}, issuer, reference, tmp_path / "failed", allow_exploratory=True
        )
    assert not (tmp_path / "failed" / "snapshot").exists()


@pytest.mark.parametrize("problem", ["issuer", "execution", "metadata", "evidence"])
def test_frozen_alpaca_execution_cannot_change_events_or_claim_complete(
    tmp_path: Path, problem: str
) -> None:
    dataset, issuer, reference = inputs(tmp_path)
    output = tmp_path / "imported"
    if problem == "issuer":
        record = RECORD.copy()
        record[6] = "2"
        source_capture(tmp_path, [record])
        with pytest.raises(ValueError, match="Issuer dividends"):
            import_alpaca_research(
                {"DEMO": dataset}, issuer, reference, output, allow_exploratory=True
            )
        return
    import_alpaca_research({"DEMO": dataset}, issuer, reference, output, allow_exploratory=True)
    path = output / "execution" / "DEMO.parquet"
    table = pq.read_table(path)
    if problem == "execution":
        rows = table.to_pylist()
        rows[3]["dividend"] = 0
        table = pa.Table.from_pylist(rows, schema=table.schema)
    elif problem == "metadata":
        table = table.replace_schema_metadata(
            {**table.schema.metadata, b"corporate_actions": b"complete"}
        )
    else:
        (path.with_suffix(".evidence") / "issuer.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError):
        validate_alpaca_execution(path, table)


def test_import_cli_uses_offline_evidence_and_refuses_duplicate_symbols(tmp_path: Path) -> None:
    from invest.cli import main

    dataset, issuer, reference = inputs(tmp_path)
    arguments = [
        "import-alpaca",
        "--dataset",
        f"DEMO={dataset}",
        "--issuer",
        str(issuer),
        "--split-reference",
        str(reference),
        "--output",
        str(tmp_path / "imported"),
        "--allow-exploratory",
    ]
    assert main(arguments) == 0
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--dataset", f"DEMO={dataset}"])
    assert error.value.code == 2
