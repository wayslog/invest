#!/usr/bin/env bash
# Read-only operational summary. Full account data and logs remain on the host.
set -euo pipefail
current=$(readlink -f /opt/invest/current)
printf 'Release: %s\n' "${current##*/}"
for unit in invest-forward.service invest-forward.timer invest-forward-health.service \
  invest-forward-health.timer invest-forward-notify-test.service invest-forward-failure.service; do
  systemctl show "$unit" --property=Id,LoadState,ActiveState,UnitFileState,Result,ExecMainStatus,NextElapseUSecRealtime,LastTriggerUSec
done
runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
  "$current/.venv/bin/python" - <<'PY'
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from invest.forward import forward_status, verify_forward

account = Path("/var/lib/invest/account")
observed_at = datetime.now(UTC)
status = forward_status(account)
summary = {key: status[key] for key in (
    "mode", "operations", "risk_status", "engine_matches", "sessions", "missing_sessions",
    "last_session", "registered_sessions", "observation_end_session", "decision_sessions",
    "fills", "pending_orders", "coverage_met", "next_capture_after", "decision_deadline",
) if key in status}
summary["observed_at"] = observed_at
try:
    verify_forward(account)
    summary["accounting_verified"] = True
except (OSError, ValueError):
    summary["accounting_verified"] = False
print("Account:", json.dumps(summary, default=str, sort_keys=True))
timers = {}
for name, unit in (("daily", "invest-forward.timer"), ("health", "invest-forward-health.timer")):
    for state, command in (("active", "is-active"), ("enabled", "is-enabled")):
        timers[name + "_" + state] = subprocess.run(
            ["systemctl", command, "--quiet", unit], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False,
        ).returncode == 0
print("Timers:", json.dumps(timers, sort_keys=True))
latest = {}
for directory in ("runs", "alerts", "health", "deployments"):
    records = sorted((account.parent / "operations" / directory).glob("*.parquet"))
    if not records:
        print(directory + ": no records")
        continue
    rows = [row for path in records[-20:] for row in pq.read_table(path).to_pylist()]
    row = max(rows, key=lambda item: item.get("recorded_at", item.get("finished_at")))
    latest[directory] = row
    fields = ("recorded_at", "started_at", "finished_at", "outcome", "healthy", "delivery",
              "notification", "updated", "sessions", "missing_sessions", "reconciliation_checks",
              "run", "commit")
    print(directory + ":", json.dumps({key: row[key] for key in fields if key in row},
                                     default=str, sort_keys=True))
backup = {"present": False, "matches_current": False}
if latest.get("runs", {}).get("backup"):
    location = Path(latest["runs"]["backup"]) / "backup.parquet"
    backup["present"] = location.is_file()
    if backup["present"]:
        row = pq.read_table(location).to_pylist()[0]
        backup["matches_current"] = row["head"] == status["head"]
print("Backup:", json.dumps(backup, sort_keys=True))

def recent(directory):
    rows = []
    for path in reversed(sorted((account.parent / "operations" / directory).glob("*.parquet"))):
        row = pq.read_table(path).to_pylist()[0]
        recorded = row.get("finished_at", row.get("recorded_at"))
        if recorded < observed_at - timedelta(hours=24):
            break
        rows.append(row)
    return rows

runs, alerts, health = recent("runs"), recent("alerts"), recent("health")
window = {
    "runs": len(runs), "updated_runs": sum(bool(row["updated"]) for row in runs),
    "failed_runs": sum(row["outcome"] != "ok" for row in runs),
    "systemd_failures": sum(row["kind"] == "systemd" for row in alerts),
    "health_failures": sum(not row["healthy"] for row in health),
    "notification_failures": sum(row["delivery"] == "failed" for row in alerts),
}
print("Window:", json.dumps(window, sort_keys=True))
PY
