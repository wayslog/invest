#!/usr/bin/env bash
# Install the tested M4 runtime separately and perform read-only IBKR captures.
set -euo pipefail
umask 077
incoming=$1
commit=$2
run=$3
release="/opt/invest-ibkr/releases/$commit"
state=/var/lib/invest/ibkr
install -d -m 755 /opt/invest-ibkr /opt/invest-ibkr/releases
install -d -o invest -g invest -m 700 "$state" "$state/captures" "$state/logs"
log="$state/logs/$run.log"
trap 'echo "IBKR_CAPTURE_ERROR: see the protected M4 capture log" >&2' ERR
if [[ ! -d "$release" ]]; then
    install -d -m 755 "$release"
    tar -xzf "$incoming/source.tar.gz" --strip-components=1 -C "$release"
    chmod -R a+rX "$release"
fi
python=$(readlink -f /opt/invest/current/.venv/bin/python)
(umask 022; UV_CACHE_DIR=/opt/invest-ibkr/cache uv sync --project "$release/integrations/ibkr" \
    --locked --python "$python") >>"$log" 2>&1
runuser -u invest -- "$release/integrations/ibkr/.venv/bin/python" - "$release" "$state" 2>>"$log" <<'PY'
import json
import sys
from pathlib import Path

release, state = map(Path, sys.argv[1:])
sys.path.insert(0, str(release / "src"))
from invest.ibkr_cli import parser, run

for name, size, duration in (("daily", "1 day", "1 Y"), ("minute", "1 min", "5 D")):
    arguments = parser().parse_args([
        "capture", "--config", str(release / "configs/ibkr.toml"),
        "--output", str(state / "captures" / name), "--bar-size", size, "--duration", duration,
    ])
    result = run(arguments)
    print(json.dumps({"kind": name, **result}, default=str, sort_keys=True), flush=True)
PY
