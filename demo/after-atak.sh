#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Footprint and self-healing, recorded (asciinema) after the ATAK chapter so
# the ATAK test device is connected: live CPU and memory from the kubelet,
# the package size, then TAK's messaging pod is deleted and the device's
# connection is checked again. demo/render-cast.py splits it at the prompts.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
domain="${DOMAIN:-uds.dev}"
device="${ATAK_DEVICE_USER:-atak-device}"
k() { uds zarf tools kubectl "$@"; }
prompt() { printf '\n\033[38;5;141muds-k3d-takserver\033[0m \033[38;5;245m$\033[0m %s\n' "$*"; }
run() {
  prompt "$*"
  "$@"
}

# TAK's admin API through the gateway, with the deploy-time admin certificate
# (tests/extract-certs.sh), as atak/ci/e2e.sh checks the device.
certs="$(bash tests/extract-certs.sh /tmp/demo-certs | tail -n 1)"
key_pass="$(bash tests/keystore-pass.sh)"
k -n istio-passthrough-gateway port-forward svc/passthrough-ingressgateway 28443:443 >/tmp/demo-pf.log 2>&1 &
pf=$!
trap 'kill "${pf}" 2>/dev/null || true' EXIT
sleep 3
device_status() {
  local endpoints
  endpoints="$(curl -k -sS --max-time 20 --cert "${certs}/admin.pem" --key "${certs}/admin.key" --pass "${key_pass}" \
    --resolve "takserver-api.${domain}:28443:127.0.0.1" \
    "https://takserver-api.${domain}:28443/Marti/api/clientEndPoints")"
  python3 -c 'import json,sys
for c in json.load(sys.stdin)["data"]:
    if c.get("username") == sys.argv[1]:
        print(c["callsign"], c["lastStatus"], "last event", c["lastEventTime"])' "${device}" <<< "${endpoints}"
}
usage() {
  k get --raw "/api/v1/nodes/$(k get nodes -o name | head -n 1 | cut -d/ -f2)/proxy/stats/summary" |
    python3 -c 'import json,sys
rows = [(p["podRef"]["name"], p.get("cpu", {}).get("usageNanoCores", 0) / 1e6, p.get("memory", {}).get("workingSetBytes", 0) / 2**20)
        for p in json.load(sys.stdin)["pods"] if p["podRef"]["namespace"] == "takserver"]
for name, cpu, mem in sorted(rows):
    print(f"{name:48} {cpu:6.0f}m {mem:7.0f}Mi")
print("total".ljust(48), f"{sum(r[1] for r in rows):6.0f}m {sum(r[2] for r in rows):7.0f}Mi")'
}

prompt "kubectl get --raw /api/v1/nodes/NODE/proxy/stats/summary   # TAK pods: CPU and memory now"
usage
run ls -lh zarf-package-takserver-amd64-*-upstream.tar.zst
prompt "curl https://takserver-api.${domain}/Marti/api/clientEndPoints   # the ATAK test device"
before="$(device_status)"
echo "${before}"
prompt "kubectl delete pod -n takserver -l app=takserver-messaging && kubectl wait pod -n takserver -l app=takserver-messaging --for=condition=Ready"
echo "deleted at $(date -u +%T) UTC"
k delete pod -n takserver -l app=takserver-messaging
k wait pod -n takserver -l app=takserver-messaging --for=condition=Ready --timeout=900s
echo "ready at $(date -u +%T) UTC"
prompt "curl https://takserver-api.${domain}/Marti/api/clientEndPoints   # until ATAK reconnects by itself"
for _ in $(seq 1 60); do
  line="$(device_status || true)"
  echo "$(date -u +%T) UTC  ${line}"
  [[ "${line}" == *Connected* ]] && [[ "${line}" != "${before}" ]] && break
  sleep 10
done
prompt ""
