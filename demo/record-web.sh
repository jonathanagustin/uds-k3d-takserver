#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record the web UI walkthrough with Playwright's built-in video, in the same
# container image the UI tests use. Writes demo/out/06-web.webm.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p demo/out

# The demo signs in as its own Keycloak user, takuser, with the same groups
# as the test user. The password is generated for this run and never shown:
# the login form masks it and GitHub Actions masks it in the log.
export DEMO_KEYCLOAK_USER="${DEMO_KEYCLOAK_USER:-takuser}"
if [ -z "${DEMO_KEYCLOAK_PASSWORD:-}" ]; then
  DEMO_KEYCLOAK_PASSWORD="Tk7!$(openssl rand -hex 5)@Qz#"
fi
export DEMO_KEYCLOAK_PASSWORD
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  echo "::add-mask::${DEMO_KEYCLOAK_PASSWORD}"
fi
python3 demo/keycloak-user.py

rm -rf tests/.playwright/demo

KEYCLOAK_PASSWORD="${DEMO_KEYCLOAK_PASSWORD}" docker run --rm \
  --network=host \
  --shm-size=1g \
  --security-opt seccomp=unconfined \
  --user "$(id -u):$(id -g)" \
  -e CI=true \
  -e TAK_SSO_URL="${TAK_SSO_URL:-https://takserver.uds.dev/}" \
  -e KEYCLOAK_USER="${DEMO_KEYCLOAK_USER}" \
  -e KEYCLOAK_PASSWORD \
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
