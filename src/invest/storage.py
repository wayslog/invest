"""Atomic Parquet snapshots for a persistent local paper account."""

import hashlib
import os
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from filelock import FileLock, Timeout

from invest.config import PaperConfig
from invest.datasets import verify_dataset
from invest.dividends import audit_dividends
from invest.market import MONEY, read_bars
from invest.paper import simulate
from invest.quality import audit_bars
from invest.reconcile import reconcile
from invest.report import write_report


@dataclass(frozen=True)
class RunLocation:
    directory: Path
    updated: bool


def engine_digest() -> str:
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def update_paper(
    data: Path,
    account: Path,
    config: PaperConfig,
    *,
    dataset: Path | None = None,
    dividend_source: Path | None = None,
    required_through: date | None = None,
) -> RunLocation:
    """Replay append-only observations and atomically publish a complete snapshot.

    Replaying from inception avoids two independent accounting implementations.
    Identical input is a no-op. Amended history/config needs a new account.
    """
    if dataset is not None:
        if data.resolve() != (dataset / "bars.parquet").resolve():
            raise ValueError("Input must be the verified dataset's bars.parquet")
        bars = verify_dataset(dataset)
        if bars["symbol"][0].as_py() != config.symbol:
            raise ValueError("Dataset symbol differs from account parameters")
    else:
        bars = read_bars(data, config.symbol)
        if (bars.schema.metadata or {})[b"source"] != b"synthetic":
            raise ValueError("Real data requires a verified --dataset with provenance")
    quality = audit_bars(
        data,
        config.symbol,
        bars["date"][0].as_py(),
        required_through or bars["date"][-1].as_py(),
        datetime.now(UTC),
    )
    if quality.errors:
        raise ValueError("Data quality failed; missing/stale/unfinished sessions or invalid bars")
    dividend_checks = None
    source_bytes = None
    if dividend_source is not None:
        if dataset is None:
            raise ValueError("Issuer dividend evidence requires a verified dataset")
        source_bytes = dividend_source.read_bytes()
        dividend_checks = audit_dividends(dataset, dividend_source)
        if dividend_checks.errors:
            raise ValueError("Issuer dividend mismatch; account not updated")
        if (
            hashlib.sha256(source_bytes).hexdigest().encode()
            != (dividend_checks.checks.schema.metadata or {})[b"source_sha256"]
        ):
            raise ValueError("Issuer source changed during validation")
    schema = pa.schema(
        [
            (
                f.name,
                pa.string()
                if f.name == "symbol"
                else pa.int64()
                if f.name == "lookback"
                else MONEY,
            )
            for f in fields(config)
        ]
    )
    settings = pa.Table.from_pylist([asdict(config)], schema=schema)
    digest = engine_digest()
    account.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(account / ".lock", timeout=0):
            pointer = account / "CURRENT"
            if pointer.exists():
                name = pointer.read_text(encoding="utf-8").strip()
                if not name or Path(name).name != name or name in {".", ".."}:
                    raise ValueError("Invalid paper account CURRENT pointer")
                previous = account / "runs" / name
                if not pq.read_table(previous / "config.parquet").equals(settings):
                    raise ValueError("Account parameters changed; use a new account directory")
                manifest = pq.read_table(previous / "manifest.parquet").to_pylist()[0]
                if manifest["engine_source_sha256"] != digest:
                    raise ValueError("Engine implementation changed; use a new account directory")
                previous_source = previous / "dividend-source.parquet"
                if (
                    previous_source.read_bytes() if previous_source.exists() else None
                ) != source_bytes:
                    raise ValueError("Issuer evidence changed; use a new account directory")
                history = pq.read_table(previous / "bars.parquet")

                def stable_metadata(table: pa.Table) -> dict[bytes, bytes]:
                    return {
                        key: value
                        for key, value in (table.schema.metadata or {}).items()
                        if key not in {b"dataset_id", b"observed_at"}
                    }

                if (
                    bars.num_rows < history.num_rows
                    or stable_metadata(bars) != stable_metadata(history)
                    or not bars.slice(0, history.num_rows).equals(history, check_metadata=False)
                ):
                    raise ValueError("Paper history was changed or truncated; use a new account")
                if bars.num_rows == history.num_rows:
                    return RunLocation(previous, updated=False)
            result = simulate(bars, config)
            reconciliation = reconcile(bars, result, config)
            if "error" in reconciliation["status"].to_pylist():
                raise ValueError("Account reconciliation failed; snapshot not published")
            runs = account / "runs"
            runs.mkdir(exist_ok=True)
            name = uuid.uuid4().hex
            staging = runs / f".{name}.tmp"
            destination = runs / name
            staging.mkdir()
            temporary_pointer = account / f".CURRENT.{name}"
            try:
                for filename, table in {
                    "bars": bars,
                    "config": settings,
                    "equity": result.equity,
                    "trades": result.trades,
                    "events": result.events,
                    "benchmark_trades": result.benchmark_trades,
                    "metrics": result.metrics,
                    "quality": quality.checks,
                    "reconciliation": reconciliation,
                }.items():
                    pq.write_table(table, staging / f"{filename}.parquet", compression="zstd")
                if dataset is not None:
                    shutil.copytree(dataset, staging / "dataset")
                    if not verify_dataset(staging / "dataset").equals(bars, check_metadata=True):
                        raise ValueError("Dataset changed while publishing the snapshot")
                    if dividend_checks is not None and source_bytes is not None:
                        (staging / "dividend-source.parquet").write_bytes(source_bytes)
                        copied = audit_dividends(
                            staging / "dataset", staging / "dividend-source.parquet"
                        )
                        if not copied.checks.equals(dividend_checks.checks, check_metadata=True):
                            raise ValueError(
                                "Dividend evidence changed while publishing the snapshot"
                            )
                        pq.write_table(
                            copied.checks, staging / "dividends.parquet", compression="zstd"
                        )
                manifest = pa.Table.from_pylist(
                    [
                        {
                            "engine_version": version("wayslog-invest"),
                            "engine_source_sha256": digest,
                            "input_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                            "python_version": sys.version.split()[0],
                            "pyarrow_version": pa.__version__,
                            "run_id": name,
                        }
                    ]
                )
                pq.write_table(manifest, staging / "manifest.parquet", compression="zstd")
                write_report(result, staging)
                staging.rename(destination)
                temporary_pointer.write_text(name + "\n", encoding="utf-8")
                os.replace(temporary_pointer, pointer)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                temporary_pointer.unlink(missing_ok=True)
                raise
            return RunLocation(destination, updated=True)
    except Timeout as exc:
        raise ValueError("Another process is updating this paper account") from exc
