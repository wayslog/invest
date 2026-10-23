#!/usr/bin/env bash
# One user-authorized restart: preserve the legacy account and activate a new IBKR cash observation.
set -euo pipefail
umask 077
incoming=${1:?} commit=${2:?} run=${3:?}
fail() { echo "DEPLOY_ERROR: $1" >&2; exit 1; }
[[ $incoming =~ ^/opt/invest/incoming/[0-9]+-[0-9]+$ && $run =~ ^[0-9]+-[0-9]+$ ]] || fail 'Invalid staging path'
[[ $commit =~ ^[0-9a-f]{40}$ && $(id -u) == 0 ]] || fail 'Invalid restart deployment identity'
install -d -m 0755 /opt/invest/releases
exec 9>/opt/invest/.deployment.lock
flock -n 9 || fail 'Another host deployment holds the lock'
phase=prepare
quiesced=0 activated=0 primary_was_active=0 health_was_active=0
finish() {
  result=$?
  set +e
  if (( result != 0 )); then
    echo "DEPLOY_ERROR: cash restart failed during $phase; inspect protected host logs" >&2
    log_dir=/opt/invest/deployment-logs/$run
    install -d -m 0700 "$log_dir"
    printf '%s\n' "$phase" >"$log_dir/failed-phase.log"
    for log in "$incoming"/*.log; do
      [[ ! -f $log ]] || install -m 0600 "$log" "$log_dir/"
    done
    if (( activated )); then
      systemctl disable --now invest-forward.timer invest-forward-health.timer || true
    elif (( quiesced )); then
      (( primary_was_active == 0 )) || systemctl start invest-forward.timer || true
      (( health_was_active == 0 )) || systemctl start invest-forward-health.timer || true
    fi
  fi
  exit "$result"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
tar --no-same-owner -xzf "$incoming/payload.tar.gz" -C "$incoming"
[[ -f $incoming/restart.toml ]] || fail 'Missing authorized cash restart request'
release=/opt/invest/releases/$commit
if [[ ! -f $release/.source-ready ]]; then
  install -d -m 0755 "$release"
  (umask 022; tar --no-same-owner -xzf "$incoming/source.tar.gz" --strip-components=1 -C "$release")
  touch "$release/.source-ready"
fi
export UV_PYTHON_INSTALL_DIR=/opt/invest/python UV_CACHE_DIR=/opt/invest/uv-cache
# A failed sync can leave .venv behind; a locked sync must finish on every retry.
(umask 022; cd "$release" && uv sync --locked --no-dev --python 3.12 --managed-python) >"$incoming/install.log" 2>&1
python=$release/.venv/bin/python
[[ $(readlink -f "$python") == /opt/invest/python/* ]] || fail 'Service Python must be under opt invest python'
(umask 022; UV_CACHE_DIR=/opt/invest-ibkr/cache uv sync --project "$release/integrations/ibkr" \
  --locked --python "$(readlink -f "$python")") >>"$incoming/install.log" 2>&1
id invest >/dev/null 2>&1 || fail 'Existing deployment service user is required'
[[ -s /etc/invest/invest.env || -s $incoming/invest.env ]] || fail 'Telegram runtime credentials are missing'
for name in restarts archives cache; do
  install -d -m 0700 -o invest -g invest "/var/lib/invest/$name"
done
request=/var/lib/invest/restarts/restart-request-$run.toml
install -m 0600 -o invest -g invest "$incoming/restart.toml" "$request"
phase=initialize
runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
  "$python" "$release/deploy/restart.py" prepare --release "$release" --metadata "$request" \
  >"$incoming/initialize.log" 2>&1
phase=quiesce
systemctl is-active --quiet invest-forward.timer && primary_was_active=1
systemctl is-active --quiet invest-forward-health.timer && health_was_active=1
quiesced=1
systemctl stop invest-forward.timer invest-forward-health.timer
deadline=$((SECONDS + 960))
for service in invest-forward.service invest-forward-health.service invest-forward-failure.service invest-forward-notify-test.service; do
  while [[ $(systemctl show -p ActiveState --value "$service" 2>/dev/null || true) =~ ^(active|activating|deactivating|reloading)$ ]]; do
    (( SECONDS < deadline )) || fail 'Existing writer did not finish; no forced termination was attempted'
    sleep 2
  done
done
phase=handover
activated=1
runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
  "$python" "$release/deploy/restart.py" activate --release "$release" >"$incoming/handover.log" 2>&1
phase=activate
if [[ -s $incoming/invest.env ]]; then
  install -m 0600 -o root -g root "$incoming/invest.env" /etc/invest/.invest.env.next
  mv -T /etc/invest/.invest.env.next /etc/invest/invest.env
fi
install -m 0640 -o root -g invest "$release/deploy/operations-ibkr.toml" /etc/invest/operations.toml
ln -s "$release" "/opt/invest/.current.$$"
mv -Tf "/opt/invest/.current.$$" /opt/invest/current
install -m 0644 "$release"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl reset-failed invest-forward.service invest-forward-health.service invest-forward-failure.service || true
phase=validate
systemctl start invest-forward-notify-test.service
systemctl start invest-forward.service
systemctl start invest-forward-health.service
phase=receipt
runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
  "$python" "$release/deploy/restart.py" receipt --release "$release" --run "$run" >"$incoming/receipt.log" 2>&1
phase=enable_timers
systemctl enable --now invest-forward.timer invest-forward-health.timer
