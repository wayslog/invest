"""CLI wiring for the forward account; simulated time is drill-only."""

import argparse
from pathlib import Path
from typing import Any

from invest.forward import (
    control_forward,
    forward_status,
    init_forward,
    run_forward,
    verify_forward,
)
from invest.forward_ops import backup_forward, forward_job, restore_forward
from invest.quality import parse_as_of
from invest.research_registry import parse_mappings


def add_forward_commands(commands: Any) -> None:
    for name in ["init", "run", "status", "verify", "control", "job", "backup", "restore"]:
        parser = commands.add_parser(f"forward-{name}", help=f"Forward paper account: {name}")
        parser.add_argument("--account", type=Path, required=True)
        if name in {"init", "run"}:
            parser.add_argument("--input", action="append", required=True, help="SYMBOL=PATH")
            parser.add_argument("--issuer-source", type=Path)
        if name in {"init", "run", "status", "control", "restore"}:
            parser.add_argument("--at", type=parse_as_of, help="Synthetic drills only")
        if name == "init":
            parser.add_argument("--config", type=Path, required=True, help="Observation TOML")
            parser.add_argument("--policy", type=Path, required=True, help="Frozen M2 policy TOML")
            parser.add_argument(
                "--study", type=Path, help="Required for qualified_strategy and shadow_research"
            )
        if name in {"control", "restore"}:
            parser.add_argument("--actor", required=True)
            parser.add_argument("--reason", required=True)
        if name == "control":
            parser.add_argument("--action", choices=["pause", "resume", "stop"], required=True)
        if name == "job":
            parser.add_argument("--data-root", type=Path, required=True)
            parser.add_argument(
                "--issuer-source",
                type=Path,
                help="Omit to archive a fresh issuer capture for each due task",
            )
            parser.add_argument("--attempts", type=int, default=2)
        if name == "backup":
            parser.add_argument("--output", type=Path, required=True)
        if name == "restore":
            parser.add_argument("--backup", type=Path, required=True)
            parser.add_argument("--expected-head", required=True)


def dispatch_forward(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "forward-init":
        location = init_forward(
            args.account,
            args.config,
            args.policy,
            parse_mappings(args.input),
            issuer=args.issuer_source,
            study=args.study,
            at=args.at,
        )
        return {"run": str(location)}
    if args.command == "forward-run":
        return run_forward(
            args.account, parse_mappings(args.input), issuer=args.issuer_source, at=args.at
        )
    if args.command == "forward-status":
        return forward_status(args.account, at=args.at)
    if args.command == "forward-verify":
        return verify_forward(args.account)
    if args.command == "forward-control":
        location = control_forward(args.account, args.action, args.actor, args.reason, at=args.at)
        return {"run": str(location)}
    if args.command == "forward-backup":
        return backup_forward(args.account, args.output)
    if args.command == "forward-restore":
        return restore_forward(
            args.backup, args.account, args.expected_head, args.actor, args.reason, at=args.at
        )
    return forward_job(args.account, args.data_root, args.issuer_source, attempts=args.attempts)
