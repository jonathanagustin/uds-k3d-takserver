#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Save Falco events for takserver, cloudtak, and pepr-system, then prove the
# custom cert-write rule with a labeled touch in the API container.
# Unexplained events are recorded and do not fail this script. The labeled
# write does fail the script when Loki never shows falco-probe-test.
# Skips when Falco or Loki is absent.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${root}"
mkdir -p out
log="out/falco-events.txt"
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

if ! k get ns falco >/dev/null 2>&1; then
  say "falco namespace is not installed; falco-events skipped"
  exit 0
fi
if ! k get svc loki-gateway -n loki >/dev/null 2>&1; then
  say "loki-gateway is not installed; falco-events skipped"
  exit 0
fi

say "falco: no exceptions were added. This file is the collection, not an allow decision."

work="$(mktemp -d)"
pf_pid=""
cleanup() {
  if [[ -n "${pf_pid}" ]]; then
    kill "${pf_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf "${work}"
}
trap cleanup EXIT

k port-forward -n loki svc/loki-gateway "13100:80" >"${work}/pf.log" 2>&1 &
pf_pid="$!"

# query_range writes the Loki JSON to the path in $2 and returns 0 on HTTP 200.
query_range() {
  local query="$1"
  local out="$2"
  local encoded start end code
  encoded="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "${query}")"
  end="$(python3 -c 'import time; print(int(time.time()))')"
  start="$((end - 14400))"
  code="$(curl -sS -o "${out}" -w '%{http_code}' --max-time 60 \
    "http://127.0.0.1:13100/loki/api/v1/query_range?query=${encoded}&start=${start}&end=${end}&limit=5000&direction=backward" \
    || true)"
  [[ "${code}" == "200" ]]
}

collect_query='{priority=~".+"} |~ "takserver|cloudtak|pepr-system"'
collected=0
for _ in $(seq 1 30); do
  if query_range "${collect_query}" "${work}/events.json"; then
    collected=1
    break
  fi
  sleep 2
done
if [[ "${collected}" -ne 1 ]]; then
  say "Loki did not answer the Falco event query" >&2
  cat "${work}/pf.log" >&2 || true
  exit 1
fi

python3 - "${work}/events.json" "${log}" <<'PY'
import json
import sys

src, dest = sys.argv[1], sys.argv[2]
raw = json.load(open(src))
status = raw.get("status")
if status not in (None, "success"):
    sys.stderr.write(f"loki status: {status}\n")
    sys.exit(1)
wanted = {"takserver", "cloudtak", "pepr-system"}
streams = raw.get("data", {}).get("result", [])
lines_seen = 0
no_ns = 0
kept = []
samples = []
rules = {}
for stream in streams:
    labels = stream.get("stream") or {}
    for ts, line in stream.get("values") or []:
        lines_seen += 1
        obj = None
        text = line if isinstance(line, str) else ""
        start = text.find("{")
        if start >= 0:
            try:
                obj = json.loads(text[start:])
            except json.JSONDecodeError:
                obj = None
        rule = str(labels.get("rule") or "")
        priority = str(labels.get("priority") or "")
        output = text
        ns = ""
        if isinstance(obj, dict):
            fields = obj.get("output_fields") or {}
            if not isinstance(fields, dict):
                fields = {}
            ns = str(fields.get("k8s.ns.name") or obj.get("k8s.ns.name") or "")
            rule = str(obj.get("rule") or rule)
            priority = str(obj.get("priority") or priority)
            output = str(obj.get("output") or output)
        if ns not in wanted:
            if not ns:
                no_ns += 1
                if len(samples) < 3 and text:
                    samples.append(text[:500])
            continue
        rules[rule] = rules.get(rule, 0) + 1
        kept.append(f"{ts} {ns} {priority} {rule} {output}")

truncated = "yes" if lines_seen >= 5000 else "no"
with open(dest, "a", encoding="utf-8") as handle:
    handle.write(f"falco: lines_seen {lines_seen}\n")
    handle.write(f"falco: lines_without_k8s.ns.name {no_ns}\n")
    handle.write(f"falco: kept {len(kept)}\n")
    handle.write(f"falco: truncated {truncated}\n")
    handle.write("falco: rule_counts\n")
    for name in sorted(rules):
        handle.write(f"falco: rule {rules[name]} {name}\n")
    if not rules:
        handle.write("falco: rule_counts empty\n")
    handle.write("falco: events\n")
    for row in kept:
        handle.write(row + "\n")
    if samples:
        handle.write("falco: sample lines that named a namespace in the query but had no k8s.ns.name field\n")
        for sample in samples:
            handle.write(sample + "\n")
PY

say "falco-probe: labeled test write under /opt/tak/certs by touch, not the TAK JVM"
k exec -n takserver deploy/takserver-api -c takserver-api -- \
  sh -c 'mkdir -p /opt/tak/certs && touch /opt/tak/certs/falco-probe-test'

rule_query='{rule="TAK cert write outside the JVM"}'
proven=0
for _ in $(seq 1 24); do
  if query_range "${rule_query}" "${work}/rule.json" \
    && python3 - "${work}/rule.json" >"${work}/hit.txt" <<'PY'
import json
import sys

raw = json.load(open(sys.argv[1]))
needle = "falco-probe-test"
found = False
for stream in raw.get("data", {}).get("result", []):
    for ts, line in stream.get("values") or []:
        text = line if isinstance(line, str) else ""
        if needle in text:
            print(f"{ts} {text[:1000]}")
            found = True
if not found:
    sys.exit(1)
PY
  then
    proven=1
    break
  fi
  sleep 10
done

if [[ "${proven}" -ne 1 ]]; then
  say "labeled cert write did not show up in Loki for rule TAK cert write outside the JVM" >&2
  exit 1
fi

say "falco-probe: Loki has the labeled write"
while IFS= read -r hit; do
  say "falco-probe: ${hit}"
done < "${work}/hit.txt"
say "falco-events passed"
