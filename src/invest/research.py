"""Predeclared, reproducible research with selection persisted before holdout evaluation."""

import shutil
import sys
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime
from importlib.metadata import distributions, version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.datasets import checksum, verify_dataset
from invest.dividends import audit_dividends
from invest.evaluation import METRIC_SCHEMA, evaluate, yearly
from invest.market import read_bars
from invest.portfolio import PortfolioResult, simulate_portfolio
from invest.portfolio_audit import audit_portfolio
from invest.research_registry import read_registration, seal, verify_inventory, write_table
from invest.storage import engine_digest
from invest.strategies import Candidate, candidates
from invest.study_config import StudyConfig

BENCHMARKS = [Candidate(kind) for kind in ["equal_weight", "buy_hold", "market", "cash"]]
ADMISSION_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("admitted", pa.bool_()),
        ("reason", pa.string()),
        ("source_sha256", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("first_bar_received_at", pa.timestamp("us", tz="UTC")),
    ]
)
COMPARISON_SCHEMA = pa.schema(
    [
        ("phase", pa.string()),
        ("candidate", pa.string()),
        ("kind", pa.string()),
        ("lookback", pa.int64()),
        ("start", pa.date32()),
        ("end", pa.date32()),
        ("cost_multiplier", pa.int64()),
        ("gap_bps", pa.int64()),
        ("run", pa.string()),
        *list(METRIC_SCHEMA),
    ]
)
SELECTION_SCHEMA = pa.schema(
    [
        ("phase", pa.string()),
        ("candidate", pa.string()),
        ("selection_end", pa.date32()),
        ("evaluation_start", pa.date32()),
        ("basis", pa.string()),
        ("saved_at", pa.timestamp("us", tz="UTC")),
    ]
)
GATE_SCHEMA = pa.schema([("check", pa.string()), ("passed", pa.bool_()), ("detail", pa.string())])
MANIFEST_SCHEMA = pa.schema(
    [
        ("study_id", pa.string()),
        ("version", pa.string()),
        ("engine_sha256", pa.string()),
        ("config_sha256", pa.string()),
        ("registered_at", pa.timestamp("us", tz="UTC")),
        ("started_at", pa.timestamp("us", tz="UTC")),
        ("completed_at", pa.timestamp("us", tz="UTC")),
        ("scope", pa.string()),
        ("selected_candidate", pa.string()),
        ("m3_research_eligible", pa.bool_()),
        ("run_count", pa.int64()),
    ],
    metadata={b"schema_version": b"invest.study.v2"},
)


def admit_inputs(
    config: StudyConfig,
    sources: dict[str, Path],
    staging: Path,
    issuer: Path | None,
    *,
    synthetic: bool,
) -> tuple[dict[str, pa.Table], pa.Table]:
    if set(sources) != set(config.symbols):
        raise ValueError("Supply every registered symbol, including quarantined candidates")
    if not synthetic and issuer is None:
        raise ValueError("Historical ETF research requires independent issuer evidence")
    if issuer:
        shutil.copyfile(issuer, staging / "issuer-source.parquet")
    admitted: dict[str, pa.Table] = {}
    rows = []
    for symbol in sorted(sources):
        source, destination = sources[symbol], staging / "inputs" / symbol
        destination.parent.mkdir(parents=True, exist_ok=True)
        observed = None
        first_bar_received = None
        if synthetic:
            destination.mkdir()
            shutil.copyfile(source, destination / "bars.parquet")
            digest = checksum(destination / "bars.parquet")
        else:
            shutil.copytree(source, destination)
            manifest = pq.read_table(destination / "manifest.parquet").to_pylist()[0]
            observed = manifest["observed_at"]
            digest = checksum(destination / "files.parquet")
            if manifest["symbol"] != symbol:
                raise ValueError("Dataset identity does not match the registered symbol")
        reason = "passed"
        try:
            if synthetic:
                bars = read_bars(destination / "bars.parquet", symbol)
                if (bars.schema.metadata or {}).get(b"source") != b"synthetic":
                    raise ValueError("Synthetic mode requires explicit synthetic source metadata")
            else:
                bars = verify_dataset(destination)
                # A later action response or later bar page cannot hide an earlier capture.
                raw = pq.read_table(destination / "raw.parquet").to_pylist()
                first_bar_received = min(
                    (row["received_at"] for row in raw if row["kind"] == "bars"),
                    default=None,
                )
                audit = audit_dividends(destination, staging / "issuer-source.parquet")
                write_table(audit.checks, staging / "issuer-audits" / f"{symbol}.parquet")
                if audit.errors:
                    raise ValueError("Issuer cash dividend audit failed")
            admitted[symbol] = bars
        except ValueError as exc:
            reason = str(exc)
            if not synthetic and reason.startswith("Dataset is quarantined"):
                errors = [
                    row["detail"]
                    for row in pq.read_table(destination / "quality.parquet").to_pylist()
                    if row["status"] == "error"
                ]
                reason += ": " + "; ".join(errors)
        rows.append(
            {
                "symbol": symbol,
                "admitted": symbol in admitted,
                "reason": reason,
                "source_sha256": digest,
                "observed_at": observed,
                "first_bar_received_at": first_bar_received,
            }
        )
    table = pa.Table.from_pylist(rows, schema=ADMISSION_SCHEMA)
    write_table(table, staging / "admission.parquet")
    if len(admitted) < 2 or "SPY" not in admitted:
        raise ValueError("Study needs >= 2 qualified symbols, including market benchmark SPY")
    return admitted, table


def _save_result(
    directory: Path,
    result: PortfolioResult,
    inputs: dict[str, pa.Table],
    config: StudyConfig,
    cost: int,
    gap: int,
) -> pa.Table:
    for field in fields(result):
        write_table(getattr(result, field.name), directory / f"{field.name}.parquet")
    audit, attribution, closed = audit_portfolio(
        inputs,
        result,
        config,
        cost_multiplier=cost,
        gap_bps=gap,
    )
    write_table(audit, directory / "reconciliation.parquet")
    if "error" in audit["status"].to_pylist():
        raise ValueError(f"Independent portfolio reconstruction failed: {directory.name}")
    write_table(attribution, directory / "attribution.parquet")
    write_table(closed, directory / "closed-trades.parquet")
    metrics = evaluate(result, config.initial_cash, closed)
    write_table(metrics, directory / "metrics.parquet")
    return metrics


def _pick(rows: list[dict[str, Any]], options: list[Candidate]) -> Candidate:
    # No holdout input reaches selection; inactive/negative candidates are still retained.
    names = {option.name: option for option in options}
    ranked = sorted(
        (r for r in rows if r["candidate"] in names),
        key=lambda r: (-r["total_return"], r["candidate"]),
    )
    return names[ranked[0]["candidate"]]


def _selection(directory: Path, phase: str, candidate: Candidate, end: date, start: date) -> None:
    if end >= start:
        raise ValueError("Selection must end before evaluation starts")
    write_table(
        pa.Table.from_pylist(
            [
                {
                    "phase": phase,
                    "candidate": candidate.name,
                    "selection_end": end,
                    "evaluation_start": start,
                    "basis": "highest_net_return_then_name; no_holdout_input",
                    "saved_at": datetime.now(UTC),
                }
            ],
            schema=SELECTION_SCHEMA,
        ),
        directory / f"{phase}-selection.parquet",
    )


def run_study(
    registration: Path,
    sources: dict[str, Path],
    output: Path,
    *,
    issuer: Path | None = None,
    synthetic: bool = False,
) -> Path:
    digest = engine_digest()
    registration_body = registration.read_bytes()
    config, registered, config_hash = read_registration(registration_body, required_engine=digest)
    if output.exists():
        raise ValueError("Research output already exists; use a new immutable run directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir()
    started = datetime.now(UTC)
    try:
        (staging / "registration.parquet").write_bytes(registration_body)
        inputs, admission = admit_inputs(config, sources, staging, issuer, synthetic=synthetic)
        source_schema = pa.schema([("file", pa.string()), ("body", pa.binary())])
        write_table(
            pa.Table.from_pylist(
                [
                    {"file": path.name, "body": path.read_bytes()}
                    for path in sorted(Path(__file__).parent.glob("*.py"))
                ],
                schema=source_schema,
            ),
            staging / "engine-source.parquet",
        )
        write_table(
            pa.Table.from_pylist(
                [{"package": "python", "version": sys.version}]
                + sorted(
                    [
                        {"package": item.metadata["Name"], "version": item.version}
                        for item in distributions()
                    ],
                    key=lambda item: item["package"],
                ),
                schema=pa.schema([("package", pa.string()), ("version", pa.string())]),
            ),
            staging / "runtime.parquet",
        )
        options = candidates(config)
        write_table(
            pa.Table.from_pylist(
                [{"candidate": c.name, "kind": c.kind, "lookback": c.lookback} for c in options],
                schema=pa.schema(
                    [("candidate", pa.string()), ("kind", pa.string()), ("lookback", pa.int64())]
                ),
            ),
            staging / "candidates.parquet",
        )
        comparisons: list[dict[str, Any]] = []
        results: dict[str, PortfolioResult] = {}

        def run(
            phase: str, candidate: Candidate, start: date, end: date, cost: int = 1, gap: int = 0
        ) -> dict[str, Any]:
            relative = f"runs/{phase}/{candidate.name}-cost{cost}-gap{gap}"
            result = simulate_portfolio(
                inputs, config, candidate, start, end, cost_multiplier=cost, gap_bps=gap
            )
            metrics = _save_result(staging / relative, result, inputs, config, cost, gap)
            row = {
                "phase": phase,
                "candidate": candidate.name,
                "kind": candidate.kind,
                "lookback": candidate.lookback,
                "start": start,
                "end": end,
                "cost_multiplier": cost,
                "gap_bps": gap,
                "run": relative,
                **metrics.to_pylist()[0],
            }
            comparisons.append(row)
            results[relative] = result
            return row

        for phase, start, end in [
            ("train", config.train_start, config.train_end),
            ("validation", config.validation_start, config.validation_end),
        ]:
            for candidate in [*options, *BENCHMARKS]:
                run(phase, candidate, start, end)
        selected = _pick([r for r in comparisons if r["phase"] == "validation"], options)
        # Persist all validation outcomes and the choice BEFORE any holdout evaluation.
        write_table(
            pa.Table.from_pylist(comparisons, schema=COMPARISON_SCHEMA),
            staging / "pre-holdout-results.parquet",
        )
        _selection(staging, "holdout", selected, config.validation_end, config.holdout_start)
        for phase, start, end in [
            ("reused", config.reused_start, config.reused_end),
            ("holdout", config.holdout_start, config.holdout_end),
        ]:
            for candidate in [selected, *BENCHMARKS]:
                run(phase, candidate, start, end)
        for cost in config.cost_multipliers:
            if cost != 1:
                for candidate in [selected, Candidate("equal_weight")]:
                    run(
                        "validation_cost",
                        candidate,
                        config.validation_start,
                        config.validation_end,
                        cost=cost,
                    )
        for candidate in [selected, Candidate("equal_weight")]:
            run(
                "validation_gap", candidate, config.validation_start, config.validation_end, gap=500
            )
        for year in config.walk_forward_years:
            phase = f"walk_{year}"
            training = [
                run(f"{phase}_train", c, date(year - 1, 1, 1), date(year - 1, 12, 31))
                for c in options
            ]
            winner = _pick(training, options)
            _selection(staging, phase, winner, date(year - 1, 12, 31), date(year, 1, 1))
            for candidate in [winner, *BENCHMARKS]:
                run(f"{phase}_test", candidate, date(year, 1, 1), date(year, 12, 31))
        for row in comparisons:
            market_key = f"runs/{row['phase']}/market-cost1-gap0"
            if market_key in results:
                write_table(
                    yearly(results[row["run"]], results[market_key], config.initial_cash),
                    staging / row["run"] / "periods.parquet",
                )
        comparison = pa.Table.from_pylist(comparisons, schema=COMPARISON_SCHEMA)
        write_table(comparison, staging / "comparison.parquet")
        gates = eligibility(comparisons, selected, config, synthetic, admission, registered)
        write_table(gates, staging / "eligibility.parquet")
        eligible = all(gates["passed"].to_pylist())
        scope = "synthetic_engineering_only" if synthetic else "historical_research_only"
        if engine_digest() != digest:
            raise ValueError("Engine changed during the experiment; discard mixed-version results")
        write_table(
            pa.Table.from_pylist(
                [
                    {
                        "study_id": config.study_id,
                        "version": version("wayslog-invest"),
                        "engine_sha256": digest,
                        "config_sha256": config_hash,
                        "registered_at": registered,
                        "started_at": started,
                        "completed_at": datetime.now(UTC),
                        "scope": scope,
                        "selected_candidate": selected.name,
                        "m3_research_eligible": eligible,
                        "run_count": len(comparisons),
                    }
                ],
                schema=MANIFEST_SCHEMA,
            ),
            staging / "manifest.parquet",
        )
        from invest.research_report import render_study

        render_study(staging)
        seal(staging)
        if output.exists():
            raise ValueError("Research output was created concurrently")
        staging.rename(output)
    except Exception as exc:
        write_table(
            pa.Table.from_pylist(
                [{"error": str(exc), "time": datetime.now(UTC)}],
                schema=pa.schema([("error", pa.string()), ("time", pa.timestamp("us", tz="UTC"))]),
            ),
            staging / "failure.parquet",
        )
        staging.rename(output.parent / f"{output.name}.failed-{uuid.uuid4().hex}")
        raise
    return output


def eligibility(
    rows: list[dict[str, Any]],
    selected: Candidate,
    config: StudyConfig,
    synthetic: bool,
    admission: pa.Table,
    registered: datetime,
) -> pa.Table:
    def metric(phase: str, candidate: str, cost: int = 1) -> dict[str, Any]:
        return next(
            r
            for r in rows
            if r["phase"] == phase
            and r["candidate"] == candidate
            and r["cost_multiplier"] == cost
            and r["gap_bps"] == 0
        )

    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    admitted = [r for r in admission.to_pylist() if r["admitted"]]
    observed = [r.get("first_bar_received_at") for r in admitted]
    add(
        "historical_inputs_registered_before_capture",
        not synthetic
        and bool(admitted)
        and all(t is not None and t > registered for t in observed),
        "Every admitted dataset's earliest bar-page receipt must follow registration; "
        "missing timestamps fail. Historical publication times and outside prior exposure "
        "remain unknown; this is not forward evidence",
    )
    for phase in ["train", "validation", "holdout"]:
        row = metric(phase, selected.name)
        add(f"{phase}_active", row["status"] == "active", str(row["status"]))
    for phase in ["validation", "holdout"]:
        row, benchmark = metric(phase, selected.name), metric(phase, "equal_weight")
        add(f"{phase}_positive", row["total_return"] > 0, str(row["total_return"]))
        add(
            f"{phase}_beats_matched_allocation",
            row["total_return"] > benchmark["total_return"],
            f"strategy={row['total_return']}; equal_weight={benchmark['total_return']}",
        )
    row = metric("holdout", selected.name)
    add(
        "holdout_drawdown",
        row["max_drawdown"] >= -float(config.account_drawdown),
        str(row["max_drawdown"]),
    )
    if 2 in config.cost_multipliers:
        row = metric("validation_cost", selected.name, 2)
        add("validation_double_cost_positive", row["total_return"] > 0, str(row["total_return"]))
    else:
        add("validation_double_cost_positive", False, "2x cost scenario not registered")
    return pa.Table.from_pylist(checks, schema=GATE_SCHEMA)


def verify_study(directory: Path, *, replay: bool = True) -> int:
    verify_inventory(directory)
    manifest = pq.read_table(directory / "manifest.parquet").to_pylist()[0]
    config, _, _ = read_registration(
        directory / "registration.parquet",
        required_engine=manifest["engine_sha256"] if replay else None,
    )
    rows = pq.read_table(directory / "comparison.parquet").to_pylist()
    if replay:
        if manifest["engine_sha256"] != engine_digest():
            raise ValueError(
                "Replay requires the archived engine version; source is in engine-source.parquet"
            )
        admission = pq.read_table(directory / "admission.parquet").to_pylist()
        inputs = {
            r["symbol"]: read_bars(directory / "inputs" / r["symbol"] / "bars.parquet", r["symbol"])
            for r in admission
            if r["admitted"]
        }
        for row in rows:
            result = simulate_portfolio(
                inputs,
                config,
                Candidate(row["kind"], row["lookback"]),
                row["start"],
                row["end"],
                cost_multiplier=row["cost_multiplier"],
                gap_bps=row["gap_bps"],
            )
            location = directory / row["run"]
            for field in fields(result):
                if not getattr(result, field.name).equals(
                    pq.read_table(location / f"{field.name}.parquet")
                ):
                    raise ValueError(f"Research replay mismatch: {row['run']}/{field.name}")
            audit, attribution, closed = audit_portfolio(
                inputs,
                result,
                config,
                cost_multiplier=row["cost_multiplier"],
                gap_bps=row["gap_bps"],
            )
            for name, table in [
                ("reconciliation", audit),
                ("attribution", attribution),
                ("closed-trades", closed),
                ("metrics", evaluate(result, config.initial_cash, closed)),
            ]:
                if not table.equals(pq.read_table(location / f"{name}.parquet")):
                    raise ValueError(f"Research replay mismatch: {row['run']}/{name}")
    return len(rows)
