#!/usr/bin/env bash
# Invoked through SSH by the trusted workflow. No secrets in argv or stdout.
set -euo pipefail
umask 077
incoming=${1:?} payload_sha=${2:?} source_sha=${3:?} commit=${4:?} run=${5:?}
fail() { echo "DEPLOY_ERROR: $1" >&2; exit 1; }
[[ $incoming =~ ^/opt/invest/incoming/[0-9]+-[0-9]+$ && $run =~ ^[0-9]+-[0-9]+$ ]] || fail 'Invalid staging path'
[[ $commit =~ ^[0-9a-f]{40}$ ]] || fail 'Invalid deployment identity'
for value in "$payload_sha" "$source_sha"; do
  [[ $value =~ ^[0-9a-f]{64}$ ]] || fail 'Invalid deployment checksum'
done
[[ $(id -u) == 0 && -d $incoming && ! -L $incoming ]] || fail 'Invalid deployment staging directory'
install -d -m 0755 /opt/invest/releases
exec 9>/opt/invest/.deployment.lock
flock -n 9 || fail 'Another host deployment holds the lock'
phase=prepare
quiesced=0 activated=0 primary_was_active=0 health_was_active=0
finish() {
  result=$?
  set +e  # Failure to save diagnostics must not skip timer recovery or containment.
  if (( result != 0 )); then
    echo "DEPLOY_ERROR: deployment failed during $phase; inspect protected host logs" >&2
    log_dir=/opt/invest/deployment-logs/$run
    install -d -m 0700 "$log_dir"
    printf '%s\n' "$phase" >"$log_dir/failed-phase.log"
    for log in "$incoming"/*.log; do
      [[ ! -f $log ]] || install -m 0600 "$log" "$log_dir/"
    done
    if (( activated )); then
      # New daily events may already exist. Never roll account files or code backwards.
      systemctl disable --now invest-forward.timer invest-forward-health.timer || true
      systemctl start invest-forward-failure.service || true
    elif (( quiesced )); then
      (( primary_was_active == 0 )) || systemctl start invest-forward.timer || true
      (( health_was_active == 0 )) || systemctl start invest-forward-health.timer || true
    fi
  fi
  exit "$result"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM
[[ $(sha256sum "$incoming/payload.tar.gz" | cut -d' ' -f1) == "$payload_sha" ]] || fail 'Payload checksum mismatch'
tar --no-same-owner -xzf "$incoming/payload.tar.gz" -C "$incoming"
[[ $(sha256sum "$incoming/source.tar.gz" | cut -d' ' -f1) == "$source_sha" ]] || fail 'Source checksum mismatch'
release=/opt/invest/releases/$commit
if [[ -e $release || -L $release ]]; then
  [[ -f $release/.source-sha256 && ! -L $release ]] || fail 'Existing release is incomplete; inspect before retrying'
  [[ $(cat "$release/.source-sha256") == "$source_sha" ]] || fail 'Immutable release checksum mismatch'
else
  mkdir -m 0755 "$release"
  tar --no-same-owner -xzf "$incoming/source.tar.gz" --strip-components=1 -C "$release"
  # Managed Python lives outside root HOME, which the service sandbox deliberately hides.
  export UV_PYTHON_INSTALL_DIR=/opt/invest/python UV_CACHE_DIR=/opt/invest/uv-cache
  (umask 022; cd "$release" && uv sync --locked --no-dev --python 3.12 --managed-python) >"$incoming/install.log" 2>&1
  chmod 0755 "$release"
  printf '%s\n' "$source_sha" >"$release/.source-sha256"
  chmod 0644 "$release/.source-sha256"
fi
python=$release/.venv/bin/python
[[ $(readlink -f "$python") == /opt/invest/python/* ]] || fail 'Service Python must be under opt invest python'
if ! id invest >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/invest --shell /usr/sbin/nologin invest
fi
install -d -m 0700 -o invest -g invest /var/lib/invest
for name in data backups operations cache; do
  install -d -m 0700 -o invest -g invest "/var/lib/invest/$name"
done
install -d -m 0750 -o root -g invest /etc/invest
export MPLCONFIGDIR=/var/lib/invest/cache/matplotlib
account=/var/lib/invest/account
bootstrap=0 encrypted_handoff=0
if [[ -e $account || -L $account ]]; then
  [[ -d $account/journal && ! -L $account ]] || fail 'Existing account path is invalid'
else
  bootstrap=1
  phase=verify_bootstrap
  if [[ -f $incoming/account.cms ]]; then
    [[ -f /opt/invest/bootstrap/handoff.key && ! -L /opt/invest/bootstrap/handoff.key \
      && -f /opt/invest/bootstrap/handoff.pem && ! -L /opt/invest/bootstrap/handoff.pem ]] \
      || fail 'Prepare the encrypted handover recipient first'
    openssl cms -decrypt -binary -inform DER -in "$incoming/account.cms" \
      -recip /opt/invest/bootstrap/handoff.pem -inkey /opt/invest/bootstrap/handoff.key \
      -out "$incoming/account.tar.gz" >"$incoming/decrypt.log" 2>&1 \
      || fail 'Encrypted account authentication failed'
    chmod 0600 "$incoming/account.tar.gz"
    encrypted_handoff=1
  fi
  archive=$incoming/account.tar.gz
  if [[ ! -f $archive ]]; then archive=/opt/invest/bootstrap/account.tar.gz; fi
  [[ -f $archive && ! -L $archive ]] || fail 'Supply the private existing account archive before handover'
  "$python" "$release/deploy/release.py" extract-account "$archive" "$incoming/bootstrap"
  identity=$("$python" "$release/deploy/release.py" identity "$incoming/bootstrap/account" 2>"$incoming/verify.log")
  read -r account_id expected_head <<< "$identity"
fi
if [[ ! -s $incoming/invest.env && ! -s /etc/invest/invest.env ]]; then
  fail 'Runtime and Telegram credentials must be provisioned before deployment'
fi
[[ ! -L /etc/invest/invest.env ]] || fail 'The runtime EnvironmentFile must not be a symlink'
phase=quiesce
systemctl is-active --quiet invest-forward.timer && primary_was_active=1
systemctl is-active --quiet invest-forward-health.timer && health_was_active=1
quiesced=1
systemctl stop invest-forward.timer invest-forward-health.timer 2>/dev/null || {
  # Only tolerate missing units, never a broken systemd connection or failed stop.
  for timer in invest-forward.timer invest-forward-health.timer; do
    [[ $(systemctl show -p LoadState --value "$timer" 2>/dev/null || true) == not-found ]] \
      || fail 'Could not stop the existing timers'
  done
}
deadline=$((SECONDS + 960))
for service in invest-forward.service invest-forward-health.service invest-forward-failure.service invest-forward-notify-test.service; do
  while [[ $(systemctl show -p ActiveState --value "$service" 2>/dev/null || true) =~ ^(active|activating|deactivating|reloading)$ ]]; do
    (( SECONDS < deadline )) || fail 'Existing writer did not finish; no forced termination was attempted'
    sleep 2
  done
done
phase=handover
if (( bootstrap )); then
  [[ ! -e $account && ! -L $account ]] || fail 'An account appeared during handover; it was not overwritten'
  # No-clobber also protects an unexpected account created since bootstrap verification.
  mv -nT "$incoming/bootstrap/account" "$account"
  [[ ! -e $incoming/bootstrap/account ]] || fail 'An account appeared during handover; it was not overwritten'
  chown -R invest:invest "$account"
else
  # Discover the current account only after the previous daily task has finished.
  identity=$(runuser -u invest -- "$python" "$release/deploy/release.py" identity "$account" 2>"$incoming/verify.log")
  read -r account_id expected_head <<< "$identity"
fi
[[ $account_id =~ ^[0-9a-f]{32}$ && $expected_head =~ ^[0-9a-f]{64}$ ]] || fail 'Invalid account journal identity'
runuser -u invest -- "$python" "$release/deploy/release.py" verify "$account" "$account_id" "$expected_head" >"$incoming/verify.log" 2>&1
runuser -u invest -- "$release/.venv/bin/invest" forward-backup --account "$account" \
  --output "/var/lib/invest/backups/deploy-$run" >"$incoming/backup.log" 2>&1
runuser -u invest -- "$python" "$release/deploy/release.py" verify "$account" "$account_id" "$expected_head" >"$incoming/verify.log" 2>&1
phase=activate
activated=1
if [[ -s $incoming/invest.env ]]; then
  install -m 0600 -o root -g root "$incoming/invest.env" /etc/invest/.invest.env.next
  mv -T /etc/invest/.invest.env.next /etc/invest/invest.env
fi
bash "$release/deploy/install-systemd.sh" "$release" --defer-timers >"$incoming/activate.log" 2>&1
phase=receipt
# Record after the first daily task, while all timers remain quiescent.
runuser -u invest -- "$python" "$release/deploy/release.py" receipt "$account" "$account_id" "$expected_head" "$release" "$run"
phase=enable_timers
systemctl enable --now invest-forward.timer invest-forward-health.timer
if (( encrypted_handoff )); then
  # The transferred ciphertext is no longer decryptable with any long-lived SSH credential.
  rm -f /opt/invest/bootstrap/handoff.key /opt/invest/bootstrap/handoff.pem
fi
