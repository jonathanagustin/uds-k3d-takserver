#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Audits the live policy exemptions the way the UDS Core "Audit security
# posture" guide does, for the takserver and cloudtak namespaces:
#   - every Exemption that matches these namespaces is one the package
#     expects, names only the expected policies, and has no bare wildcard
#     matcher;
#   - every pod in these namespaces that the policy engine annotated as
#     exempted maps back to one of those expected exemptions.
# Prints the exempted-resource list and the TAK pod and container security
# contexts. docs/justifications.md documents each expected exemption.
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

# Pod lists are too large for environment variables, so pass files.
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
kctl get exemptions -A -o json > "${work}/exemptions.json"
kctl get pods -n takserver -o json > "${work}/pods.json"
kctl get pods -n cloudtak -o json > "${work}/cloudtak-pods.json"

python3 - "${work}" <<'PY'
import json
import os
import re
import sys

# Exemption name -> (namespace, name pattern, policies). Keep in step with
# docs/justifications.md.
EXPECTED = {
    "takserver-db-setup": [("takserver", r"^takserver-db-setup-.*", {"RestrictIstioSidecarOverrides"})],
}
OURS = {"takserver", "cloudtak"}
WILDCARDS = {"", ".*", "^.*", ".*$", "^.*$"}
PREFIX = "uds-core.pepr.dev/uds-core-policies."

failures = []
def load(name):
    with open(os.path.join(sys.argv[1], name)) as handle:
        return json.load(handle)["items"]


exemptions = load("exemptions.json")
tak_pods = load("pods.json")
pods = tak_pods + load("cloudtak-pods.json")

print("Exemptions that match the takserver or cloudtak namespaces:")
seen = set()
for item in exemptions:
    name = item["metadata"]["name"]
    for entry in item["spec"].get("exemptions", []):
        matcher = entry.get("matcher", {})
        namespace = matcher.get("namespace", "")
        if namespace not in OURS:
            continue
        pattern = matcher.get("name", "")
        policies = set(entry.get("policies", []))
        print(f"  {name}: {namespace}/{pattern} {matcher.get('kind', 'pod')} {sorted(policies)}")
        if pattern.strip('"') in WILDCARDS:
            failures.append(f"{name}: matcher name {pattern!r} is a bare wildcard")
        expected = EXPECTED.get(name)
        if expected is None:
            failures.append(f"{name}: not an expected exemption; add it to docs/justifications.md and this test")
            continue
        if (namespace, pattern, policies) not in [(n, p, set(ps)) for n, p, ps in expected]:
            failures.append(f"{name}: {namespace}/{pattern} {sorted(policies)} differs from the expected entry")
        seen.add(name)

for name in EXPECTED:
    if name not in seen:
        failures.append(f"{name}: expected exemption is missing")

print("Pods the policy engine annotated as exempted:")
exempted = 0
for pod in pods:
    meta = pod["metadata"]
    for key, value in sorted((meta.get("annotations") or {}).items()):
        if value != "exempted" or not key.startswith(PREFIX):
            continue
        exempted += 1
        policy = key[len(PREFIX):]
        print(f"  {meta['namespace']}/{meta['name']}: {policy}")
        allowed = any(
            meta["namespace"] == n and re.search(p, meta["name"]) and policy in ps
            for entries in EXPECTED.values()
            for n, p, ps in entries
        )
        if not allowed:
            failures.append(f"{meta['namespace']}/{meta['name']}: exempted from {policy} without an expected exemption")
if exempted == 0:
    print("  none (the database setup hook pod is gone once its Job is cleaned up)")

print("TAK pod and container security contexts:")
for pod in tak_pods:
    context = json.dumps(pod["spec"].get("securityContext") or {}, sort_keys=True)
    print(f"  {pod['metadata']['name']}: {context}")
    for container in pod["spec"].get("containers", []):
        context = json.dumps(container.get("securityContext") or {}, sort_keys=True)
        print(f"  {pod['metadata']['name']}/{container['name']}: {context}")

if failures:
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    sys.exit(1)
print("exemptions: every exemption and exempted pod in takserver and cloudtak is expected")
PY
