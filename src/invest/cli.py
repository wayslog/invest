"""Command-line entry point for offline research."""

import argparse
import json
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path

from invest.analysis import analyze_prices
from invest.config import load_config


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invest", description="US equity research tools")
    parser.add_argument("--version", action="version", version=version("wayslog-invest"))
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Summarize adjusted daily closing prices")
    analyze.add_argument("parquet", type=Path, help="Parquet with date32 date and adjusted_close")
    paper = commands.add_parser("paper", help="Update a local daily-bar paper account")
    inputs = paper.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--data", type=Path, help="Synthetic bars in Parquet")
    inputs.add_argument("--dataset", type=Path, help="Verified historical dataset directory")
    paper.add_argument("--config", type=Path, required=True, help="Research parameters in TOML")
    paper.add_argument("--account", type=Path, required=True, help="Persistent account directory")
    paper.add_argument(
        "--dividend-source", type=Path, help="State Street source capture; mismatch blocks updates"
    )
    paper.add_argument(
        "--require-current",
        action="store_true",
        help="Require the latest admissible session (Alpaca: next New York day at 00:15)",
    )
    audit = commands.add_parser("audit", help="Check Parquet structure and XNYS session coverage")
    audit.add_argument("--data", type=Path, required=True)
    audit.add_argument("--symbol", required=True)
    audit.add_argument("--start", type=date.fromisoformat, required=True)
    audit.add_argument("--end", type=date.fromisoformat, required=True)
    audit.add_argument("--as-of", required=True, help="Explicit timestamp including timezone")
    audit.add_argument("--output", type=Path, required=True, help="New Parquet quality report")
    fetch = commands.add_parser("fetch", help="Capture read-only Alpaca data into Parquet batches")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end", type=date.fromisoformat, required=True)
    fetch.add_argument("--feed", choices=["sip", "iex"], required=True)
    fetch.add_argument(
        "--actions-through",
        type=date.fromisoformat,
        help="Corporate-action process-date cutoff; default today + 120 days",
    )
    fetch.add_argument(
        "--output", type=Path, required=True, help="Parent directory for new batches"
    )
    verify = commands.add_parser("verify-data", help="Verify and reproduce a saved dataset offline")
    verify.add_argument("--dataset", type=Path, required=True)
    source = commands.add_parser(
        "capture-dividends", help="Archive public issuer evidence in Parquet"
    )
    source.add_argument("--output", type=Path, required=True)
    dividends = commands.add_parser("audit-dividends", help="Compare issuer cash dividends offline")
    dividends.add_argument("--dataset", type=Path, required=True)
    dividends.add_argument(
        "--source", type=Path, required=True, help="Issuer source Parquet capture"
    )
    dividends.add_argument("--output", type=Path, required=True, help="New Parquet audit report")
    registration = commands.add_parser("research-register", help="Freeze a research design")
    registration.add_argument("--config", type=Path, required=True)
    registration.add_argument("--output", type=Path, required=True)
    registration.add_argument(
        "--known-history",
        action="store_true",
        help="Freeze prior exposure; results cannot qualify for formal forward observation",
    )
    proposal = commands.add_parser(
        "research-propose", help="Freeze a hypothesis and future validation"
    )
    proposal.add_argument("--config", type=Path, required=True)
    proposal.add_argument("--protocol", type=Path, required=True)
    proposal.add_argument("--known-through", type=date.fromisoformat, required=True)
    proposal.add_argument("--lockfile", type=Path, default=Path("uv.lock"))
    proposal.add_argument("--output", type=Path, required=True)
    diagnostic = commands.add_parser(
        "research-diagnose", help="Explain sealed historical risk and attribution"
    )
    diagnostic.add_argument("--study", type=Path, required=True)
    diagnostic.add_argument("--output", type=Path, required=True)
    research = commands.add_parser("research", help="Run a registered portfolio study offline")
    research.add_argument("--registration", type=Path, required=True)
    research.add_argument(
        "--input", action="append", required=True, help="SYMBOL=dataset directory"
    )
    research.add_argument("--issuer-source", type=Path)
    research.add_argument(
        "--synthetic", action="store_true", help="Inputs are synthetic Parquet files"
    )
    research.add_argument("--output", type=Path, required=True)
    study_verify = commands.add_parser("verify-study", help="Verify and replay a saved study")
    study_verify.add_argument("--study", type=Path, required=True)
    study_verify.add_argument("--hashes-only", action="store_true")
    mine = commands.add_parser("mine", help="Mine factors and freeze research rank signals offline")
    mine.add_argument("--config", type=Path, required=True)
    mine.add_argument("--output", type=Path, required=True)
    from invest.forward_cli import add_forward_commands

    add_forward_commands(commands)
    args = parser.parse_args(argv)
    exit_code = 0

    try:
        if args.command.startswith("forward-"):
            from invest.forward_cli import dispatch_forward

            output = dispatch_forward(args)
            if output.get("error") or (
                args.command in {"forward-run", "forward-job"} and output.get("status") == "paused"
            ):
                exit_code = 1
        elif args.command == "analyze":
            output = asdict(analyze_prices(args.parquet))
        elif args.command == "mine":
            from invest.factor_mining import run_mining

            with redirect_stdout(sys.stderr):
                output = asdict(run_mining(args.config, args.output))
            output["directory"] = str(output["directory"])
            exit_code = 0 if output["selected"] else 1
        elif args.command == "research-register":
            from invest.research_registry import register_study

            register_study(args.config, args.output, known_history=args.known_history)
            output = {"registration": str(args.output)}
        elif args.command == "research-propose":
            from invest.research_proposals import register_proposal

            output = register_proposal(
                args.config, args.protocol, args.output, args.known_through, lockfile=args.lockfile
            )
        elif args.command == "research-diagnose":
            from invest.research_diagnostics import diagnose_study

            output = diagnose_study(args.study, args.output)
        elif args.command == "research":
            from invest.research import run_study
            from invest.research_registry import parse_mappings

            directory = run_study(
                args.registration,
                parse_mappings(args.input),
                args.output,
                issuer=args.issuer_source,
                synthetic=args.synthetic,
            )
            output = {"study": str(directory), "report": str(directory / "report.html")}
        elif args.command == "verify-study":
            from invest.research import verify_study

            count = verify_study(args.study, replay=not args.hashes_only)
            output = {"study": str(args.study), "runs": count, "replayed": not args.hashes_only}
        elif args.command == "paper":
            from invest.quality import latest_completed_session
            from invest.storage import update_paper

            location = update_paper(
                args.dataset / "bars.parquet" if args.dataset else args.data,
                args.account,
                load_config(args.config),
                dataset=args.dataset,
                dividend_source=args.dividend_source,
                required_through=latest_completed_session(
                    datetime.now(UTC), provider_daily=args.dataset is not None
                )
                if args.require_current
                else None,
            )
            output = {"run_directory": str(location.directory), "updated": location.updated}
        elif args.command == "audit":
            from invest.quality import audit_bars, parse_as_of, save_quality

            report = audit_bars(
                args.data, args.symbol, args.start, args.end, parse_as_of(args.as_of)
            )
            save_quality(report, args.output)
            exit_code = 1 if report.errors else 0
            output = {
                "scope": "structure_and_calendar_only",
                "errors": report.errors,
                "warnings": report.warnings,
                "output": str(args.output),
            }
        elif args.command == "fetch":
            import pyarrow.parquet as pq

            from invest.alpaca import FetchSpec
            from invest.datasets import fetch_dataset

            spec = FetchSpec(args.symbol, args.start, args.end, args.feed)
            if args.actions_through is not None:
                spec = FetchSpec(args.symbol, args.start, args.end, args.feed, args.actions_through)
            dataset_location = fetch_dataset(spec, args.output)
            status = pq.read_table(dataset_location / "manifest.parquet")["status"][0].as_py()
            findings = pq.read_table(dataset_location / "quality.parquet").to_pylist()
            output = {
                "dataset": str(dataset_location),
                "status": status,
                "errors": [row["detail"] for row in findings if row["status"] == "error"],
                "warnings": sum(row["status"] == "warning" for row in findings),
            }
            exit_code = 1 if status == "quarantined" else 0
        elif args.command == "capture-dividends":
            from invest.dividends import capture_distributions

            capture_distributions(args.output)
            output = {"source": str(args.output)}
        elif args.command == "audit-dividends":
            from invest.dividends import audit_dividends
            from invest.quality import save_quality

            report = audit_dividends(args.dataset, args.source)
            save_quality(report, args.output)
            exit_code = 1 if report.errors else 0
            output = {
                "errors": report.errors,
                "checks": report.checks.num_rows,
                "output": str(args.output),
            }
        else:
            from invest.datasets import verify_dataset

            bars = verify_dataset(args.dataset)
            output = {
                "dataset": str(args.dataset),
                "observations": bars.num_rows,
                "scope": "historical_research_only",
            }
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"invest: {exc}\n")
    print(json.dumps(output, indent=2, allow_nan=False, default=_json_default))
    return exit_code
