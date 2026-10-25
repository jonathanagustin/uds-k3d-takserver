#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The target-down rules use kube-state-metrics, and the chart still has
# no ServiceMonitor. JVM panels stay in the dashboard.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${root}"

fail() {
  echo "monitoring: $*" >&2
  exit 1
}

rendered="$(helm template takserver charts/takserver --namespace takserver --api-versions monitoring.coreos.com/v1)"
if grep -q 'kind: ServiceMonitor' <<< "${rendered}"; then
  fail "chart renders a ServiceMonitor"
fi
if grep -q 'up{namespace="takserver", pod=~"takserver-messaging' <<< "${rendered}"; then
  fail "messaging target-down still uses up{}"
fi
if ! grep -q 'kube_deployment_spec_replicas{namespace="takserver", deployment="takserver-messaging"} == 0' <<< "${rendered}"; then
  fail "messaging target-down does not use kube_deployment_spec_replicas"
fi
if ! grep -q 'kube_deployment_spec_replicas{namespace="takserver", deployment="takserver-api"} == 0' <<< "${rendered}"; then
  fail "API target-down does not use kube_deployment_spec_replicas"
fi
if ! grep -q 'TAKAPITargetDown' <<< "${rendered}"; then
  fail "TAKAPITargetDown was renamed"
fi
if ! grep -q 'container_memory_working_set_bytes' <<< "${rendered}"; then
  fail "dashboard has no container memory series"
fi
if ! grep -q 'jvm_memory_used_bytes' <<< "${rendered}"; then
  fail "JVM heap panel was removed"
fi
if ! grep -q 'TAKDeploymentUnavailable' <<< "${rendered}"; then
  fail "TAKDeploymentUnavailable is missing"
fi
if ! grep -q 'deployment=~"takserver-api|takserver-messaging"} == 1' <<< "${rendered}"; then
  fail "TAKDeploymentUnavailable does not require spec replicas 1"
fi
if ! grep -A 2 'alert: TAKDeploymentUnavailable' <<< "${rendered}" | grep -q 'for: 10m'; then
  fail "TAKDeploymentUnavailable for is not 10m"
fi

echo "monitoring: target-down uses kube-state-metrics and there is no ServiceMonitor"
