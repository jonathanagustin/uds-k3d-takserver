#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# Called once by e2e.sh under its outer 475s timeout + 5s kill grace.
set -euo pipefail
umask 077
output="${1:?fresh scenario evidence directory}"
domain="${DOMAIN:-uds.dev}"
[[ "${domain}" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 2
work="$(mktemp -d "${RUNNER_TEMP:-/tmp}/atak-scenario.XXXXXX")"
name="atak-peer-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
k() { uds zarf tools kubectl --request-timeout=10s "$@"; }
cleanup() {
  result=$?
  trap - EXIT INT TERM
  rm -rf -- "${work}"
  cleanup_result=0
  # UI XML/receipts are sanitized before the existing artifact upload, also
  # on the first failed phase. Private PEMs never enter the evidence tree.
  if [[ -d "${output}" ]]; then
    while IFS= read -r -d '' file; do
      if ! python3 .github/scripts/redact-logs.py "${file}" >/dev/null 2>&1; then
        rm -f -- "${file}"
        cleanup_result=1
      fi
    done < <(find "${output}" -type f \( -name '*.xml' -o -name '*.json' \) -print0)
  fi
  timeout 2s uds zarf tools kubectl --request-timeout=1s delete takclient "${name}" -n takclients --ignore-not-found --wait=false >/dev/null 2>&1 || cleanup_result=1
  timeout 2s demo/atak-adb.sh stop >/dev/null 2>&1 || cleanup_result=1
  if [[ -d "${output}" ]]; then
    python3 - "${output}" "${cleanup_result}" <<'PY_CLEANUP'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]); ok=sys.argv[2]=='0'
(path/'cleanup.json').write_text(json.dumps({'cleanup_verified':ok})+'\n')
if not ok and (path/'receipt.json').exists():
    receipt=json.loads((path/'receipt.json').read_text())
    if receipt.get('status')!='failed': receipt['status']='failed-cleanup'
    (path/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
PY_CLEANUP
  fi
  if [[ "${result}" -eq 0 && "${cleanup_result}" -ne 0 ]]; then result=1; fi
  exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
prepare() {
# The same controller and server group as e2e.sh's ATAK device. The silent
# observer is not a contact; Android uses the actual Broadcast UI target.
k apply -f - >/dev/null <<YAML
apiVersion: tak.jonathanagustin.github.io/v1alpha1
kind: TakClient
metadata:
  name: ${name}
  namespace: takclients
spec:
  callsign: ${name}
  groups:
    - ${DEVICE_GROUP:-Operators}
  validityDays: 1
YAML
k wait takclient "${name}" -n takclients --for=condition=Ready --timeout=50s >/dev/null
for item in client.pem client.key ca.pem; do
  escaped="${item//./\\.}"
  k get secret "${name}" -n takclients -o "jsonpath={.data.${escaped}}" | base64 -d > "${work}/${item}"
  test -s "${work}/${item}"
done
# Authenticated deployment data is the pin authority, never the TLS wire.
k get secret takserver-certs -n takserver -o 'jsonpath={.data.takserver\.pem}' | base64 -d > "${work}/server.pem"
openssl x509 -in "${work}/server.pem" -outform DER | sha256sum | cut -d ' ' -f 1 > "${work}/pin"
python3 takx/mission-package/build_fixture.py --output "${work}/scenario.dpk" >/dev/null
}
# Bootstrap has its own aggregate deadline, including controller admission,
# secret reads, authenticated leaf extraction and deterministic fixture build.
export work name domain
export -f k prepare
timeout --signal=TERM --kill-after=2s 80s bash -euo pipefail -c prepare
read -r pin < "${work}/pin"
# e2e.sh owns the existing passthrough port-forward 28443:443. Streaming
# reaches 8089 through SNI takserver-stream.<domain>, with CA + exact leaf.
python3 -B atak/ci/interoperability.py --mission-package "${work}/scenario.dpk" \
  --output "${output}" --host "takserver-stream.${domain}" --port 28443 \
  --ca "${work}/ca.pem" --cert "${work}/client.pem" --key "${work}/client.key" \
  --server-leaf-sha256 "${pin}"
