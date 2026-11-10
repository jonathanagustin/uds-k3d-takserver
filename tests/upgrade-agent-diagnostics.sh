#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Failure-only diagnostics; native Zarf actions own readiness and its deadlines.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
filter="${here}/../.github/scripts/redact-then-filter.sh"
# Agent logs are untrusted. Omit the whole stream on authentication markers,
# including JSON/header variants, before the existing config-secret redactor.
redact() {
  python3 -c '
import re, sys
text = sys.stdin.read()
if re.search(r"authorization|bearer|basic|registry.?auth|dockerconfigjson|\bauth\b", text, re.IGNORECASE):
    print("Omitted authentication-bearing agent diagnostic")
else:
    sys.stdout.write(text)
' | "${filter}" --tail "${1}"
}
if [[ "${UPGRADE_AGENT_DIAGNOSTICS_INNER:-}" != 1 ]]; then
  log="$(mktemp)"
  setsid env UPGRADE_AGENT_DIAGNOSTICS_INNER=1 bash "$0" "${1:-unknown}" >"${log}" 2>&1 &
  pid=$!
  for ((elapsed = 0; elapsed < 30; elapsed++)); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -TERM -- "-${pid}" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-${pid}" 2>/dev/null || true
  else
    wait "${pid}" || true
  fi
  redact 120 <"${log}" || echo 'Omitted unsanitizable agent diagnostics'
  rm -f "${log}"
  exit 0
fi
k() { timeout --kill-after=1s 3s uds zarf tools kubectl --request-timeout=2s "$@"; }
safe() { k "$@" 2>&1 | redact 40 || echo 'Omitted unavailable or unsanitizable agent diagnostic'; }
# K3d nodes are Docker containers (app=k3d). K3s ships crictl configured for
# its embedded containerd; use its CRI API rather than guessing rotated paths.
# Also works when the Kubernetes API/Service selector is unavailable. Never
# inspect Docker env, Kubernetes Secrets, or CRI inspect (which includes env).
nodes="$(timeout --kill-after=1s 3s docker ps --filter label=app=k3d --format '{{.Names}}' 2>/dev/null || true)"
node_count=0
while IFS= read -r node; do
  [[ "${node}" =~ ^k3d-[a-zA-Z0-9_.-]+-(server|agent)-[0-9]+$ ]] || continue
  node_count=$((node_count + 1))
  [[ "${node_count}" -le 2 ]] || break
  ids="$(timeout --kill-after=1s 3s docker exec "${node}" k3s crictl ps -a -o json 2>/dev/null |
    python3 "${here}/upgrade-agent-metadata.py" cri 2>/dev/null || true)"
  while read -r id metadata; do
    [[ "${id}" =~ ^[a-f0-9]{12,64}$ ]] || continue
    echo "Node CRI agent log: ${node}/${id}"
    printf '%s\n' "${metadata}" | redact 4
    timeout --kill-after=1s 3s docker exec "${node}" k3s crictl logs --tail=80 "${id}" 2>&1 |
      redact 80 || echo 'Omitted unavailable or unsanitizable CRI diagnostic'
  done <<<"${ids}"
done <<<"${nodes}"

echo "Zarf agent diagnostics: phase=${1:-unknown}, namespace=zarf deployment/service=agent-hook"
safe get deployment agent-hook -n zarf -o wide
safe get service,endpoints agent-hook -n zarf -o wide
# Use the actual live Service selector, not an assumed pod label.
selector="$(k get service agent-hook -n zarf -o json 2>/dev/null | python3 -c '
import json,sys
selector=json.load(sys.stdin).get("spec",{}).get("selector",{})
assert selector, "agent service has no selector"
print(",".join(f"{key}={value}" for key,value in sorted(selector.items())))
' 2>/dev/null || true)"
if [[ -z "${selector}" ]]; then
  echo 'Agent Service selector unavailable; omitted pod logs'
else
safe get pods -n zarf -l "${selector}" -o wide
pods="$(k get pods -n zarf -l "${selector}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
count=0
while IFS= read -r pod; do
  [[ -n "${pod}" ]] || continue
  count=$((count + 1))
  [[ "${count}" -le 2 ]] || break
  echo "Agent container metadata: ${pod}/server"
  k get pod -n zarf "${pod}" -o json 2>/dev/null | python3 "${here}/upgrade-agent-metadata.py" pod | redact 12 || true
  echo "Current agent log: ${pod}/server"
  safe logs -n zarf "${pod}" -c server --tail=80
  echo "Previous agent log: ${pod}/server"
  safe logs -n zarf "${pod}" -c server --previous --tail=80
done <<<"${pods}"
fi
