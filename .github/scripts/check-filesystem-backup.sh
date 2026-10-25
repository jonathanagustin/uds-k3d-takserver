#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Default renders omit the node-agent. The string "true" renders it, the
# exemption, and the CloudTAK volume annotation.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${root}"

fail() {
  echo "filesystem-backup: $*" >&2
  exit 1
}

off="$(helm template takserver charts/takserver --namespace takserver)"
cloud_off="$(helm template cloudtak charts/cloudtak --namespace cloudtak)"
if grep -q 'kind: DaemonSet' <<< "${off}"; then
  fail "default TAK render includes a DaemonSet"
fi
if grep -q 'name: velero-node-agent' <<< "${off}"; then
  fail "default TAK render includes the node-agent exemption"
fi
if grep -q 'backup.velero.io/backup-volumes' <<< "${cloud_off}"; then
  fail "default CloudTAK render annotates the volume"
fi

on="$(helm template takserver charts/takserver --namespace takserver --set-string backup.filesystem.enabled=true)"
cloud_on="$(helm template cloudtak charts/cloudtak --namespace cloudtak --set-string backup.filesystem.enabled=true)"
for needle in \
  'kind: DaemonSet' \
  'name: node-agent' \
  'name: velero-node-agent' \
  'docker.io/velero/velero:v1.18.4' \
  'privileged: true' \
  '/var/lib/kubelet/pods' \
  'namespace: velero'; do
  if ! grep -q "${needle}" <<< "${on}"; then
    fail "enabled TAK render is missing ${needle}"
  fi
done
if ! grep -q 'backup.velero.io/backup-volumes: data' <<< "${cloud_on}"; then
  fail "enabled CloudTAK render is missing the volume annotation"
fi

tpl="values/filesystem-backup.yaml.tpl"
if ! grep -q 'FILESYSTEM_BACKUP' "${tpl}"; then
  fail "${tpl} does not read FILESYSTEM_BACKUP"
fi
if ! grep -q 'backup.velero.io/backup-volumes: data' "${tpl}"; then
  fail "${tpl} does not annotate the Bitnami data volume"
fi

echo "filesystem-backup: default render is empty and the enabled render has the agent"
