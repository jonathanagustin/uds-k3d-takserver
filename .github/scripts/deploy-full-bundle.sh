#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Deploy bundle/full. On arm64 the in-cluster registry pod has died while
# Zarf was pushing TAK images: the API returned 502, then the registry pod
# was gone. Zarf's own push retries stop after a few seconds and fail the
# whole bundle. Wait until the API answers and run the same deploy again.
# uds deploy repeats cleanly with --force-conflicts.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${root}"

k() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

# The registry pod is recreated by the retry itself. This only waits for the
# API, which is what the failed push could not reach.
wait_for_api() {
  local try
  for try in $(seq 1 30); do
    if k get --raw='/readyz' >/dev/null 2>&1; then
      echo "API answered (try ${try})"
      k get pods -n zarf -o wide || true
      return 0
    fi
    echo "API not ready (try ${try})"
    sleep 10
  done
  echo "API did not answer; retrying the deploy anyway" >&2
}

attempts="${DEPLOY_ATTEMPTS:-3}"
attempt=1
while [[ "${attempt}" -le "${attempts}" ]]; do
  echo "full bundle deploy attempt ${attempt} of ${attempts}"
  if uds run deploy:test-bundle --no-progress --with path=bundle/full --with options=--force-conflicts; then
    exit 0
  fi
  echo "full bundle deploy attempt ${attempt} failed" >&2
  if [[ "${attempt}" -eq "${attempts}" ]]; then
    exit 1
  fi
  wait_for_api
  attempt=$((attempt + 1))
done

echo "full bundle deploy did not run" >&2
exit 1
