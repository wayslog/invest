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
from pathlib import Path

import pyarrow.parquet as pq

from invest.forward import forward_status, verify_forward

account = Path("/var/lib/invest/account")
status = forward_status(account)
summary = {key: status[key] for key in (
    "mode", "operations", "risk_status", "engine_matches", "sessions", "missing_sessions",
    "last_session",
)}
try:
    verify_forward(account)
    summary["accounting_verified"] = True
except (OSError, ValueError):
    summary["accounting_verified"] = False
print("Account:", json.dumps(summary, default=str, sort_keys=True))
for directory in ("runs", "alerts", "health", "deployments"):
    records = sorted((account.parent / "operations" / directory).glob("*.parquet"))
    if not records:
        print(directory + ": no records")
        continue
    rows = [row for path in records[-20:] for row in pq.read_table(path).to_pylist()]
    row = max(rows, key=lambda item: item.get("recorded_at", item.get("finished_at")))
    fields = ("recorded_at", "started_at", "finished_at", "outcome", "healthy", "delivery",
              "notification", "updated", "sessions", "missing_sessions", "reconciliation_checks",
              "run", "commit")
    print(directory + ":", json.dumps({key: row[key] for key in fields if key in row},
                                     default=str, sort_keys=True))
PY
