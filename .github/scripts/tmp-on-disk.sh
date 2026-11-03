#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Ubuntu 26.04 runners mount /tmp as a size-limited tmpfs. Zarf extracts the
# multi-GB slim checkpoint under /tmp, and that failed there with
# "disk quota exceeded" (runs 40468308064 and 40483896004, see #219).
# A lazy unmount puts /tmp back on the root disk. The log steps still read
# /tmp/zarf-*.log and /tmp/uds-*.log. Does nothing when /tmp is not tmpfs,
# as on Ubuntu 24.04.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ]] && [[ "${CI:-}" != "true" ]]; then
  echo "Not a CI runner; leaving /tmp alone."
  exit 0
fi

fstype="$(findmnt --noheadings --output FSTYPE --target /tmp || true)"
if [[ "${fstype}" != "tmpfs" ]]; then
  echo "/tmp is ${fstype:-on the root file system}; nothing to do."
  exit 0
fi

findmnt --target /tmp
sudo umount --lazy /tmp
sudo chmod 1777 /tmp
echo "/tmp is now on $(findmnt --noheadings --output SOURCE,FSTYPE --target /tmp)"
df -h /tmp
