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

# TRIM_SKIP_ABOVE_GB: leave the disk alone when at least this many GB are
# already free. The deletes cost minutes on a slow runner, and a test job
# uses about 30 GB (measured in the Test workflow). Unset, the trim always runs.
if [[ -n "${TRIM_SKIP_ABOVE_GB:-}" ]]; then
  avail_gb="$(df --output=avail -BG / | tail -n 1 | tr -dc '0-9')"
  if ((avail_gb >= TRIM_SKIP_ABOVE_GB)); then
    echo "trim: ${avail_gb} GB free, at least ${TRIM_SKIP_ABOVE_GB} GB; skipping the deletes."
    df -h /
    exit 0
  fi
fi

# Time each delete and report the space it freed, so the slow ones can be cut
# or moved to the background on the numbers. Same deletes as before.
used_kb() { df --output=used -k / | tail -n 1 | tr -d ' '; }
start_all="${SECONDS}"
start_used="$(used_kb)"
df -h /

paths=(
  /usr/share/dotnet
  /usr/local/lib/android
  /opt/ghc
  /opt/hostedtoolcache/CodeQL
  /usr/local/share/boost
  /usr/share/swift
  /usr/local/.ghcup
  /usr/local/julia*
  /usr/share/miniconda
  /opt/az
  /usr/local/share/powershell
)
for path in "${paths[@]}"; do
  before="$(used_kb)"
  started="${SECONDS}"
  # The julia entry is a glob, so leave it unquoted.
  # shellcheck disable=SC2086
  sudo rm -rf ${path}
  printf 'trim: %-34s %4ss %6s MB freed\n' "${path}" "$((SECONDS - started))" "$(((before - $(used_kb)) / 1024))"
done

# The k3d node and the slim core package share this disk; preinstalled images
# the test never uses are dead weight and the node hit DiskPressure without it.
if command -v docker >/dev/null 2>&1; then
  before="$(used_kb)"
  started="${SECONDS}"
  sudo docker image prune --all --force || true
  printf 'trim: %-34s %4ss %6s MB freed\n' "docker image prune" "$((SECONDS - started))" "$(((before - $(used_kb)) / 1024))"
fi

df -h /
printf 'trim: total %ss, %s MB freed\n' "$((SECONDS - start_all))" "$(((start_used - $(used_kb)) / 1024))"
