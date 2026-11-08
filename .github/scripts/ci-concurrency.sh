#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The concurrency group used by the expensive workflows. GitHub evaluates the
# expression in the workflow file; this script is the same rule for tests.
#
#   group = workflow-event-(pr number, or the ref)-(run id, or "gate")
#   The run id is used only for schedule and workflow_dispatch.
#   cancel is true only for pull_request and push.
#
# A pull request therefore cancels only its own older runs. A main push
# cancels only an older push of the same workflow. A nightly run and a
# manual run each have their own group, so a push neither cancels them nor
# waits for them. Release and Demo Video do not call this script.
#
#   ci-concurrency.sh group WORKFLOW EVENT REF PR RUN_ID
#   ci-concurrency.sh cancel EVENT
set -euo pipefail

group_for() {
  local workflow="$1" event="$2" ref="$3" pr="${4:-}" run_id="$5" refpart suffix
  if [[ -n "${pr}" ]]; then
    refpart="${pr}"
  else
    refpart="${ref}"
  fi
  if [[ "${event}" == "schedule" || "${event}" == "workflow_dispatch" ]]; then
    suffix="${run_id}"
  else
    suffix="gate"
  fi
  printf '%s-%s-%s-%s\n' "${workflow}" "${event}" "${refpart}" "${suffix}"
}

cancel_for() {
  local event="$1"
  if [[ "${event}" == "pull_request" || "${event}" == "push" ]]; then
    echo true
  else
    echo false
  fi
}

usage() {
  echo "usage: ci-concurrency.sh group WORKFLOW EVENT REF PR RUN_ID | cancel EVENT" >&2
  exit 2
}

cmd="${1:-}"
case "${cmd}" in
  group)
    [[ $# -eq 6 ]] || usage
    group_for "$2" "$3" "$4" "$5" "$6"
    ;;
  cancel)
    [[ $# -eq 2 ]] || usage
    cancel_for "$2"
    ;;
  *) usage ;;
esac
