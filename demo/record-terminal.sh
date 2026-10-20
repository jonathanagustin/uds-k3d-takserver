#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record each terminal chapter with VHS against the running cluster.
# Needs vhs, ttyd, ffmpeg, a Chrome/Chromium, and the JetBrains Mono font.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p demo/out

if command -v k3d >/dev/null 2>&1; then
  k3d kubeconfig merge uds --kubeconfig-merge-default >/dev/null
fi

for tape in demo/tapes/*.tape; do
  echo "Recording ${tape}"
  vhs "${tape}"
done
