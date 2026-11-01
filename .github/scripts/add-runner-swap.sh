#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Make the runner's swap SWAP_GB (default 8) at /swapfile. Workflows in this
# repo run on ubuntu-24.04 or ubuntu-24.04-arm unless vars.TEST_RUNNER names
# something else. None of them name a larger hosted runner. The full-core
# layers plus TAK need more memory than that VM keeps free. The runner image
# already ships a 3G /swapfile, so an existing swap is resized rather than
# kept. Running it again with swap already at the target changes nothing.
# Outside CI this exits 0.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" && "${CI:-}" != "true" ]]; then
  echo "Not a CI runner; not changing swap."
  exit 0
fi

gb="${SWAP_GB:-8}"
if [[ ! "${gb}" =~ ^[0-9]+$ ]] || ((gb < 1 || gb > 32)); then
  echo "SWAP_GB must be an integer from 1 to 32, got '${gb}'." >&2
  exit 1
fi

path="/swapfile"
# mkswap keeps the first page for its header, so an 8G file reports 4KiB
# less than 8G. Allow 1MiB under the target.
want=$((gb * 1024 * 1024 * 1024 - 1024 * 1024))

# Bytes of swap that are on now, over every swap file and device.
swap_total() {
  swapon --noheadings --bytes --show=SIZE | awk '{ s += $1 } END { print s + 0 }'
}

echo "Swap before:"
swapon --show || true

if (($(swap_total) >= want)); then
  echo "Swap is already at least ${gb}G."
else
  if swapon --noheadings --show=NAME | grep -x "${path}" >/dev/null; then
    echo "Turning off the existing ${path} to resize it."
    sudo swapoff "${path}"
  fi
  sudo rm -f "${path}"
  echo "Creating ${gb}G swap at ${path}"
  if ! sudo fallocate -l "${gb}G" "${path}"; then
    sudo dd if=/dev/zero of="${path}" bs=1M count="$((gb * 1024))"
  fi
  sudo chmod 600 "${path}"
  sudo mkswap "${path}" >/dev/null
  sudo swapon "${path}"
fi

total="$(swap_total)"
echo "Swap after: $((total / 1024 / 1024))M total (target ${gb}G)"
swapon --show
free -h
if ((total < want)); then
  echo "Swap is $((total / 1024 / 1024))M, below the ${gb}G target." >&2
  exit 1
fi
