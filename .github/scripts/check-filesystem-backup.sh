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
  'runAsUser: 0' \
  'role: node-agent' \
  'name: HOME' \
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

# The chart's own values.yaml placeholder is not replaced before Helm
# renders, so both local charts must read the switch from a valuesFile.
switch="values/filesystem-backup-switch.yaml"
if ! grep -q '###ZARF_VAR_FILESYSTEM_BACKUP###' "${switch}"; then
  fail "${switch} does not read FILESYSTEM_BACKUP"
fi
if ! grep -q -- '- ../values/filesystem-backup-switch.yaml' common/zarf.yaml; then
  fail "common/zarf.yaml does not pass ${switch} to uds-takserver-config"
fi
if ! grep -q -- '- values/filesystem-backup-switch.yaml' zarf.yaml; then
  fail "zarf.yaml does not pass ${switch} to uds-cloudtak"
fi

bundle="bundle/full/uds-bundle.yaml"
if ! grep -q 'name: node-agent' "${bundle}"; then
  fail "${bundle} does not select the node-agent"
fi
if ! grep -q 'remoteGenerated: KubeAPI' "${bundle}"; then
  fail "${bundle} does not allow the node-agent to the Kubernetes API"
fi
config="bundle/full/uds-config.yaml"
if ! grep -q 'FILESYSTEM_BACKUP: "true"' "${config}"; then
  fail "${config} does not turn FILESYSTEM_BACKUP on"
fi

echo "filesystem-backup: default render is empty and the enabled render has the agent"
