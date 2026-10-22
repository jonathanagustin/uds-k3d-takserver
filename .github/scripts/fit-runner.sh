#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The slim checkpoint already requests about 1950m on a 2 CPU node.
# Drop pods the TAK tests do not need so the core upgrade can schedule.
# Pepr and the Istio CNI stay up: the bundle webhook and pod sandbox depend on them.
set -euo pipefail

if command -v kubectl >/dev/null 2>&1; then
  k() { kubectl "$@"; }
elif command -v uds >/dev/null 2>&1; then
  k() { uds zarf tools kubectl "$@"; }
else
  echo "kubectl is not available" >&2
  exit 1
fi

if command -v k3d >/dev/null 2>&1; then
  k3d kubeconfig merge uds --kubeconfig-merge-default >/dev/null
fi

if ! k get nodes >/dev/null 2>&1; then
  echo "kubectl cannot read the k3d cluster." >&2
  exit 1
fi

# This DaemonSet is restored with the checkpoint and requests 100m.
k delete daemonset --ignore-not-found -n kube-system ensure-machine-id
k delete job --ignore-not-found -n kube-system ensure-machine-id
k delete pod --ignore-not-found -n kube-system -l job-name=ensure-machine-id

"$(dirname "${BASH_SOURCE[0]}")/allow-experimental-gateway-crds.sh"

scale_to() {
  local namespace="$1"
  local name="$2"
  local replicas="$3"
  if k get deploy "${name}" -n "${namespace}" >/dev/null 2>&1; then
    k scale "deploy/${name}" -n "${namespace}" --replicas="${replicas}"
    k rollout status "deploy/${name}" -n "${namespace}" --timeout=180s
  fi
}

# MinIO is part of the dev stack and is not used by the TAK tests.
scale_to uds-dev-stack minio 0
# One mutation webhook is enough while the bundle is deploying.
scale_to zarf agent-hook 1

echo "Allocated CPU after trimming unused pods:"
k describe node | sed -n '/Allocated resources:/,/Events:/p'
