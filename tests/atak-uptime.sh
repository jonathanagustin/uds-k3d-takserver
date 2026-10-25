#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Require a monitoring Probe for the ATAK viewer and probe_success 1.
# The ATAK e2e job deploys core-monitoring, then the device package, then this.
# Slim core alone has no Probe CRD, so a missing CRD is a failure here.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${root}"
mkdir -p out
log="out/atak-uptime.txt"
: > "${log}"

say() {
  printf '%s\n' "$*" | tee -a "${log}"
}

k() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

if ! k api-resources --api-group=monitoring.coreos.com 2>/dev/null | grep -q '^probes '; then
  say "monitoring.coreos.com Probe is not installed" >&2
  exit 1
fi

listed=0
for _ in $(seq 1 30); do
  k get probes.monitoring.coreos.com -n monitoring -o yaml >"${log}.list" 2>/dev/null || true
  if grep -q 'phone.html' "${log}.list" && grep -q 'atak' "${log}.list"; then
    listed=1
    break
  fi
  sleep 10
done
say "kubectl get probes -n monitoring"
# The list is large. Keep the phone.html documents.
awk '
  /^---$/ { if (keep) print buf; buf = $0 ORS; keep = 0; next }
  { buf = buf $0 ORS }
  /phone\.html/ { keep = 1 }
  END { if (keep) print buf }
' "${log}.list" | tee -a "${log}"
if [[ "${listed}" -ne 1 ]]; then
  say "no Probe for the ATAK viewer phone.html page" >&2
  exit 1
fi

if k get svc kube-prometheus-stack-prometheus -n monitoring >/dev/null 2>&1; then
  prom_svc="kube-prometheus-stack-prometheus"
  prom_port="9090"
else
  prom_svc="$(k get svc -n monitoring -o jsonpath='{.items[0].metadata.name}')"
  prom_port="$(k get svc -n monitoring "${prom_svc}" -o jsonpath='{.spec.ports[0].port}')"
fi

work="$(mktemp -d)"
pf_pid=""
cleanup() {
  if [[ -n "${pf_pid}" ]]; then
    kill "${pf_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf "${work}"
}
trap cleanup EXIT

k port-forward -n monitoring "svc/${prom_svc}" "9091:${prom_port}" >"${work}/pf.log" 2>&1 &
pf_pid="$!"

ready=0
for _ in $(seq 1 30); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:9091/-/ready" || true)"
  if [[ "${code}" == "200" ]]; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "${ready}" -ne 1 ]]; then
  say "Prometheus port-forward did not answer" >&2
  cat "${work}/pf.log" >&2 || true
  exit 1
fi

query() {
  local encoded
  encoded="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' 'probe_success')"
  curl -fsS --max-time 20 "http://127.0.0.1:9091/api/v1/query?query=${encoded}" -o "${work}/probe.json"
  python3 "${root}/tests/atak_probe.py" "${work}/probe.json"
}

up=0
for _ in $(seq 1 18); do
  if query >"${work}/now.txt"; then
    say "probe_success for the ATAK viewer:"
    tee -a "${log}" < "${work}/now.txt"
    if grep -q '^1 ' "${work}/now.txt" && ! grep -q '^0 ' "${work}/now.txt"; then
      up=1
      break
    fi
  fi
  sleep 10
done
if [[ "${up}" -ne 1 ]]; then
  say "ATAK viewer probe_success was not 1" >&2
  cat "${work}/now.txt" >&2 || true
  if [[ -f "${work}/probe.json" ]]; then
    say "every probe_success series:" >&2
    python3 "${root}/tests/atak_probe.py" --all "${work}/probe.json" | tee -a "${log}" >&2 || true
  fi
  exit 1
fi
say "atak-uptime passed"
