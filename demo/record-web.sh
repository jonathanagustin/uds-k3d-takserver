#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record the web UI walkthrough with Playwright's built-in video, in the same
# container image the UI tests use. Writes demo/out/06-web.webm.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p demo/out
rm -rf tests/.playwright/demo

docker run --rm \
  --network=host \
  --shm-size=1g \
  --security-opt seccomp=unconfined \
  --user "$(id -u):$(id -g)" \
  -e CI=true \
  -e TAK_SSO_URL="${TAK_SSO_URL:-https://takserver.uds.dev/}" \
  -e KEYCLOAK_USER="${KEYCLOAK_USER:-doug}" \
  -e KEYCLOAK_PASSWORD="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}" \
  -v "$(pwd)/tests:/app" \
  -w /app \
  mcr.microsoft.com/playwright:v1.64.1 \
  bash -lc 'export HOME=/tmp COREPACK_HOME=/tmp/corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0 && mkdir -p "$COREPACK_HOME" && corepack prepare pnpm@10.33.4 --activate && corepack pnpm install --frozen-lockfile && corepack pnpm exec playwright test --config playwright.demo.config.ts'

video="$(find tests/.playwright/demo -name '*.webm' | head -n 1)"
if [ -z "${video}" ]; then
  echo "Playwright did not write a video." >&2
  exit 1
fi
cp "${video}" demo/out/06-web.webm
if [ -f tests/.playwright/demo/events.json ]; then
  cp tests/.playwright/demo/events.json demo/out/06-web-events.json
fi
