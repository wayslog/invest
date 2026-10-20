"""Immutable research datasets with captured evidence and fail-closed admission."""

import hashlib
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from invest.alpaca import (
    NEW_YORK,
    RAW_SCHEMA,
    FetchSpec,
    RequestData,
    authenticated_request,
    decode,
    fetch_pages,
    normalize,
)
from invest.quality import QUALITY_SCHEMA, QualityReport, audit_bars, daily_capture_after

MANIFEST_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("provider", pa.string()),
        ("symbol", pa.string()),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("feed", pa.string()),
        ("actions_through", pa.date32()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("status", pa.string()),
        ("scope", pa.string()),
        ("normalizer_version", pa.string()),
    ],
    metadata={b"schema_version": b"invest.dataset.v2"},
)
FILES_SCHEMA = pa.schema([("file", pa.string()), ("sha256", pa.string())])
NORMALIZER_VERSION = "alpaca.v2"
FILES = {
    "raw.parquet",
    "manifest.parquet",
    "quality.parquet",
    "bars.parquet",
    "actions.parquet",
    "availability.parquet",
}


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def daily_capture_ready(raw: pa.Table, spec: FetchSpec) -> bool:
    # A later corporate-action response cannot make prematurely fetched bars complete.
    return all(
        row["received_at"]
        >= daily_capture_after(datetime.fromisoformat(bar["t"]).astimezone(NEW_YORK).date())
        for row in raw.to_pylist()
        if row["kind"] == "bars"
        for bar in decode(row["body"])["bars"].get(spec.symbol, [])
    )


def fetch_dataset(spec: FetchSpec, root: Path, request: RequestData | None = None) -> Path:
    """Preserve failures as quarantined batches; never rewrite another dataset."""
    request = request or authenticated_request()
    dataset_id = uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    staging, destination = root / f".{dataset_id}.tmp", root / dataset_id
    staging.mkdir()
    try:
        pages: list[dict[str, object]] = []
        failure = ""
        try:
            for page in fetch_pages(spec, request):
                pages.append(page)
        except ValueError as exc:
            failure = str(exc)
        except (KeyError, TypeError):
            failure = "Fetch failed or pagination incomplete; inspect access and captured responses"
        raw = pa.Table.from_pylist(pages, schema=RAW_SCHEMA)
        pq.write_table(raw, staging / "raw.parquet", compression="zstd")
        observed_at = max(raw["received_at"].to_pylist()) if pages else datetime.now(UTC)
        if not failure:
            try:
                bars, actions, availability = normalize(raw, spec, dataset_id)
                for name, table in [
                    ("bars", bars),
                    ("actions", actions),
                    ("availability", availability),
                ]:
                    pq.write_table(table, staging / f"{name}.parquet", compression="zstd")
                quality = audit_bars(
                    staging / "bars.parquet", spec.symbol, spec.start, spec.end, observed_at
                )
            except (KeyError, TypeError):
                failure = "Provider response is missing a required field or has an invalid type"
            except ValueError as exc:
                failure = str(exc)
        if failure:
            quality = QualityReport(
                pa.Table.from_pylist(
                    [{"status": "error", "check": "ingestion", "date": None, "detail": failure}],
                    schema=QUALITY_SCHEMA,
                )
            )
        else:
            extra: list[dict[str, object]] = [
                {
                    "status": "pass",
                    "check": "provider_capture",
                    "date": None,
                    "detail": "Both endpoints paginated to completion; supported actions mapped",
                },
                {
                    "status": "warning",
                    "check": "daily_open_proxy",
                    "date": None,
                    "detail": "Historical daily-open proxy; auction execution unverified",
                },
            ]
            if spec.feed == "iex":
                extra.append(
                    {
                        "status": "warning",
                        "check": "limited_feed",
                        "date": None,
                        "detail": "IEX is one venue, not consolidated US market data",
                    }
                )
            if not daily_capture_ready(raw, spec):
                extra.append(
                    {
                        "status": "error",
                        "check": "unfinished_provider_capture",
                        "date": spec.end,
                        "detail": "A bar page was captured before the provider daily cutoff",
                    }
                )
            quality = QualityReport(
                pa.concat_tables(
                    [quality.checks, pa.Table.from_pylist(extra, schema=quality.checks.schema)]
                )
            )
        pq.write_table(quality.checks, staging / "quality.parquet", compression="zstd")
        manifest = pa.Table.from_pylist(
            [
                {
                    "dataset_id": dataset_id,
                    "provider": "alpaca",
                    "symbol": spec.symbol,
                    "start": spec.start,
                    "end": spec.end,
                    "feed": spec.feed,
                    "actions_through": spec.actions_through,
                    "observed_at": observed_at,
                    "status": "quarantined" if quality.errors else "research_only",
                    "scope": "historical_research_only",
                    "normalizer_version": NORMALIZER_VERSION,
                }
            ],
            schema=MANIFEST_SCHEMA,
        )
        pq.write_table(manifest, staging / "manifest.parquet", compression="zstd")
        files = pa.Table.from_pylist(
            [{"file": path.name, "sha256": checksum(path)} for path in sorted(staging.iterdir())],
            schema=FILES_SCHEMA,
        )
        pq.write_table(files, staging / "files.parquet", compression="zstd")
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def verify_dataset(directory: Path) -> pa.Table:
    """Verify bytes and reproduce normalization before admitting historical research."""
    files = pq.read_table(directory / "files.parquet")
    if not files.schema.equals(FILES_SCHEMA) or files.num_rows != len(
        set(files["file"].to_pylist())
    ):
        raise ValueError("Invalid dataset file inventory")
    inventory = set(files["file"].to_pylist())
    if not {"raw.parquet", "manifest.parquet", "quality.parquet"} <= inventory or inventory - FILES:
        raise ValueError("Invalid dataset inventory paths")
    paths = list(directory.iterdir())
    if {path.name for path in paths} != inventory | {"files.parquet"} or any(
        path.is_symlink() or not path.is_file() for path in paths
    ):
        raise ValueError("Dataset contains unexpected files or links")
    for row in files.to_pylist():
        if checksum(directory / row["file"]) != row["sha256"]:
            raise ValueError(f"Dataset checksum mismatch: {row['file']}")
    table = pq.read_table(directory / "manifest.parquet")
    if not table.schema.equals(MANIFEST_SCHEMA, check_metadata=True) or table.num_rows != 1:
        raise ValueError("Invalid dataset manifest")
    manifest = table.to_pylist()[0]
    if manifest["status"] != "research_only" or inventory != FILES:
        raise ValueError("Dataset is quarantined; inspect quality.parquet")
    if (
        manifest["normalizer_version"] != NORMALIZER_VERSION
        or manifest["provider"] != "alpaca"
        or manifest["scope"] != "historical_research_only"
    ):
        raise ValueError("Unsupported dataset version/provider/scope")
    spec = FetchSpec(
        manifest["symbol"],
        manifest["start"],
        manifest["end"],
        manifest["feed"],
        manifest["actions_through"],
    )
    raw = pq.read_table(directory / "raw.parquet")
    if manifest["observed_at"] != max(raw["received_at"].to_pylist()):
        raise ValueError("Dataset observation timestamp mismatch")
    if manifest["observed_at"] > datetime.now(UTC):
        raise ValueError("Dataset observation time is in the future")
    normalized = normalize(raw, spec, manifest["dataset_id"])
    if not daily_capture_ready(raw, spec):
        raise ValueError("Dataset contains a premature provider daily capture")
    for name, expected in zip(["bars", "actions", "availability"], normalized, strict=True):
        if not pq.read_table(directory / f"{name}.parquet").equals(expected, check_metadata=True):
            raise ValueError(f"Dataset normalization mismatch: {name}")
    current = audit_bars(
        directory / "bars.parquet", spec.symbol, spec.start, spec.end, manifest["observed_at"]
    )
    saved = QualityReport(pq.read_table(directory / "quality.parquet"))
    if not saved.checks.schema.equals(current.checks.schema, check_metadata=True):
        raise ValueError("Saved quality report does not describe this dataset")
    if current.errors or saved.errors:
        raise ValueError("Dataset failed calendar/structure admission checks")
    return normalized[0]
