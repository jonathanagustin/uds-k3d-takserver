#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Which changes make a pull request run Full Core (.github/scripts/full-core-paths.sh).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="${root}/.github/scripts/full-core-paths.sh"
fails=0

check() {
  local want="$1" event="$2" labeled="$3" changed="$4" out got
  out="$(mktemp)"
  EVENT="${event}" LABELED="${labeled}" CHANGED="${changed}" GITHUB_OUTPUT="${out}" "${script}" 2>/dev/null
  got="$(sed -n 's/^run=//p' "${out}")"
  rm -f "${out}"
  if [[ "${got}" != "${want}" ]]; then
    echo "not ok: ${event} labeled=${labeled} [${changed//$'\n'/ }] -> ${got}, want ${want}"
    fails=$((fails + 1))
  else
    echo "ok: ${event} labeled=${labeled} [${changed//$'\n'/ }] -> ${got}"
  fi
}

check true push false ""
check true schedule false ""
check true workflow_dispatch false ""
check true pull_request true "docs/data.md"
check false pull_request false "docs/data.md"
check false pull_request false "charts/takserver/templates/prereqs.yaml"
check false pull_request false $'tests/test_bench.py\nbench/run.py'
check true pull_request false "charts/takserver/templates/db-dump.yaml"
check true pull_request false "charts/takserver/templates/monitoring.yaml"
check true pull_request false "charts/takserver/templates/uds-package.yaml"
check true pull_request false "charts/takserver/dashboards/takserver.json"
check true pull_request false "bundle/full/uds-config.yaml"
check true pull_request false "bundle/uds-bundle.yaml"
check true pull_request false ".github/workflows/full-core.yaml"
check true pull_request false ".github/scripts/summarize-coreconfig.py"
check true pull_request false ".github/scripts/runner-wedge-probe.sh"
check true pull_request false ".github/scripts/redact-logs.py"
check true pull_request false ".github/scripts/stage-sanitized-logs.sh"
check true pull_request false ".github/scripts/redact-then-filter.sh"
check true pull_request false "tests/backup-restore.sh"
check true pull_request false "tests/grafana-alerts.sh"
check true pull_request false "values/filesystem-backup.yaml.tpl"
check true pull_request false "values/cloudtak-storage.yaml.tpl"
check true pull_request false "pepr/capabilities/workload.ts"
check true pull_request false "tasks/test.yaml"
check false pull_request false "bundle/uds-config.yaml"
check false pull_request false "pepr/capabilities/workload.test.ts"
check true pull_request false $'pepr/capabilities/workload.test.ts\npepr/capabilities/workload.ts'
check true pull_request false $'bundle/uds-config.yaml\nbundle/full/uds-config.yaml'
check true pull_request false "bundle/test-values.yaml"

if (( fails > 0 )); then
  echo "${fails} case(s) failed"
  exit 1
fi
