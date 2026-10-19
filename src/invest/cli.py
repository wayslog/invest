"""Command-line entry point for offline research."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from invest.analysis import analyze_prices


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="invest", description="US equity research tools")
    parser.add_argument("--version", action="version", version=version("wayslog-invest"))
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Summarize adjusted daily closing prices")
    analyze.add_argument("csv", type=Path, help="CSV containing date and adjusted_close columns")
    args = parser.parse_args(argv)

    try:
        summary = analyze_prices(args.csv)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"invest: {exc}\n")
    print(json.dumps(asdict(summary), indent=2, allow_nan=False))
    return 0
