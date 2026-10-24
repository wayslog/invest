"""量化研究主入口；挖掘、回测、只读决策共享冻结输入与正式结果。"""

import argparse
import json
import sys
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import date
from importlib.metadata import version
from pathlib import Path


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    # 持续账户仍使用原始操作契约；只在显式调用时加载旧运行模块。
    if values and (values[0] == "legacy" or values[0].startswith("forward-")):
        from invest.legacy_cli import main as legacy_main

        return legacy_main(values[1:] if values[0] == "legacy" else values)
    parser = argparse.ArgumentParser(
        prog="invest",
        description="Offline quantitative research: mine, backtest and decide",
        epilog=(
            "Use invest legacy --help for historical workflows. "
            "Existing forward-* commands remain available."
        ),
    )
    parser.add_argument("--version", action="version", version=version("wayslog-invest"))
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("mine", "Mine factors and freeze research signals"),
        ("backtest", "Backtest a frozen pool with shared cash and independent audit"),
        ("decide", "Generate read-only stock rankings and action recommendations"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "decide":
            command.add_argument(
                "--as-of",
                type=date.fromisoformat,
                required=True,
                help="Explicit XNYS decision session date",
            )
    for name in ("verify-backtest", "verify-decision"):
        command = commands.add_parser(name, help="Verify and replay a frozen research result")
        command.add_argument("--study", type=Path, required=True)
    commands.add_parser("legacy", help="Explicit legacy research and account compatibility")
    args = parser.parse_args(values)
    exit_code = 0
    try:
        with redirect_stdout(sys.stderr):
            if args.command == "mine":
                from invest.factor_mining import run_mining

                output = asdict(run_mining(args.config, args.output))
                exit_code = 0 if output["selected"] else 1
            elif args.command == "backtest":
                from invest.backtest_study import run_backtest

                output = asdict(run_backtest(args.config, args.output))
            elif args.command == "decide":
                from invest.decision_study import run_decision

                output = asdict(run_decision(args.config, args.output, args.as_of))
                exit_code = 0 if output["status"] == "completed" else 1
            elif args.command == "verify-backtest":
                from invest.backtest_study import verify_backtest

                output = verify_backtest(args.study)
            else:
                from invest.decision_study import verify_decision

                output = verify_decision(args.study)
        if "directory" in output:
            output["report"] = str(Path(output["directory"]) / "report.html")
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"invest: {exc}\n")
    print(json.dumps(output, indent=2, allow_nan=False, default=_json_default))
    return exit_code
