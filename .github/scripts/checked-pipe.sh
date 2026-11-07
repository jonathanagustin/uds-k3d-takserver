#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Run COMMAND, redact its combined output, and append that to LOG.
#
#   checked_pipe LOG FILTER -- COMMAND...
#
# Three processes. Their statuses are saved in one step, because reading
# PIPESTATUS[0] clears the array before [1] can be read, and set -u then
# aborts even when every stage succeeded.
#
# CHECKED_SMOKE_RC, CHECKED_FILTER_RC, and CHECKED_TEE_RC are always set.
# The function returns 0 only when all three are 0. A filter or tee failure
# returns 1. Otherwise it returns the command's status.
checked_pipe() {
  local log="$1"
  local filter="$2"
  shift 2
  local -a pipe_status=()
  local errexit=0
  [[ $- == *e* ]] && errexit=1
  set +e
  "$@" 2>&1 | timeout --foreground 30 "${filter}" | tee -a "${log}"
  pipe_status=("${PIPESTATUS[@]}")
  [[ "${errexit}" -eq 1 ]] && set -e
  if [[ ${#pipe_status[@]} -ne 3 ]]; then
    CHECKED_SMOKE_RC=3
    CHECKED_FILTER_RC=3
    CHECKED_TEE_RC=3
    echo "checked-pipe: pipeline status incomplete" >&2
    return 1
  fi
  CHECKED_SMOKE_RC=${pipe_status[0]}
  CHECKED_FILTER_RC=${pipe_status[1]}
  CHECKED_TEE_RC=${pipe_status[2]}
  if [[ "${CHECKED_FILTER_RC}" -ne 0 || "${CHECKED_TEE_RC}" -ne 0 ]]; then
    return 1
  fi
  return "${CHECKED_SMOKE_RC}"
}
