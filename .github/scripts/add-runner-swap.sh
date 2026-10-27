#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Add swap on a GitHub-hosted runner. Workflows in this repo run on
# ubuntu-24.04 or ubuntu-24.04-arm unless vars.TEST_RUNNER names something
# else. None of them name a larger hosted runner. The full-core layers plus
# TAK need more memory than that VM keeps free. Outside CI this exits 0.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" && "${CI:-}" != "true" ]]; then
  echo "Not a CI runner; not adding swap."
  exit 0
fi

swap_now="$(swapon --noheadings --show || true)"
if [[ -n "${swap_now}" ]]; then
  echo "Swap is already on."
  swapon --show
  free -h
  exit 0
fi

gb="${SWAP_GB:-8}"
if [[ ! "${gb}" =~ ^[0-9]+$ ]] || ((gb < 1 || gb > 32)); then
  echo "SWAP_GB must be an integer from 1 to 32, got '${gb}'." >&2
  exit 1
fi

path="/swapfile"
echo "Adding ${gb}G swap at ${path}"
if ! sudo fallocate -l "${gb}G" "${path}"; then
  sudo dd if=/dev/zero of="${path}" bs=1M count="$((gb * 1024))"
fi
sudo chmod 600 "${path}"
sudo mkswap "${path}"
sudo swapon "${path}"
swapon --show
free -h
