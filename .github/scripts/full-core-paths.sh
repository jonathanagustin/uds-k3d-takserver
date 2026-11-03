#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Prints run=true|false to $GITHUB_OUTPUT (stdout outside Actions): whether
# Full Core has to run for this event. See .github/workflows/full-core.yaml.
#
#   EVENT    github.event_name
#   LABELED  "true" when the pull request has the full-core label
#   BASE     pull request base sha
#   HEAD     pull request head sha
#   CHANGED  newline-separated paths, instead of git diff (for tests)
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"

decide() {
  echo "run=$1" >> "${out}"
  echo "full-core: run=$1 ($2)" >&2
  exit 0
}

if [[ "${EVENT:-}" != "pull_request" ]]; then
  decide true "${EVENT:-unknown} event"
fi
if [[ "${LABELED:-false}" == "true" ]]; then
  decide true "full-core label"
fi

if [[ -n "${CHANGED+x}" ]]; then
  changed="${CHANGED}"
else
  changed="$(git diff --name-only "${BASE:?}...${HEAD:?}")"
fi

# Backup, monitoring, UDS Core integration, the bundles, and the files this
# workflow runs. Keep in step with tasks.yaml test-full-core and tasks/test.yaml
# test:full-core.
pattern='^('
pattern+='bundle/'
pattern+='|\.github/workflows/full-core\.yaml'
pattern+='|\.github/scripts/(full-core-paths|check-full-core|full-core-top|check-monitoring|check-filesystem-backup|check-exemptions|deploy-slim-core|fit-runner|trim-runner|add-runner-swap|dump-memory|dev-package|wait-for-tak-images)\.(sh|py)'
pattern+='|tasks\.yaml'
pattern+='|tasks/test\.yaml'
pattern+='|tests/(backup-restore|db-dump-secret|local-path-local|grafana-alerts|falco-events|portal|uptime-probes|loki-client|exemptions)[^/]*'
pattern+='|tests/(grafana|portal)[^/]*\.spec\.ts'
pattern+='|values/(filesystem-backup|postgres-storage)[^/]*'
pattern+='|charts/[^/]+/templates/[^/]*(backup|dump|velero|monitor|alert|grafana|prometheus|falco|loki|portal|package|exemption|network)[^/]*'
pattern+='|charts/[^/]+/(dashboards|alerts|rules)/'
pattern+='|pepr/capabilities/workload[^/]*\.ts'
pattern+=')'

hits="$(grep -E "${pattern}" <<< "${changed}" || true)"
if [[ -n "${hits}" ]]; then
  decide true "$(tr '\n' ' ' <<< "${hits}" | cut -c1-300)"
fi
decide false "no backup, monitoring, Core, bundle or Full Core path changed"
