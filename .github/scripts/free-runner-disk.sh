#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Drop preinstalled GitHub-hosted runner toolchains before a build or install.
# A fresh ubuntu-latest image leaves little room for the TAK layers.
set -euo pipefail

if [ "${GITHUB_ACTIONS:-}" != "true" ] && [ "${CI:-}" != "true" ]; then
  echo "Not a CI runner; leaving the disk alone."
  exit 0
fi

df -h /

sudo rm -rf \
  /usr/share/dotnet \
  /usr/local/lib/android \
  /opt/ghc \
  /opt/hostedtoolcache

if [ "${PRUNE_DOCKER:-false}" = "true" ] && command -v docker >/dev/null 2>&1; then
  docker image prune --all --force || true
fi

df -h /
