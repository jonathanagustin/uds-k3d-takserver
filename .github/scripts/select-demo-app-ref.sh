#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Keep image-key HEAD at the selected app source, with current recorder files.
set -euo pipefail
workflow_sha="$(git rev-parse HEAD)"
expected_sha="${EXPECTED_SHA:-${workflow_sha}}"
if [[ -n "${APP_REF:-}" ]]; then
  git fetch --no-tags --depth=1 -- origin "${APP_REF}"
  app_sha="$(git rev-parse FETCH_HEAD)"
  git checkout --detach "${app_sha}"
  git restore --source="${workflow_sha}" --staged --worktree -- \
    demo tests/demo tests/playwright.demo.config.ts tasks.yaml .gitignore .github/workflows/demo.yaml \
    .github/scripts/published_package_ref.py \
    assets/tak-on-uds-dark.svg assets/tak-mark-dark.svg \
    .github/scripts/demo-failure-diagnostics.sh .github/scripts/dump-memory.sh \
    .github/scripts/redact-then-filter.sh .github/scripts/redact-logs.py \
    .github/scripts/summarize-coreconfig.py
  expected_sha="${app_sha}"
  echo "Deploying ${app_sha} from ${APP_REF}; recorder files remain at ${workflow_sha}"
fi
for helper in .github/scripts/wait-for-tak-images.sh .github/scripts/pin-image-tags.sh \
  .github/container-and-chart/docker/build.sh .github/container-and-chart/cloudtak/build.sh .github/container-and-chart/postgis/build.sh; do
  if [[ ! -x "${helper}" ]]; then
    echo "Unsupported demo app source: required image preparation helper is missing: ${helper}" >&2
    exit 1
  fi
done
# Known read-only protocol only: an old script may otherwise ignore --wait
# and fall through to a build. Inspect source rather than executing a probe.
for helper in .github/container-and-chart/cloudtak/build.sh .github/container-and-chart/postgis/build.sh; do
  # Match literal source syntax; expansion here would inspect the wrong protocol.
  # shellcheck disable=SC2016
  if ! grep -Fq 'if [[ "${1:-}" = "--wait" ]]; then' "${helper}"; then
    echo "Unsupported demo app source: helper lacks the supported --wait branch: ${helper}" >&2
    exit 1
  fi
done
waiter=.github/scripts/wait-for-tak-images.sh
# shellcheck disable=SC2016
if ! grep -Fq 'build_if_missing="${BUILD_IF_MISSING:-true}"' "${waiter}" ||
  ! grep -Fq '"${build_if_missing}" != "true"' "${waiter}" ||
  ! grep -Fq 'EXPECTED_SHA' "${waiter}"; then
  echo "Unsupported demo app source: TAK waiter lacks the no-build/source-SHA protocol" >&2
  exit 1
fi
printf 'expected-sha=%s\n' "${expected_sha}" >> "${GITHUB_OUTPUT:-/dev/stdout}"
