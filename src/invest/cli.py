"""Command-line entry point for offline research."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from invest.analysis import analyze_prices
from invest.config import load_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invest", description="US equity research tools")
    parser.add_argument("--version", action="version", version=version("wayslog-invest"))
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Summarize adjusted daily closing prices")
    analyze.add_argument("parquet", type=Path, help="Parquet with date32 date and adjusted_close")
    paper = commands.add_parser("paper", help="Update a local daily-bar paper account")
    paper.add_argument("--data", type=Path, required=True, help="Raw bars in Parquet")
    paper.add_argument("--config", type=Path, required=True, help="Research parameters in TOML")
    paper.add_argument("--account", type=Path, required=True, help="Persistent account directory")
    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            output = asdict(analyze_prices(args.parquet))
        else:
            from invest.storage import update_paper

            location = update_paper(args.data, args.account, load_config(args.config))
            output = {"run_directory": str(location.directory), "updated": location.updated}
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"invest: {exc}\n")
    print(json.dumps(output, indent=2, allow_nan=False))
    return 0
