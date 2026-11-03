#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# List the TAK and CloudTAK blackbox probes (in their own namespaces), require
# probe_success 1, and require that TAK answered /login itself (status 200, no
# redirect to Keycloak). Then scale CloudTAK to zero and back, and record the
# drop and the recovery.
# The ATAK viewer probe is on atak/deploy/device.yaml. The full bundle does
# not deploy that package, so this job does not list it.
# Skips when the Probe CRD is absent.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${root}"
mkdir -p out
log="out/uptime-probes.txt"
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

if ! k api-resources --api-group=monitoring.coreos.com 2>/dev/null | grep '^probes ' >/dev/null; then
  say "monitoring.coreos.com Probe is not installed; uptime-probes skipped"
  exit 0
fi

say "uptime: ATAK viewer probe is not in this job; the full bundle does not deploy atak/deploy/device.yaml"

listed=0
for _ in $(seq 1 18); do
  # The Package operator creates each Probe in the package's own namespace
  # (takserver, cloudtak), not in monitoring, so list across namespaces.
  k get probes.monitoring.coreos.com -A -o wide >"${log}.list" 2>/dev/null || true
  if grep -Ei 'takserver|cloudtak|map' "${log}.list" >/dev/null 2>&1; then
    listed=1
    break
  fi
  sleep 10
done
say "kubectl get probes -A"
tee -a "${log}" < "${log}.list"
if [[ "${listed}" -ne 1 ]]; then
  say "probes do not include TAK or CloudTAK" >&2
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

# Prints one "<tak|cloudtak> <success> <status> <redirects> <instance>" line per
# TAK or CloudTAK target, classified by host.
series() {
  local m
  for m in probe_success probe_http_status_code probe_http_redirects; do
    curl -fsS --max-time 20 "http://127.0.0.1:9091/api/v1/query?query=${m}" -o "${work}/${m}.json"
  done
  python3 - "${work}" <<'PY'
import json, os, sys
from urllib.parse import urlparse
work = sys.argv[1]
rows = {}
for metric in ("probe_success", "probe_http_status_code", "probe_http_redirects"):
    data = json.load(open(os.path.join(work, metric + ".json")))
    for row in data.get("data", {}).get("result", []):
        instance = row.get("metric", {}).get("instance", "")
        rows.setdefault(instance, {})[metric] = row.get("value", ["", ""])[1]
found = False
for instance in sorted(rows):
    host = urlparse(instance).hostname or ""
    kind = ""
    if host.startswith("map."):
        kind = "cloudtak"
    elif host.startswith("takserver."):
        kind = "tak"
    if not kind:
        continue
    found = True
    v = rows[instance]
    print(kind, v.get("probe_success", "?"), v.get("probe_http_status_code", "?"),
          v.get("probe_http_redirects", "?"), instance)
if not found:
    sys.exit(2)
PY
}

# Requires probe_success 1 for every target of this kind. For TAK it also
# requires status 200 with no redirect, so the pass came from TAK and not from
# the Keycloak page a redirect would end on.
require_up() {
  local kind="$1"
  local line success status redirects
  local saw=0
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    say "probe ${line}"
    read -r _ success status redirects _ <<< "${line}"
    if [[ "${line}" == "${kind} "* ]]; then
      saw=1
      if [[ "${success}" != "1" ]]; then
        say "${kind} probe_success is ${success}" >&2
        return 1
      fi
      if [[ "${kind}" == "tak" && ( "${status}" != "200" || "${redirects}" != "0" ) ]]; then
        say "tak probe got status ${status} after ${redirects} redirects; expected 200 from TAK with none" >&2
        return 1
      fi
    fi
  done < <(series)
  if [[ "${saw}" -ne 1 ]]; then
    say "no ${kind} probe series" >&2
    return 1
  fi
}

up=0
for _ in $(seq 1 18); do
  if require_up tak && require_up cloudtak; then
    up=1
    break
  fi
  sleep 10
done
if [[ "${up}" -ne 1 ]]; then
  say "TAK and CloudTAK probe_success were not both 1" >&2
  exit 1
fi
say "uptime: probe_success is 1 for TAK and CloudTAK, and TAK answered /login without a redirect"

# Deleting the pod is not enough: it is back within one scrape interval, so the
# probe can miss the outage. Scale to zero so the drop lasts until scale-up.
replicas="$(k get deploy cloudtak -n cloudtak -o jsonpath='{.spec.replicas}')"
replicas="${replicas:-1}"
if [[ "${replicas}" -lt 1 ]]; then
  replicas=1
fi
restore_cloudtak() {
  k scale deploy/cloudtak -n cloudtak --replicas="${replicas}" >/dev/null 2>&1 || true
}
trap 'restore_cloudtak; cleanup' EXIT
say "uptime: scaling CloudTAK to zero so the probe can drop"
k scale deploy/cloudtak -n cloudtak --replicas=0

dropped=0
for _ in $(seq 1 48); do
  if series | tee "${work}/now.txt" | grep '^cloudtak 0 ' >/dev/null; then
    dropped=1
    say "uptime: CloudTAK probe_success dropped to 0"
    grep '^cloudtak ' "${work}/now.txt" | tee -a "${log}"
    break
  fi
  sleep 10
done
if [[ "${dropped}" -ne 1 ]]; then
  say "CloudTAK probe_success did not drop after the pod was deleted" >&2
  series | tee -a "${log}" >&2 || true
  exit 1
fi

say "uptime: scaling CloudTAK back to ${replicas}"
restore_cloudtak

recovered=0
for _ in $(seq 1 48); do
  if series >"${work}/now.txt" && ! grep -q '^cloudtak 0 ' "${work}/now.txt" && grep -q '^cloudtak 1 ' "${work}/now.txt"; then
    recovered=1
    say "uptime: CloudTAK probe_success recovered to 1"
    grep '^cloudtak ' "${work}/now.txt" | tee -a "${log}"
    break
  fi
  sleep 10
done
if [[ "${recovered}" -ne 1 ]]; then
  say "CloudTAK probe_success did not recover" >&2
  series | tee -a "${log}" >&2 || true
  exit 1
fi

k rollout status deploy/cloudtak -n cloudtak --timeout=180s
say "uptime-probes passed"
