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
if re.search(r"authorization|bearer|basic", text, re.IGNORECASE):
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
  exit 0
fi
safe get pods -n zarf -l "${selector}" -o wide
pods="$(k get pods -n zarf -l "${selector}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
count=0
while IFS= read -r pod; do
  [[ -n "${pod}" ]] || continue
  count=$((count + 1))
  [[ "${count}" -le 2 ]] || break
  echo "Current agent log: ${pod}/server"
  safe logs -n zarf "${pod}" -c server --tail=80
  echo "Previous agent log: ${pod}/server"
  safe logs -n zarf "${pod}" -c server --previous --tail=80
done <<<"${pods}"
