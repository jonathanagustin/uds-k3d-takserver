#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Full-core CI only. Creates StorageClass local-path-local, whose PVs are
# Kubernetes local volumes, so Velero file-system backup copies them (Velero
# skips hostPath PVs). uds-k3d runs local-path-provisioner with a
# sharedFileSystemPath, and a shared-FS PV gets no node affinity, which a
# local PV requires. So the provisioner config moves to storageClassConfigs:
# local-path keeps its config unchanged, and local-path-local gets a
# nodePathMap on the same directory.
set -euo pipefail

k() {
  uds zarf tools kubectl "$@"
}

say() {
  echo "local-path-local: $*"
}

ns="$(k get configmap -A --field-selector metadata.name=local-path-config \
  -o jsonpath='{.items[0].metadata.namespace}')"
if [[ -z "${ns}" ]]; then
  say "ConfigMap local-path-config not found" >&2
  exit 1
fi

current="$(k get configmap local-path-config -n "${ns}" -o jsonpath='{.data.config\.json}')"
patched="$(python3 - "${current}" <<'PY'
import json
import sys

cfg = json.loads(sys.argv[1])
classes = cfg.get("storageClassConfigs") or {}
if "local-path-local" in classes:
    print(json.dumps(cfg))
    sys.exit(0)
if classes:
    base = classes.get("local-path")
    if base is None:
        sys.exit("storageClassConfigs has no local-path entry")
else:
    base = {}
    for key in ("nodePathMap", "sharedFileSystemPath"):
        if cfg.get(key):
            base[key] = cfg.pop(key)
    cfg["nodePathMap"] = []
    cfg.pop("sharedFileSystemPath", None)
    classes = {"local-path": base}
path = base.get("sharedFileSystemPath")
if not path:
    paths = [p for n in base.get("nodePathMap", []) for p in n.get("paths", [])]
    if not paths:
        sys.exit("local-path has neither sharedFileSystemPath nor a nodePathMap path")
    path = paths[0]
classes["local-path-local"] = {
    "nodePathMap": [{"node": "DEFAULT_PATH_FOR_NON_LISTED_NODES", "paths": [path]}]
}
cfg["storageClassConfigs"] = classes
print(json.dumps(cfg))
PY
)"
k create configmap local-path-config -n "${ns}" --from-literal=config.json="${patched}" \
  --dry-run=client -o json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"data": d["data"]}))' \
  > /tmp/local-path-config-patch.json
k patch configmap local-path-config -n "${ns}" --type merge --patch-file /tmp/local-path-config-patch.json
say "provisioner config in ${ns}: ${patched}"

k apply -f "$(dirname "${BASH_SOURCE[0]}")/local-path-local-storageclass.yaml"

# The provisioner reloads its config from the mounted ConfigMap. Restart it so
# the new class is known before any claim uses it.
deploy="$(k get deploy -n "${ns}" -l app=local-path-provisioner -o name | head -n 1)"
if [[ -z "${deploy}" ]]; then
  deploy="deployment/local-path-provisioner"
fi
k rollout restart -n "${ns}" "${deploy}"
k rollout status -n "${ns}" "${deploy}" --timeout=180s
say "StorageClass local-path-local ready"
