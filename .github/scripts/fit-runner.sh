#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The slim checkpoint already requests about 1950m on a 2 CPU node.
# Drop pods the TAK tests do not need so the core upgrade can schedule.
# Pepr and the Istio CNI stay up: the bundle webhook and pod sandbox depend on them.
set -euo pipefail

# Two replicas are an opt-in CI availability experiment until validated live.
# Keep the ordinary path unchanged; refuse malformed choices before any writes.
agent_replicas="${CI_AGENT_REPLICAS-1}"
case "${agent_replicas}" in
  1 | 2) ;;
  *) echo "CI_AGENT_REPLICAS must be 1 or 2" >&2; exit 1 ;;
esac

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
  elif [[ "${namespace}/${name}" == zarf/agent-hook && "${agent_replicas}" == 2 ]]; then
    echo "two-replica diagnostic requires the existing agent deployment" >&2
    return 1
  fi
}

# MinIO is part of the dev stack and is not used by the TAK tests.
scale_to uds-dev-stack minio 0
# The focused manual diagnostic can preserve upstream two-replica admission.
# This mitigates one-Pod endpoint loss; it does not fix unexplained exit 2.
scale_to zarf agent-hook "${agent_replicas}"

echo "Allocated CPU after trimming unused pods:"
k describe node | sed -n '/Allocated resources:/,/Events:/p'
