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
import ast
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import invest

from invest.forward import forward_status, verify_forward

account = Path("/var/lib/invest/account")
try:
    from invest.forward_service import read_service_config, service_status, service_verify
except ImportError:
    config = None  # Older archived releases predate the IBKR cash backend.
else:
    config_file = Path("/etc/invest/operations.toml")
    config = read_service_config(config_file) if config_file.is_file() else None
if config is not None:
    account = config.account
observed_at = datetime.now(UTC)
status = service_status(config) if config is not None else forward_status(account)
summary = {key: status[key] for key in (
    "mode", "operations", "risk_status", "engine_matches", "sessions", "missing_sessions",
    "last_session", "registered_sessions", "observation_end_session", "decision_sessions",
    "fills", "pending_orders", "coverage_met", "next_capture_after", "decision_deadline",
    "source", "observation_start_session", "missed_sessions",
) if key in status}
summary["observed_at"] = observed_at
try:
    if config is not None:
        service_verify(config)
    else:
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

# Only report matching public source literals; never echo a private error string.
error = str(latest.get("runs", {}).get("error", ""))
matches = []
for source in Path(invest.__file__).parent.glob("*.py"):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if 12 <= len(text) <= 240 and text in error:
                matches.append((len(text), source.name, text))
matched = max(matches, default=(0, "", "unclassified"))
print("Run diagnostic:", json.dumps({"source": matched[1], "public_message": matched[2]}, sort_keys=True))

for kind in ("daily", "minute"):
    captures = sorted(Path("/var/lib/invest/ibkr/captures", kind).glob("*/capture.parquet"))
    if not captures:
        continue
    folder = captures[-1].parent
    manifest = pq.read_table(captures[-1]).to_pylist()[0]
    account_number = manifest["account"]
    messages = []
    for row in pq.read_table(folder / "raw.parquet").to_pylist():
        if row["method"] == "errorEvent" and not row["complete"]:
            body = json.loads(row["payload"])
            message = str(body["message"]).replace(account_number, "<paper-account>")
            message = re.sub(r"\bDU[A-Z0-9_]+\b", "<paper-account>", message)
            messages.append({"code": body["code"], "message": message})
    print("IBKR " + kind + ":", json.dumps({
        "captured_at": manifest["captured_at"], "complete": manifest["complete"],
        "errors": messages,
    }, default=str, sort_keys=True))
PY
