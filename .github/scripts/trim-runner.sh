#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Free the preinstalled toolchains a TAK test never runs.
# On the measured runner this was most of the space: dotnet, Android, GHC,
# and CodeQL. The install job later ran out of disk inside the k3d node (93%
# of 71.6 GiB used, image pulls failing), so this also drops more toolchains
# and the preinstalled Docker images.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ]] && [[ "${CI:-}" != "true" ]]; then
  echo "Not a CI runner; leaving the disk alone."
  exit 0
fi

df -h /

sudo rm -rf \
  /usr/share/dotnet \
  /usr/local/lib/android \
  /opt/ghc \
  /opt/hostedtoolcache/CodeQL \
  /usr/local/share/boost \
  /usr/share/swift \
  /usr/local/.ghcup \
  /usr/local/julia* \
  /usr/share/miniconda \
  /opt/az \
  /usr/local/share/powershell

# The k3d node and the slim core package share this disk; preinstalled images
# the test never uses are dead weight and the node hit DiskPressure without it.
if command -v docker >/dev/null 2>&1; then
  sudo docker image prune --all --force || true
fi

df -h /
