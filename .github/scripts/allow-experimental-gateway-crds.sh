#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The checkpoint ships the standard channel Gateway API CRDs. core-base ships
# the experimental channel, and the upstream safe-upgrades policy rejects
# that upgrade. Remove the policy before the core-base upgrade.
set -euo pipefail

if command -v kubectl >/dev/null 2>&1; then
  k() { kubectl "$@"; }
elif command -v uds >/dev/null 2>&1; then
  k() { uds zarf tools kubectl "$@"; }
else
  echo "kubectl is not available" >&2
  exit 1
fi

k delete validatingadmissionpolicy --ignore-not-found safe-upgrades.gateway.networking.k8s.io
k delete validatingadmissionpolicybinding --ignore-not-found safe-upgrades.gateway.networking.k8s.io
