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
    for name in ["service", "health", "notify-test", "system-failure"]:
        parser = commands.add_parser(f"forward-{name}", help=f"Forward operations: {name}")
        parser.add_argument("--config", type=Path, required=True)
    for name in [
        "init",
        "run",
        "status",
        "verify",
        "control",
        "job",
        "backup",
        "restore",
        "migrate",
    ]:
        parser = commands.add_parser(f"forward-{name}", help=f"Forward paper account: {name}")
        parser.add_argument("--account", type=Path, required=True)
        if name in {"init", "run"}:
            parser.add_argument("--input", action="append", required=True, help="SYMBOL=PATH")
            parser.add_argument("--issuer-source", type=Path)
        if name in {"init", "run", "status", "control", "restore", "migrate"}:
            parser.add_argument("--at", type=parse_as_of, help="Synthetic drills only")
        if name == "init":
            parser.add_argument("--config", type=Path, required=True, help="Observation TOML")
            parser.add_argument("--policy", type=Path, required=True, help="Frozen M2 policy TOML")
            parser.add_argument(
                "--study", type=Path, help="Required for qualified_strategy and shadow_research"
            )
        if name in {"control", "restore", "migrate"}:
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
        if name == "migrate":
            parser.add_argument(
                "--backup", type=Path, required=True, help="New backup outside the account"
            )
            parser.add_argument("--expected-head", required=True)
            parser.add_argument("--from-engine", required=True)


def dispatch_forward(args: argparse.Namespace) -> dict[str, Any]:
    if args.command in {
        "forward-service",
        "forward-health",
        "forward-notify-test",
        "forward-system-failure",
    }:
        from invest.forward_service import (
            check_service,
            notification_test,
            run_service,
            system_failure,
        )

        operation = {
            "forward-service": run_service,
            "forward-health": check_service,
            "forward-notify-test": notification_test,
            "forward-system-failure": system_failure,
        }[args.command]
        return operation(args.config)
    if (args.account / "registration.parquet").is_file():
        from invest import ibkr_observation

        if getattr(args, "at", None) is not None:
            raise ValueError("IBKR cash observation uses the host clock")
        if args.command == "forward-status":
            return ibkr_observation.status(args.account)
        if args.command == "forward-verify":
            return ibkr_observation.verify(args.account)
        if args.command == "forward-backup":
            return ibkr_observation.backup(args.account, args.output)
        if args.command == "forward-job":
            if args.issuer_source is not None:
                raise ValueError("IBKR cash observation does not use issuer fallback data")
            return ibkr_observation.job(args.account, args.data_root, attempts=args.attempts)
        raise ValueError("This command requires a legacy forward account")
    if args.command == "forward-migrate":
        from invest.forward_migration import migrate_forward

        return migrate_forward(
            args.account,
            args.expected_head,
            args.from_engine,
            args.backup,
            args.actor,
            args.reason,
            at=args.at,
        )
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
