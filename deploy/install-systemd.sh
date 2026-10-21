#!/usr/bin/env bash
# Install a quiesced release. CI also pins account identity, head and engine first.
set -euo pipefail

release_dir=${1:?Usage: bash deploy/install-systemd.sh /opt/invest/releases/RELEASE [--defer-timers]}
if (( $# > 2 )) || [[ -n ${2:-} && ${2:-} != --defer-timers ]]; then
  echo 'Unknown installation option' >&2
  exit 1
fi
case "$release_dir" in
  /opt/invest/releases/*) ;;
  *) echo 'Release must be under /opt/invest/releases' >&2; exit 1 ;;
esac
if [[ $(id -u) != 0 ]]; then
  echo 'System service installation requires root on the deployment host' >&2
  exit 1
fi
if [[ ! -x "$release_dir/.venv/bin/invest" || ! -d /var/lib/invest/account/journal ]]; then
  echo 'Install the locked release and transfer the existing account first' >&2
  exit 1
fi
if [[ ! -s /etc/invest/invest.env || -L /etc/invest/invest.env ]]; then
  echo 'Provision /etc/invest/invest.env securely; never pass secrets as arguments' >&2
  exit 1
fi
if systemctl is-active --quiet invest-forward.timer || systemctl is-active --quiet invest-forward.service \
  || systemctl is-active --quiet invest-forward-health.timer || systemctl is-active --quiet invest-forward-health.service; then
  echo 'Stop the existing writer and follow the version migration procedure before deployment' >&2
  exit 1
fi
if [[ $(timedatectl show -p NTPSynchronized --value) != yes ]]; then
  echo 'Host clock must be synchronized before recording real observation times' >&2
  exit 1
fi
if ! id invest >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/invest --shell /usr/sbin/nologin invest
fi
install -d -m 0750 -o root -g invest /etc/invest
install -d -m 0700 -o invest -g invest /var/lib/invest
for name in data backups operations cache; do
  install -d -m 0700 -o invest -g invest "/var/lib/invest/$name"
done
chown -R invest:invest /var/lib/invest/account
chown root:root /etc/invest/invest.env
chmod 0600 /etc/invest/invest.env
install -m 0640 -o root -g invest "$release_dir/deploy/operations.toml" /etc/invest/operations.toml
runuser -u invest -- env MPLCONFIGDIR=/var/lib/invest/cache/matplotlib \
  "$release_dir/.venv/bin/invest" forward-verify --account /var/lib/invest/account
ln -s "$release_dir" "/opt/invest/.current.$$"
mv -Tf "/opt/invest/.current.$$" /opt/invest/current
install -m 0644 "$release_dir"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
# A verified Telegram receipt and durable first run are deployment gates.
systemctl start invest-forward-notify-test.service
systemctl start invest-forward.service
systemctl start invest-forward-health.service
if [[ ${2:-} != --defer-timers ]]; then
  systemctl enable --now invest-forward.timer invest-forward-health.timer
  systemctl list-timers invest-forward.timer invest-forward-health.timer --no-pager
fi
