#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Fail when a lockfile has an advisory that is not ignored, with a reason and
# an expiry, in the osv-scanner.toml next to it. Scorecard reads those files
# on its own schedule. This runs in lint, so a new advisory fails the pull
# request first.
set -euo pipefail

cd "$(dirname "$0")/../.."

if ! command -v osv-scanner >/dev/null 2>&1; then
  echo "osv-scanner is not installed" >&2
  exit 1
fi

found=0
while IFS= read -r -d '' lock; do
  found=$((found + 1))
  dir="$(dirname "${lock}")"
  args=(scan source -L "${lock}")
  if [[ -f "${dir}/osv-scanner.toml" ]]; then
    args+=(--config "${dir}/osv-scanner.toml")
  fi
  echo "scanning ${lock#./}"
  osv-scanner "${args[@]}"
done < <(find . -type f \
  \( -name 'package-lock.json' -o -name 'pnpm-lock.yaml' -o -name 'requirements.txt' -o -name 'dist-package-lock.json' \) \
  -not -path './upstream/*' \
  -not -path '*/node_modules/*' \
  -not -path './.git/*' \
  -print0 | sort -z)

if [[ "${found}" -eq 0 ]]; then
  echo "no lockfiles found" >&2
  exit 1
fi
