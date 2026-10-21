#!/usr/bin/env bash
# Only the public certificate leaves the host. The temporary private key stays root-only.
set -euo pipefail
umask 077
fail() { echo "DEPLOY_ERROR: $1" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'Handover preparation requires root'
command -v openssl >/dev/null || fail 'OpenSSL is required for encrypted handover'
install -d -m 0755 /opt/invest
exec 9>/opt/invest/.deployment.lock
flock -n 9 || fail 'Another host deployment holds the lock'
[[ ! -e /var/lib/invest/account && ! -L /var/lib/invest/account ]] \
  || fail 'The host already has an account; use normal deployment'
directory=/opt/invest/bootstrap
[[ ! -L $directory ]] || fail 'Invalid bootstrap directory'
install -d -m 0700 "$directory"
key=$directory/handoff.key certificate=$directory/handoff.pem
if [[ -e $key || -e $certificate || -L $key || -L $certificate ]]; then
  [[ -f $key && -f $certificate && ! -L $key && ! -L $certificate ]] \
    || fail 'Incomplete handover key material; inspect protected host files'
else
  # OAEP and authenticated AES-GCM are used by the client; no account or runtime secrets here.
  openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 2 \
    -subj /CN=invest-account-handoff -keyout "$key" -out "$certificate" \
    >"$directory/key-generation.log" 2>&1 \
    || fail 'Handover certificate generation failed; inspect protected host logs'
fi
chmod 0600 "$key" "$certificate"
openssl x509 -in "$certificate" -noout -checkend 0 >/dev/null \
  || fail 'The handover certificate expired; inspect protected host files'
cat "$certificate"
