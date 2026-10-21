"""Read sealed historical results to explain risk, exposure and economic attribution."""

import hashlib
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from invest.datasets import checksum
from invest.market import MONEY
from invest.research_registry import seal, verify_inventory, write_table

DIAGNOSTIC_SCHEMA = pa.schema(
    [
        ("phase", pa.string()),
        ("candidate", pa.string()),
        ("kind", pa.string()),
        ("cost_multiplier", pa.int64()),
        ("gap_bps", pa.int64()),
        ("first_session", pa.date32()),
        ("last_session", pa.date32()),
        ("sessions", pa.int64()),
        ("active_sessions", pa.int64()),
        ("zero_exposure_sessions", pa.int64()),
        ("first_risk_change", pa.date32()),
        ("risk_change", pa.string()),
        ("ending_status", pa.string()),
        ("total_return", pa.float64()),
        ("max_drawdown", pa.float64()),
        ("ending_equity", MONEY),
        ("trades", pa.int64()),
        ("commissions", MONEY),
        ("reconciliation_checks", pa.int64()),
        ("reconciliation_errors", pa.int64()),
        ("equity_sha256", pa.string()),
        ("positions_sha256", pa.string()),
        ("trades_sha256", pa.string()),
    ]
)


def _table_hash(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as stream:
        stream.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def diagnose_study(study: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Diagnostic output exists; preserve previous evidence")
    verify_inventory(study)
    manifest = pq.read_table(study / "manifest.parquet").to_pylist()[0]
    rows, attributions, reasons = [], [], []
    for comparison in pq.read_table(study / "comparison.parquet").to_pylist():
        directory = study / comparison["run"]
        equity = pq.read_table(directory / "equity.parquet")
        snapshots = equity.to_pylist()
        events = pq.read_table(directory / "events.parquet").to_pylist()
        risk = [event for event in events if event["kind"] == "risk_state"]
        trades = pq.read_table(directory / "trades.parquet")
        reconciliation = pq.read_table(directory / "reconciliation.parquet")
        rows.append(
            {
                "phase": comparison["phase"],
                "candidate": comparison["candidate"],
                "kind": comparison["kind"],
                "cost_multiplier": comparison["cost_multiplier"],
                "gap_bps": comparison["gap_bps"],
                "first_session": snapshots[0]["date"],
                "last_session": snapshots[-1]["date"],
                "sessions": len(snapshots),
                "active_sessions": sum(row["status"] == "active" for row in snapshots),
                "zero_exposure_sessions": sum(row["market_value"] == 0 for row in snapshots),
                "first_risk_change": risk[0]["date"] if risk else None,
                "risk_change": risk[0]["detail"] if risk else "",
                "ending_status": snapshots[-1]["status"],
                "total_return": comparison["total_return"],
                "max_drawdown": comparison["max_drawdown"],
                "ending_equity": snapshots[-1]["equity"],
                "trades": trades.num_rows,
                "commissions": sum(trades["commission"].to_pylist(), Decimal(0)),
                "reconciliation_checks": reconciliation.num_rows,
                "reconciliation_errors": reconciliation["status"].to_pylist().count("error"),
                "equity_sha256": _table_hash(equity),
                "positions_sha256": _table_hash(pq.read_table(directory / "positions.parquet")),
                "trades_sha256": _table_hash(trades),
            }
        )
        attribution = pq.read_table(directory / "attribution.parquet").to_pylist()
        for row in attribution:
            if row["date"] == snapshots[-1]["date"]:
                attributions.append(
                    {
                        "phase": comparison["phase"],
                        "candidate": comparison["candidate"],
                        "cost_multiplier": comparison["cost_multiplier"],
                        "gap_bps": comparison["gap_bps"],
                        **row,
                    }
                )
        for reason, count in Counter(
            pq.read_table(directory / "orders.parquet")["reason"].to_pylist()
        ).items():
            reasons.append(
                {
                    "phase": comparison["phase"],
                    "candidate": comparison["candidate"],
                    "cost_multiplier": comparison["cost_multiplier"],
                    "gap_bps": comparison["gap_bps"],
                    "reason": reason,
                    "orders": count,
                }
            )
    output.mkdir(parents=True)
    write_table(pa.Table.from_pylist(rows, schema=DIAGNOSTIC_SCHEMA), output / "runs.parquet")
    write_table(pa.Table.from_pylist(attributions), output / "attribution.parquet")
    write_table(pa.Table.from_pylist(reasons), output / "order-reasons.parquet")
    write_table(
        pa.Table.from_pylist(
            [
                {
                    "study_id": manifest["study_id"],
                    "study_head": checksum(study / "files.parquet"),
                    "historical_engine_sha256": manifest["engine_sha256"],
                    "diagnosed_at": datetime.now(UTC),
                    "basis": "sealed_historical_outputs; "
                    "no new qualification or changed-engine replay",
                }
            ]
        ),
        output / "lineage.parquet",
    )
    seal(output)
    return {
        "output": str(output),
        "runs": len(rows),
        "reconciliation_errors": sum(r["reconciliation_errors"] for r in rows),
    }
