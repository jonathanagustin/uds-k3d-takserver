#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# List the TAK and CloudTAK blackbox probes (in their own namespaces), require probe_success 1, then
# scale CloudTAK to zero and back, and record the drop and the recovery.
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

if ! k api-resources --api-group=monitoring.coreos.com 2>/dev/null | grep -q '^probes '; then
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

# Prints one "tak|cloudtak <value> <instance>" line per TAK or CloudTAK series.
series() {
  local encoded
  encoded="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' 'probe_success')"
  curl -fsS --max-time 20 "http://127.0.0.1:9091/api/v1/query?query=${encoded}" -o "${work}/probe.json"
  python3 - "${work}/probe.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
rows = data.get("data", {}).get("result", [])
found = False
for row in rows:
    metric = row.get("metric", {})
    instance = metric.get("instance", "")
    value = row.get("value", ["", ""])[1]
    kind = ""
    if "map." in instance or instance.endswith("/login") or "/login" in instance:
        kind = "cloudtak"
    elif "takserver." in instance and "takserver-api." not in instance and "takserver-stream." not in instance:
        kind = "tak"
    if not kind:
        continue
    found = True
    print(f"{kind} {value} {instance}")
if not found:
    sys.exit(2)
PY
}

require_up() {
  local kind="$1"
  local line value
  local saw=0
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    say "probe_success ${line}"
    if [[ "${line}" == "${kind} "* ]]; then
      saw=1
      value="${line#"${kind}" }"
      value="${value%% *}"
      if [[ "${value}" != "1" ]]; then
        say "${kind} probe_success is ${value}" >&2
        return 1
      fi
    fi
  done < <(series)
  if [[ "${saw}" -ne 1 ]]; then
    say "no ${kind} probe_success series" >&2
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
say "uptime: probe_success is 1 for TAK and CloudTAK"

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
  if series | tee "${work}/now.txt" | grep -q '^cloudtak 0 '; then
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
