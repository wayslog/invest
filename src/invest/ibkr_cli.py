"""IBKR Paper capture and explicit execution-drill commands; no automatic strategy orders."""

import argparse
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from invest import ibkr_execution as execution
from invest.ibkr_data import quality, save_capture
from invest.ibkr_gateway import IBKRGateway
from invest.ibkr_models import create_intent, decimal, read_config
from invest.ibkr_store import EventStore
from invest.quality import latest_completed_session


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="Read-only Paper account and market capture")
    capture.add_argument("--config", type=Path, default=Path("configs/ibkr.toml"))
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--bar-size", choices=["1 day", "1 min", "5 mins", "15 mins", "1 hour"])
    capture.add_argument("--duration")
    for name in ("init", "submit", "cancel", "reconcile"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=Path("configs/ibkr.toml"))
        command.add_argument("--journal", type=Path, required=True)
        if name in {"submit", "cancel"}:
            command.add_argument("--intent-id", required=True)
    intent = commands.add_parser("intent", help="Persist a decision before the next session opens")
    intent.add_argument("--journal", type=Path, required=True)
    intent.add_argument("--capture", type=Path, required=True)
    intent.add_argument("--intent-id", required=True)
    intent.add_argument("--symbol", required=True)
    intent.add_argument("--side", choices=["BUY", "SELL"], required=True)
    intent.add_argument("--quantity", type=int, required=True)
    intent.add_argument("--limit-price", required=True)
    intent.add_argument("--decision-session", type=date.fromisoformat)
    for name in ("status", "export"):
        command = commands.add_parser(name)
        command.add_argument("--journal", type=Path, required=True)
        if name == "export":
            command.add_argument("--output", type=Path, required=True)
    demo = commands.add_parser("demo", help="Offline synthetic timeout/partial-fill/cancel drill")
    demo.add_argument("--output", type=Path, required=True)
    return root


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "demo":
        from invest.ibkr_synthetic import run_demo

        return run_demo(args.output)
    if args.command == "capture":
        config = read_config(args.config)
        changes = {
            key: getattr(args, key) for key in ("bar_size", "duration") if getattr(args, key)
        }
        config = replace(config, **changes)
        with IBKRGateway(config) as broker:
            capture = broker.capture()
        destination = save_capture(capture, args.output)
        checks = quality(capture)
        return {
            "source": "ibkr",
            "environment": "paper",
            "capture": str(destination),
            "complete": not any(row["status"] == "error" for row in checks),
            "account_snapshot_complete": capture.snapshot.complete,
            "contracts": len(capture.contracts),
            "historical_bars": len(capture.historical),
            "positions": len(capture.snapshot.positions),
            "orders": len(capture.snapshot.orders),
            "executions": len(capture.snapshot.executions),
            "quote_types": {row["symbol"]: row["actual_type"] for row in capture.quotes},
            "quality_errors": sorted({r["check"] for r in checks if r["status"] == "error"}),
            "quality_warnings": sorted({r["check"] for r in checks if r["status"] == "warning"}),
            "legacy_engine_admitted": False,
        }
    store = EventStore(args.journal)
    if args.command == "status":
        with store.locked():
            return execution.summary(execution.project(store))
    if args.command == "export":
        return execution.export_report(store, args.output)
    if args.command == "intent":
        with store.locked():
            state = execution.project(store)
            registration = state.registration
            if registration["source"] != "ibkr":
                raise ValueError("Use the offline demo for synthetic journals")
            metadata = pq.read_table(args.capture / "capture.parquet").to_pylist()[0]
            if (metadata["source"], metadata["account"], metadata["client_id"]) != (
                "ibkr",
                registration["account"],
                registration["client_id"],
            ):
                raise ValueError("Contract capture source/account/client differs from journal")
            contracts = pq.read_table(args.capture / "contracts.parquet").to_pylist()
            matches = [r for r in contracts if r["symbol"] == args.symbol]
            if (
                len(matches) != 1
                or matches[0]["currency"] != "USD"
                or matches[0]["security_type"] != "STK"
            ):
                raise ValueError("Select one qualified USD stock/ETF from an IBKR capture")
            contract = matches[0]
            price = decimal(args.limit_price)
            if contract["min_tick"] <= 0 or price % contract["min_tick"]:
                raise ValueError("Limit price must align with the captured contract's minimum tick")
            now = datetime.now(UTC)
            existing = state.orders.get(args.intent_id)
            session = args.decision_session or (
                existing.intent.decision_session if existing else latest_completed_session(now)
            )
            intent = create_intent(
                args.intent_id,
                registration["account"],
                registration["client_id"],
                contract["con_id"],
                args.symbol,
                args.side,
                args.quantity,
                price,
                session,
                existing.intent.decision_at if existing else now,
            )
        updated = execution.add_intent(store, intent)
        return {
            "intent_id": intent.intent_id,
            "updated": updated,
            "valid_from": intent.valid_from,
            "valid_until": intent.valid_until,
        }
    config = read_config(args.config)
    with IBKRGateway(config) as broker:
        if args.command == "init":
            execution.initialize(store, broker, config)
            return execution.summary(execution.reconcile(store, broker))
        if args.command == "reconcile":
            return execution.summary(execution.reconcile(store, broker))
        action = execution.submit if args.command == "submit" else execution.cancel
        return execution.summary(action(store, broker, args.intent_id))


def main() -> None:
    args = parser().parse_args()
    try:
        result = run(args)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"IBKR operation failed: {error}") from None
    print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
