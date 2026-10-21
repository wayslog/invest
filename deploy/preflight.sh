#!/usr/bin/env bash
# Read-only: no files, users, services or account state are changed.
set -euo pipefail
fail() { echo "DEPLOY_ERROR: $1" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'SSH user must be root for systemd deployment'
[[ $(uname -s) == Linux && -d /run/systemd/system ]] || fail 'A running Linux systemd host is required'
for tool in bash tar sha256sum flock runuser useradd install uv; do
  command -v "$tool" >/dev/null || fail "Host is missing required tool $tool"
done
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || fail 'Host clock must be synchronized'
uv --version >/dev/null
systemctl --version >/dev/null
