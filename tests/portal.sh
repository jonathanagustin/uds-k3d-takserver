#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Portal tiles on the full-core cluster. Slim does not install core-portal,
# and the shared ui task runs every spec, so this stays a separate task.
set -euo pipefail

if ! uds zarf tools kubectl get deploy -n uds-portal -o name | grep -q .; then
  echo "uds-portal is not deployed" >&2
  exit 1
fi

python3 ./tests/ensure-outsider.py
mkdir -p tests/.playwright/screenshots

docker run --rm \
  --network=host \
  --shm-size=1g \
  --security-opt seccomp=unconfined \
  --user "$(id -u):$(id -g)" \
  -e CI=true \
  -e PORTAL_URL="https://portal.uds.dev" \
  -e KEYCLOAK_USER="${KEYCLOAK_USER:-doug}" \
  -e KEYCLOAK_PASSWORD="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}" \
  -e KEYCLOAK_OUTSIDER="${KEYCLOAK_OUTSIDER:-outsider}" \
  -e KEYCLOAK_OUTSIDER_PASSWORD="${KEYCLOAK_OUTSIDER_PASSWORD:-outsider123!@#UN}" \
  -v "$(pwd)/tests:/app" \
  -w /app \
  mcr.microsoft.com/playwright:v1.64.1 \
  bash -lc 'export HOME=/tmp COREPACK_HOME=/tmp/corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0 && mkdir -p "$COREPACK_HOME" && corepack prepare pnpm@10.33.4 --activate && corepack pnpm install --frozen-lockfile && corepack pnpm exec playwright test portal.spec.ts'
