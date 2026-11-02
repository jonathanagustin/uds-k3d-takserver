#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Grafana /api/search returns the TAK dashboard, and Prometheus /api/v1/rules
# lists the TAK alerts. When Prometheus is up, the TAK API and messaging
# targets and the Pepr module target are up, and a JVM query returns data.
# Slim has no monitoring API and this script exits 0.
#
# Then it scales takserver-messaging to 0, waits until Alertmanager reports
# TAKMessagingTargetDown active, scales it back to 1, and waits for Ready.
# Saves a Playwright screenshot of the dashboard when docker is available.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${root}"
mkdir -p out

k() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

if ! k api-resources --api-group=monitoring.coreos.com 2>/dev/null | grep '^prometheusrules ' >/dev/null; then
  echo "monitoring.coreos.com is not installed; grafana-alerts skipped"
  exit 0
fi

k get configmap takserver-dashboard -n takserver >/dev/null
k get prometheusrule.monitoring.coreos.com takserver -n takserver >/dev/null
k get configmap takserver-loki-rules -n takserver >/dev/null

work="$(mktemp -d)"
pids=()
messaging_scaled=0
restore_messaging() {
  if [[ "${messaging_scaled}" -ne 1 ]]; then
    return 0
  fi
  k scale deploy/takserver-messaging -n takserver --replicas=1 || true
  messaging_scaled=0
}
cleanup() {
  local pid
  restore_messaging
  for pid in "${pids[@]+"${pids[@]}"}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
  rm -rf "${work}"
}
trap cleanup EXIT

forward() {
  local ns="$1"
  local svc="$2"
  local local_port="$3"
  local remote_port="$4"
  k port-forward -n "${ns}" "svc/${svc}" "${local_port}:${remote_port}" >"${work}/pf-${local_port}.log" 2>&1 &
  pids+=("$!")
}

ready() {
  local url="$1"
  local code _
  for _ in $(seq 1 30); do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "${url}" || true)"
    if [[ "${code}" != "000" && -n "${code}" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

gf_svc="$(k get svc -n grafana -o jsonpath='{.items[0].metadata.name}')"
gf_port="$(k get svc -n grafana "${gf_svc}" -o jsonpath='{.spec.ports[0].port}')"
if k get svc kube-prometheus-stack-prometheus -n monitoring >/dev/null 2>&1; then
  prom_svc="kube-prometheus-stack-prometheus"
  prom_port="9090"
else
  prom_svc="$(k get svc -n monitoring -o jsonpath='{.items[0].metadata.name}')"
  prom_port="$(k get svc -n monitoring "${prom_svc}" -o jsonpath='{.spec.ports[0].port}')"
fi
echo "grafana service ${gf_svc}:${gf_port}"
echo "prometheus service ${prom_svc}:${prom_port}"

forward grafana "${gf_svc}" 3001 "${gf_port}"
forward monitoring "${prom_svc}" 9091 "${prom_port}"

if ! ready "http://127.0.0.1:3001/api/health"; then
  echo "Grafana port-forward did not answer" >&2
  cat "${work}/pf-3001.log" >&2 || true
  exit 1
fi
if ! ready "http://127.0.0.1:9091/-/ready"; then
  echo "Prometheus port-forward did not answer" >&2
  cat "${work}/pf-9091.log" >&2 || true
  exit 1
fi

user=""
pass=""
mapfile -t creds < <(k get secret -n grafana -o json | python3 -c '
import json, sys, base64
data = json.load(sys.stdin)
for item in data.get("items", []):
    raw = item.get("data") or {}
    if "admin-user" in raw and "admin-password" in raw:
        print(base64.b64decode(raw["admin-user"]).decode())
        print(base64.b64decode(raw["admin-password"]).decode())
        break
')
if [[ "${#creds[@]}" -ge 2 ]]; then
  user="${creds[0]}"
  pass="${creds[1]}"
fi

search_ok=0
for _ in $(seq 1 18); do
  if [[ -n "${user}" ]]; then
    code="$(curl -sS -o out/grafana-search.json -w '%{http_code}' --max-time 20 -u "${user}:${pass}" "http://127.0.0.1:3001/api/search?query=TAK" || true)"
  else
    code="$(curl -sS -o out/grafana-search.json -w '%{http_code}' --max-time 20 "http://127.0.0.1:3001/api/search?query=TAK" || true)"
  fi
  echo "grafana search HTTP ${code}"
  if [[ "${code}" == "200" ]] && grep -q 'TAK Server' out/grafana-search.json; then
    search_ok=1
    break
  fi
  sleep 10
done
if [[ "${search_ok}" -ne 1 ]]; then
  echo "Grafana /api/search?query=TAK did not return the TAK Server dashboard" >&2
  if [[ -s out/grafana-search.json ]]; then
    head -c 500 out/grafana-search.json >&2 || true
    echo >&2
  fi
  exit 1
fi
echo "Grafana /api/search?query=TAK returned the TAK Server dashboard"

rules_ok=0
for _ in $(seq 1 18); do
  code="$(curl -sS -o out/prometheus-tak-rules.json -w '%{http_code}' --max-time 20 "http://127.0.0.1:9091/api/v1/rules" || true)"
  echo "prometheus rules HTTP ${code}"
  if [[ "${code}" == "200" ]] \
    && grep -q 'TAKAPITargetDown' out/prometheus-tak-rules.json \
    && grep -q 'TAKMessagingTargetDown' out/prometheus-tak-rules.json \
    && grep -q 'TAKJVMHeapHigh' out/prometheus-tak-rules.json \
    && grep -q 'TAKPodRestartLoop' out/prometheus-tak-rules.json \
    && grep -q 'TAKDeploymentUnavailable' out/prometheus-tak-rules.json; then
    rules_ok=1
    break
  fi
  sleep 10
done
if [[ "${rules_ok}" -ne 1 ]]; then
  echo "Prometheus /api/v1/rules did not list the TAK alerts" >&2
  exit 1
fi
echo "Prometheus /api/v1/rules lists the TAK alerts"

scrape_ok=0
for _ in $(seq 1 30); do
  code="$(curl -sS -o out/prometheus-targets.json -w '%{http_code}' --max-time 20 "http://127.0.0.1:9091/api/v1/targets?state=active" || true)"
  echo "prometheus targets HTTP ${code}"
  if [[ "${code}" == "200" ]] && python3 - <<'PY'
import json
import sys

active = json.load(open("out/prometheus-targets.json")).get("data", {}).get("activeTargets", [])

def up(namespace, path, pod_prefix="", pool=""):
    matched = []
    for target in active:
        labels = target.get("labels") or {}
        url = target.get("scrapeUrl") or ""
        pod = labels.get("pod") or ""
        if target.get("health") != "up" or labels.get("namespace") != namespace or path not in url:
            continue
        if pod_prefix and not pod.startswith(pod_prefix):
            continue
        # The module's pods are pepr-<uuid>-..., so match the PodMonitor's
        # scrape pool (podMonitor/takserver/takserver-oidc/0) instead.
        if pool and pool not in (target.get("scrapePool") or ""):
            continue
        matched.append(pod or url)
    return matched

missing = []
if not up("takserver", "/metrics", "takserver-api-"):
    missing.append("takserver-api")
if not up("takserver", "/metrics", "takserver-messaging-"):
    missing.append("takserver-messaging")
if not up("pepr-system", "/metrics", pool="/takserver-oidc/"):
    missing.append("takserver-oidc")
if missing:
    print("waiting on " + ", ".join(missing))
    sys.exit(1)
PY
  then
    scrape_ok=1
    break
  fi
  sleep 10
done
if [[ "${scrape_ok}" -ne 1 ]]; then
  echo "Prometheus targets for TAK or the Pepr module were not up" >&2
  python3 - <<'PY' >&2 || true
import json
try:
    active = json.load(open("out/prometheus-targets.json")).get("data", {}).get("activeTargets", [])
except FileNotFoundError:
    raise SystemExit(0)
for target in active:
    labels = target.get("labels") or {}
    ns = labels.get("namespace")
    if ns not in ("takserver", "pepr-system"):
        continue
    print(ns, labels.get("pod"), target.get("scrapePool"), target.get("health"), target.get("scrapeUrl"), target.get("lastError"))
PY
  exit 1
fi
echo "Prometheus targets for the TAK API, messaging, and the Pepr module are up"

query_ok=0
for _ in $(seq 1 12); do
  code="$(curl -sS -G -o out/prometheus-jvm.json -w '%{http_code}' --max-time 20 \
    "http://127.0.0.1:9091/api/v1/query" \
    --data-urlencode 'query=jvm_memory_used_bytes{namespace="takserver"}' || true)"
  echo "prometheus jvm query HTTP ${code}"
  if [[ "${code}" == "200" ]] && python3 - <<'PY'
import json
import sys
result = json.load(open("out/prometheus-jvm.json")).get("data", {}).get("result", [])
sys.exit(0 if result else 1)
PY
  then
    query_ok=1
    break
  fi
  sleep 10
done
if [[ "${query_ok}" -ne 1 ]]; then
  echo "jvm_memory_used_bytes{namespace=\"takserver\"} returned no data" >&2
  exit 1
fi
echo "jvm_memory_used_bytes{namespace=\"takserver\"} returned data"

pepr_ok=0
for _ in $(seq 1 12); do
  code="$(curl -sS -G -o out/prometheus-pepr.json -w '%{http_code}' --max-time 20 \
    "http://127.0.0.1:9091/api/v1/query" \
    --data-urlencode 'query=pepr_errors{namespace="pepr-system",pod=~"pepr-c72fcf944a4f43bbb386d22371aa640f-.*"}' || true)"
  echo "prometheus pepr query HTTP ${code}"
  if [[ "${code}" == "200" ]] && python3 - <<'PY'
import json
import sys
result = json.load(open("out/prometheus-pepr.json")).get("data", {}).get("result", [])
sys.exit(0 if result else 1)
PY
  then
    pepr_ok=1
    break
  fi
  sleep 10
done
if [[ "${pepr_ok}" -ne 1 ]]; then
  echo "pepr_errors for takserver-oidc returned no data" >&2
  exit 1
fi
echo "pepr_errors for takserver-oidc returned data"

if k get svc kube-prometheus-stack-alertmanager -n monitoring >/dev/null 2>&1; then
  am_svc="kube-prometheus-stack-alertmanager"
  am_port="9093"
else
  am_svc="$(k get svc -n monitoring -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | grep -i alertmanager | head -n 1 || true)"
  am_port="9093"
fi
if [[ -z "${am_svc}" ]]; then
  echo "no Alertmanager Service in monitoring" >&2
  exit 1
fi
echo "alertmanager service ${am_svc}:${am_port}"
forward monitoring "${am_svc}" 9093 "${am_port}"
if ! ready "http://127.0.0.1:9093/-/ready"; then
  if ! ready "http://127.0.0.1:9093/api/v2/status"; then
    echo "Alertmanager port-forward did not answer" >&2
    cat "${work}/pf-9093.log" >&2 || true
    exit 1
  fi
fi

messaging_scaled=1
k scale deploy/takserver-messaging -n takserver --replicas=0
echo "grafana-alerts: test scaled takserver-messaging to 0"

fired=0
for _ in $(seq 1 40); do
  code="$(curl -sS -o out/alertmanager-alerts.json -w '%{http_code}' --max-time 20 "http://127.0.0.1:9093/api/v2/alerts" || true)"
  echo "alertmanager alerts HTTP ${code}"
  if [[ "${code}" == "200" ]] && python3 -c '
import json, sys
alerts = json.load(open("out/alertmanager-alerts.json"))
ok = any(
    item.get("labels", {}).get("alertname") == "TAKMessagingTargetDown"
    and item.get("status", {}).get("state") == "active"
    for item in alerts
)
sys.exit(0 if ok else 1)
'; then
    fired=1
    break
  fi
  sleep 15
done
if [[ "${fired}" -ne 1 ]]; then
  echo "TAKMessagingTargetDown did not reach active in Alertmanager" >&2
  exit 1
fi
echo "grafana-alerts: TAKMessagingTargetDown is firing in Alertmanager"

if command -v docker >/dev/null 2>&1; then
  mkdir -p tests/.playwright/screenshots
  docker run --rm \
    --network=host \
    --shm-size=1g \
    --security-opt seccomp=unconfined \
    --user "$(id -u):$(id -g)" \
    -e CI=true \
    -e SKIP_SSO_SETUP=1 \
    -e GRAFANA_URL="http://127.0.0.1:3001/d/takserver/tak-server" \
    -e GRAFANA_USER="${user}" \
    -e GRAFANA_PASSWORD="${pass}" \
    -v "${root}/tests:/app" \
    -w /app \
    mcr.microsoft.com/playwright:v1.64.1@sha256:47b510dd9230bf0b9bfc9b20102241e577ea7a99334ab4c3ca19f19770e9b8ea \
    bash -lc 'export HOME=/tmp COREPACK_HOME=/tmp/corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0 && mkdir -p "$COREPACK_HOME" && corepack prepare pnpm@10.33.4 --activate && corepack pnpm install --frozen-lockfile && corepack pnpm exec playwright test grafana.spec.ts'
  echo "grafana-alerts: saved tests/.playwright/screenshots/tak-dashboard.png"
else
  echo "grafana-alerts: playwright screenshot skipped: docker is not available" >&2
  exit 1
fi

restore_messaging
# The next tests use messaging. Its startup probe allows 80 periods of 10s
# after the dependency waits, so wait up to 15 minutes for Ready.
if ! k rollout status deploy/takserver-messaging -n takserver --timeout=900s; then
  echo "takserver-messaging did not become Ready after scaling back to 1" >&2
  k get pods -n takserver -l app=takserver-messaging -o wide >&2 || true
  exit 1
fi
echo "grafana-alerts: takserver-messaging scaled back to 1 and is Ready"
