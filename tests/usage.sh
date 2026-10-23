#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Prints what each container in the takserver, cloudtak and pepr-system
# namespaces uses right now, next to its requests and limits. Usage comes
# from the kubelet Summary API (/api/v1/nodes/<node>/proxy/stats/summary),
# because uds-k3d turns off metrics-server. CPU is the kubelet's recent
# average in millicores, memory is the working set in MiB. Fails if a running
# container has no stats, or if one is at or over its memory limit.
set -euo pipefail

kctl() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

namespaces=(takserver cloudtak pepr-system)

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
for ns in "${namespaces[@]}"; do
  kctl get pods -n "${ns}" -o json > "${work}/pods-${ns}.json"
done
kctl get nodes -o name | cut -d/ -f2 > "${work}/nodes.txt"
while IFS= read -r node; do
  kctl get --raw "/api/v1/nodes/${node}/proxy/stats/summary" > "${work}/summary-${node}.json"
done < "${work}/nodes.txt"

python3 - "${work}" "${namespaces[@]}" <<'PY'
import glob
import json
import os
import sys

work, namespaces = sys.argv[1], sys.argv[2:]

UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
         "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}


def mem_bytes(value):
    if not value:
        return None
    for suffix, factor in UNITS.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    return float(value)


def cpu_milli(value):
    if not value:
        return None
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


def show(value, fmt):
    return "-" if value is None else fmt.format(value)


usage = {}
for path in glob.glob(os.path.join(work, "summary-*.json")):
    with open(path, encoding="utf-8") as f:
        summary = json.load(f)
    for pod in summary.get("pods", []):
        ref = pod["podRef"]
        for c in pod.get("containers", []):
            usage[(ref["namespace"], ref["name"], c["name"])] = (
                c.get("cpu", {}).get("usageNanoCores"),
                c.get("memory", {}).get("workingSetBytes"),
            )

rows, missing, over = [], [], []
for ns in namespaces:
    with open(os.path.join(work, f"pods-{ns}.json"), encoding="utf-8") as f:
        pods = json.load(f)["items"]
    for pod in pods:
        name = pod["metadata"]["name"]
        running = {s["name"] for s in pod.get("status", {}).get("containerStatuses", [])
                   if "running" in s.get("state", {})}
        for c in pod["spec"]["containers"]:
            if c["name"] not in running:
                continue
            res = c.get("resources", {})
            req, lim = res.get("requests", {}), res.get("limits", {})
            cpu_ns, mem = usage.get((ns, name, c["name"]), (None, None))
            if mem is None:
                missing.append(f"{ns}/{name}/{c['name']}")
            limit = mem_bytes(lim.get("memory"))
            if mem is not None and limit is not None and mem >= limit:
                over.append(f"{ns}/{name}/{c['name']}")
            rows.append((
                f"{ns}/{name}/{c['name']}",
                show(None if cpu_ns is None else cpu_ns / 1e6, "{:.0f}"),
                show(cpu_milli(req.get("cpu")), "{:.0f}"),
                show(cpu_milli(lim.get("cpu")), "{:.0f}"),
                show(None if mem is None else mem / 2**20, "{:.0f}"),
                show(None if mem_bytes(req.get("memory")) is None else mem_bytes(req.get("memory")) / 2**20, "{:.0f}"),
                show(None if limit is None else limit / 2**20, "{:.0f}"),
            ))

header = ("container", "cpu m", "req m", "lim m", "mem Mi", "req Mi", "lim Mi")
width = max(len(r[0]) for r in rows + [header])
print(f"{header[0]:<{width}} " + " ".join(f"{h:>7}" for h in header[1:]))
for r in sorted(rows):
    print(f"{r[0]:<{width}} " + " ".join(f"{v:>7}" for v in r[1:]))

if missing:
    print("No kubelet stats for: " + ", ".join(missing), file=sys.stderr)
if over:
    print("At or over the memory limit: " + ", ".join(over), file=sys.stderr)
if missing or over:
    sys.exit(1)
print(f"Usage listed for {len(rows)} running containers")
PY
