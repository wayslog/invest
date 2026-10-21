#!/usr/bin/env bash
# Public recipient certificate is prefixed by the caller. All host output is encrypted.
set -euo pipefail
umask 077
recipient_base64=${recipient_base64:?Public recipient certificate is required}
work=$(mktemp -d /opt/invest/inspection.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
printf '%s' "$recipient_base64" | base64 -d >"$work/recipient.pem"
mkdir "$work/files"
for unit in invest-forward.service invest-forward.timer invest-forward-health.service \
  invest-forward-health.timer invest-forward-notify-test.service invest-forward-failure.service; do
  systemctl show "$unit" --property=Id,LoadState,ActiveState,UnitFileState,Result,ExecMainStatus,NextElapseUSecRealtime,LastTriggerUSec \
    >"$work/files/$unit.txt" 2>&1 || true
done
journalctl -u invest-forward.service -u invest-forward-health.service \
  -u invest-forward-notify-test.service -u invest-forward-failure.service \
  -n 120 --no-pager --output=short-iso >"$work/files/journal.txt" 2>&1 || true
if [[ -d /opt/invest/deployment-logs ]]; then
  while IFS= read -r log; do
    name=$(basename "$(dirname "$log")")-$(basename "$log")
    tail -n 100 "$log" >"$work/files/$name"
  done < <(find /opt/invest/deployment-logs -mindepth 2 -maxdepth 2 -type f -name '*.log' | sort | tail -n 20)
fi
for directory in runs alerts health deployments; do
  source=/var/lib/invest/operations/$directory
  if [[ -d $source ]]; then
    mkdir "$work/files/$directory"
    while IFS= read -r record; do
      cp -- "$record" "$work/files/$directory/"
    done < <(find "$source" -maxdepth 1 -type f -name '*.parquet' | sort | tail -n 20)
  fi
done
if [[ -x /opt/invest/current/.venv/bin/invest && -d /var/lib/invest/account/journal ]]; then
  readlink -f /opt/invest/current >"$work/files/current.txt"
  for operation in forward-status forward-verify; do
    runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
      /opt/invest/current/.venv/bin/invest "$operation" --account /var/lib/invest/account \
      >"$work/files/$operation.json" 2>"$work/files/$operation.error" || true
  done
fi
tar -czf "$work/private.tar.gz" -C "$work/files" .
openssl cms -encrypt -binary -aes-256-gcm -recip "$work/recipient.pem" \
  -keyopt rsa_padding_mode:oaep -keyopt rsa_oaep_md:sha256 -in "$work/private.tar.gz" \
  -out "$work/status.cms" -outform DER 2>"$work/encryption.log"
cat "$work/status.cms"
