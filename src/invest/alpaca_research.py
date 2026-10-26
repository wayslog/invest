"""Alpaca 历史研究入口：冻结原始证据，核对现金分红及拆股口径。"""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import NEW_YORK, RAW_SCHEMA, decode
from invest.contracts import RESEARCH_BARS, UNIVERSE, DataSnapshot, SnapshotSpec, research_schema
from invest.datasets import verify_dataset
from invest.dividends import audit_dividends
from invest.research_artifacts import protect_inputs, seal_artifacts, verify_artifacts
from invest.research_data import create_snapshot, digest

COVERAGE_SCHEMA = research_schema(
    "alpaca_coverage",
    [
        ("symbol", pa.string()),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("dataset_id", pa.string()),
        ("bar_count", pa.int64()),
        ("dividend_count", pa.int64()),
        ("split_count", pa.int64()),
        ("coverage", pa.string()),
        ("limitations", pa.list_(pa.field("element", pa.string()))),
    ],
)
LIMITATIONS = [
    "provider_reported_actions_not_independent_all_event_completeness",
    "corporate_action_publication_and_revision_history_unknown",
    "fixed_symbol_sample_not_historical_stock_universe",
    "price_return_labels_exclude_cash_distributions",
]


def _split_reference(path: Path, symbol: str) -> dict[Any, dict[str, Any]]:
    """重放完整分页；保留实际采集时刻，不将空拆股响应当作无事件证明。"""
    table = pq.read_table(path)
    if not table.schema.equals(RAW_SCHEMA, check_metadata=True) or not table.num_rows:
        raise ValueError("Invalid split reference capture")
    expected: dict[str, Any] | None = None
    seen: set[str] = set()
    rows: dict[Any, dict[str, Any]] = {}
    for index, captured in enumerate(table.to_pylist()):
        query = json.loads(captured["query"])
        if (
            captured["kind"] != "split_reference"
            or captured["endpoint"] != "/v2/stocks/bars"
            or query.get("adjustment") != "split"
            or query.get("feed") != "sip"
            or query.get("timeframe") != "1Day"
            or symbol not in query.get("symbols", "").split(",")
            or (index == 0 and "page_token" in query)
            or (index > 0 and query != expected)
            or hashlib.sha256(captured["body"]).hexdigest() != captured["sha256"]
            or captured["received_at"] is None
            or captured["received_at"] > datetime.now(UTC)
        ):
            raise ValueError("Split reference identity, pagination or capture changed")
        page = decode(captured["body"])
        token = page["next_page_token"]
        if token is None:
            if index != table.num_rows - 1:
                raise ValueError("Unexpected split reference page after completion")
        elif not isinstance(token, str) or not token or token in seen:
            raise ValueError("Invalid split reference pagination")
        else:
            seen.add(token)
        expected = {**query, "page_token": token} if token else None
        for value in page["bars"].get(symbol, []):
            stamp = datetime.fromisoformat(value["t"]).astimezone(NEW_YORK)
            if stamp.hour or stamp.minute or stamp.second or stamp.date() in rows:
                raise ValueError("Invalid split reference session")
            rows[stamp.date()] = value
    if expected is not None:
        raise ValueError("Incomplete split reference pagination")
    return rows


def _validated_inputs(evidence: Path) -> tuple[pa.Table, dict[str, Any], pa.Table]:
    dataset = evidence / "dataset"
    bars = verify_dataset(dataset)
    manifest = pq.read_table(dataset / "manifest.parquet").to_pylist()[0]
    if manifest["feed"] != "sip":
        raise ValueError("Alpaca research requires an explicit SIP capture")
    audit = audit_dividends(dataset, evidence / "issuer.parquet")
    if audit.errors:
        raise ValueError("Issuer dividends disagree with Alpaca cash events")
    reference = _split_reference(evidence / "split-reference.parquet", manifest["symbol"])
    if set(reference) != set(bars["date"].to_pylist()):
        raise ValueError("Split reference must cover every raw session")
    splits = []
    for page in pq.read_table(dataset / "raw.parquet").to_pylist():
        if page["kind"] == "actions":
            splits.extend(decode(page["body"])["corporate_actions"].get("forward_splits", []))
    cutoff = min(
        row["received_at"].astimezone(NEW_YORK).date()
        for row in pq.read_table(evidence / "split-reference.parquet").to_pylist()
    )
    for row in bars.to_pylist():
        ratio = Decimal(1)
        for event in splits:
            if row["date"].isoformat() < event["ex_date"] <= cutoff.isoformat():
                ratio *= Decimal(str(event["new_rate"])) / Decimal(str(event["old_rate"]))
        adjusted = reference[row["date"]]
        # 调整价可能按美分舍入；研究与会计仍直接使用原始价格，绝不反算原价。
        tolerance = Decimal(".005") if ratio != 1 else Decimal(0)
        if any(
            abs(row[name] / ratio - Decimal(str(adjusted[key]))) > tolerance
            for name, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
        ) or Decimal(row["volume"]) * ratio != Decimal(str(adjusted["v"])):
            raise ValueError("Split-adjusted prices or share volume disagree with action history")
    coverage = pa.Table.from_pylist(
        [
            {
                "symbol": manifest["symbol"],
                "start": manifest["start"],
                "end": manifest["end"],
                "dataset_id": manifest["dataset_id"],
                "bar_count": bars.num_rows,
                "dividend_count": sum(value > 0 for value in bars["dividend"].to_pylist()),
                "split_count": sum(value > 1 for value in bars["split_ratio"].to_pylist()),
                "coverage": "bounded_research",
                "limitations": LIMITATIONS,
            }
        ],
        schema=COVERAGE_SCHEMA,
    )
    return bars, manifest, coverage


def validate_alpaca_execution(path: Path, table: pa.Table) -> None:
    """冻结回测也重新验证随附证据，不依赖可手填的 complete 标记或旧绝对路径。"""
    evidence = path.with_suffix(".evidence")
    verify_artifacts(evidence)
    expected, manifest, coverage = _validated_inputs(evidence)
    metadata = table.schema.metadata or {}
    required = {
        b"source": b"alpaca",
        b"feed": b"sip",
        b"volume_unit": b"shares",
        b"currency_basis": b"project_usd_convention",
        b"corporate_actions": b"bounded_research",
        b"dataset_id": manifest["dataset_id"].encode(),
        b"evidence_sha256": digest(evidence / "artifacts.parquet").encode(),
    }
    if any(metadata.get(k) != v for k, v in required.items()):
        raise ValueError("Alpaca execution requires its verified research evidence")
    if not coverage.equals(pq.read_table(evidence / "coverage.parquet"), check_metadata=True):
        raise ValueError("Corporate-action coverage evidence changed")
    lookup = {row["date"]: row for row in expected.to_pylist()}
    if any(lookup.get(row["date"]) != row for row in table.to_pylist()):
        raise ValueError("Alpaca execution differs from its captured raw data and events")


def freeze_execution_evidence(source: Path, destination: Path) -> None:
    """同一输入证据随研究冻结，保证结果脱离原采集路径仍可重放。"""
    if (pq.read_schema(source).metadata or {}).get(b"source") == b"alpaca":
        shutil.copytree(source.with_suffix(".evidence"), destination.with_suffix(".evidence"))


def import_alpaca_research(
    datasets: dict[str, Path],
    issuer: Path,
    split_reference: Path,
    output: Path,
    *,
    allow_exploratory: bool = False,
) -> DataSnapshot:
    """只创建新研究目录；原始批次、账户、登记和样本外状态均不修改。"""
    if not allow_exploratory or not datasets:
        raise ValueError("Alpaca historical research requires explicit exploratory opt-in")
    if any(not key.isascii() or not key.isalnum() or not key.isupper() for key in datasets):
        raise ValueError("Research instruments must be uppercase alphanumeric symbols")
    output = output.resolve()
    protect_inputs((output,), (*datasets.values(), issuer, split_reference))
    output.mkdir(parents=True, exist_ok=False)
    (output / "execution").mkdir()
    bars_rows: list[dict[str, Any]] = []
    universe_rows: list[dict[str, Any]] = []
    coverages: list[pa.Table] = []
    try:
        for symbol, dataset in sorted(datasets.items()):
            destination = output / "execution" / f"{symbol}.parquet"
            evidence = destination.with_suffix(".evidence")
            shutil.copytree(dataset, evidence / "dataset")
            shutil.copy2(issuer, evidence / "issuer.parquet")
            shutil.copy2(split_reference, evidence / "split-reference.parquet")
            bars, manifest, coverage = _validated_inputs(evidence)
            if manifest["symbol"] != symbol:
                raise ValueError("Alpaca dataset symbol differs from its declared instrument")
            pq.write_table(coverage, evidence / "coverage.parquet", compression="zstd")
            seal_artifacts(evidence)
            metadata = {
                **(bars.schema.metadata or {}),
                b"volume_unit": b"shares",
                b"corporate_actions": b"bounded_research",
                b"currency_basis": b"project_usd_convention",
                b"source_ref": str(dataset.resolve()).encode(),
                b"evidence_sha256": digest(evidence / "artifacts.parquet").encode(),
            }
            pq.write_table(bars.replace_schema_metadata(metadata), destination, compression="zstd")
            validate_alpaca_execution(destination, pq.read_table(destination))
            captured = {}
            for page in pq.read_table(dataset / "raw.parquet").to_pylist():
                if page["kind"] == "bars":
                    for bar in decode(page["body"])["bars"].get(symbol, []):
                        day = datetime.fromisoformat(bar["t"]).astimezone(NEW_YORK).date()
                        captured[day] = page["received_at"]
            bars_rows.extend(
                {
                    "date": row["date"],
                    "instrument": symbol,
                    **{name: row[name] for name in ("open", "high", "low", "close", "volume")},
                    "available_at": None,
                    "captured_at": captured[row["date"]],
                }
                for row in bars.to_pylist()
            )
            universe_rows.append(
                {
                    "instrument": symbol,
                    "symbol": symbol,
                    "start": manifest["start"],
                    "end": manifest["end"],
                    "available_at": None,
                }
            )
            coverages.append(coverage)
        snapshot = create_snapshot(
            pa.Table.from_pylist(bars_rows, schema=RESEARCH_BARS),
            pa.Table.from_pylist(universe_rows, schema=UNIVERSE),
            output / "snapshot",
            SnapshotSpec("alpaca", str(output), "raw", "shares", "current_sample"),
            allow_exploratory=True,
        )
        pq.write_table(pa.concat_tables(coverages), output / "coverage.parquet", compression="zstd")
    finally:
        seal_artifacts(output)
    return snapshot
