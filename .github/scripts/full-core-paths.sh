#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Prints run=true|false to $GITHUB_OUTPUT (stdout outside Actions): whether
# Full Core has to run for this event. See .github/workflows/full-core.yaml.
#
#   EVENT    github.event_name
#   LABELED  "true" when the pull request has the full-core label
#   BASE     pull request base sha, or github.event.before on a push
#   HEAD     pull request head sha, or github.sha on a push
#   CHANGED  newline-separated paths, instead of git diff (for tests)
#
# schedule and workflow_dispatch always run. A pull request with the label
# always runs. A push uses the commits just pushed (two-dot), not the whole
# history. A push with no previous sha runs, so a new branch is not skipped.
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"

decide() {
  echo "run=$1" >> "${out}"
  echo "full-core: run=$1 ($2)" >&2
  exit 0
}

case "${EVENT:-}" in
  schedule | workflow_dispatch)
    decide true "${EVENT} event"
    ;;
  pull_request)
    if [[ "${LABELED:-false}" == "true" ]]; then
      decide true "full-core label"
    fi
    ;;
  push) ;;
  *)
    decide true "${EVENT:-unknown} event"
    ;;
esac

if [[ -n "${CHANGED+x}" ]]; then
  changed="${CHANGED}"
else
  if [[ "${EVENT}" == "push" ]]; then
    if [[ -z "${BASE:-}" || "${BASE}" =~ ^0+$ ]]; then
      decide true "push has no previous commit"
    fi
    changed="$(git diff --name-only "${BASE}" "${HEAD:?}")"
  else
    changed="$(git diff --name-only "${BASE:?}...${HEAD:?}")"
  fi
fi

# Backup, monitoring, UDS Core integration, the bundles, and the files this
# workflow runs. Keep in step with tasks.yaml test-full-core and tasks/test.yaml
# test:full-core.
pattern='^('
pattern+='bundle/'
pattern+='|\.github/workflows/full-core\.yaml'
pattern+='|\.github/scripts/(full-core-paths|check-full-core|full-core-top|check-monitoring|check-filesystem-backup|check-exemptions|deploy-slim-core|fit-runner|trim-runner|add-runner-swap|dump-memory|runner-wedge-probe|runner-wedge-kernel|redact-logs|redact-then-filter|checked-pipe|node-agent-ready|summarize-coreconfig|stage-sanitized-logs|dev-package|wait-for-tak-images)\.(sh|py)'
pattern+='|tasks\.yaml'
pattern+='|tasks/test\.yaml'
pattern+='|tests/(backup-restore|db-dump-secret|local-path-local|grafana-alerts|falco-events|portal|uptime-probes|loki-client|exemptions)[^/]*'
pattern+='|tests/(grafana|portal)[^/]*\.spec\.ts'
pattern+='|values/(filesystem-backup|postgres-storage|cloudtak-storage)[^/]*'
pattern+='|charts/[^/]+/templates/[^/]*(backup|dump|velero|monitor|alert|grafana|prometheus|falco|loki|portal|package|exemption|network)[^/]*'
pattern+='|charts/[^/]+/(dashboards|alerts|rules)/'
pattern+='|pepr/capabilities/workload[^/]*\.ts'
pattern+=')'

# Files under those paths that Full Core does not read. bundle/uds-config.yaml
# configures the slim test bundle (Test's install and upgrade jobs); Full Core
# deploys bundle/full with bundle/full/uds-config.yaml. The workload unit tests
# run in the Unit tests workflow (unit-tests.yaml), not in a cluster. The two
# exact runner-wedge probes run only after failure and have subprocess Unit tests.
skip='^(bundle/uds-config\.yaml|pepr/capabilities/[^/]*\.test\.ts|\.github/scripts/runner-wedge-(probe\.sh|kernel\.py))$'

hits="$(grep -E "${pattern}" <<< "${changed}" | grep -Ev "${skip}" || true)"
if [[ -n "${hits}" ]]; then
  decide true "$(tr '\n' ' ' <<< "${hits}" | cut -c1-300)"
fi
decide false "no backup, monitoring, Core, bundle or Full Core path changed"
