#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# checked_pipe LOG FILTER COMMAND...
#
# The filter must not share a pipe with the command. It reads until EOF, so
# a deadline wrapped around that pipe starts while the command is still
# writing and fails every command that outlives the filter budget.
#
# Order:
#   1. Run COMMAND in its own process group. Combined output goes to a
#      private mode-600 file under a mode-700 directory. The smoke deadline
#      starts here.
#   2. Reap COMMAND. On the deadline, SIGTERM the group, then SIGKILL it
#      after the grace period. A killed writer can leave a partial secret,
#      so that file is deleted and not sanitized or published.
#   3. When COMMAND exits by itself, run FILTER on the finished file. The
#      filter deadline starts only now. tee the sanitized file only when
#      FILTER exits 0.
#
# CHECKED_SMOKE_RC, CHECKED_FILTER_RC, and CHECKED_TEE_RC are always set.
# The function returns 0 only when all three are 0. A filter or tee failure
# returns 1. A deadline returns 124. A signal that cancels the wait returns
# 143. Any other command status is returned unchanged.
#
# CHECKED_SMOKE_DEADLINE (default 600), CHECKED_FILTER_DEADLINE (default 30),
# and CHECKED_KILL_AFTER (default 5) are seconds. CHECKED_PIPE_TMP is the
# private parent directory (default ${TMPDIR:-/tmp}).
#
# A direct api-smoke run re-execs this file as:
#   checked-pipe.sh supervise DEADLINE KILL_AFTER COMMAND...
# checked_pipe passes API_SMOKE_BOUNDED=1 so that run does not stack a
# second supervisor.

_sg_cancelled=0
_sg_leader=""
_sg_wd=""
_sg_killer=""
_sg_kill_after=5
_sg_saved_term=""
_sg_saved_int=""
_cp_dir=""
_cp_errexit=0
SUPERVISE_TIMED_OUT=0
SUPERVISE_CANCELLED=0

_sg_on_signal() {
  _sg_cancelled=1
  if [[ -n "${_sg_wd}" ]]; then
    kill -KILL -"${_sg_wd}" 2>/dev/null || true
  fi
  if [[ -n "${_sg_leader}" ]]; then
    kill -TERM -"${_sg_leader}" 2>/dev/null || true
  fi
  if [[ -z "${_sg_killer}" && -n "${_sg_leader}" ]]; then
    # New session: this grace killer must survive the watchdog group.
    # $1 and $2 expand in that shell. Quoting them here would expand them now.
    # shellcheck disable=SC2016
    setsid bash -c 'sleep "$1"; kill -KILL -"$2" 2>/dev/null || true' \
      bash "${_sg_kill_after}" "${_sg_leader}" >/dev/null 2>&1 </dev/null &
    _sg_killer=$!
  fi
}

_sg_restore_traps() {
  trap - TERM INT
  if [[ -n "${_sg_saved_term}" ]]; then
    # shellcheck disable=SC2294 # trap -p output is the restore command
    eval "${_sg_saved_term}"
  fi
  if [[ -n "${_sg_saved_int}" ]]; then
    # shellcheck disable=SC2294
    eval "${_sg_saved_int}"
  fi
}

# supervise_group DEADLINE KILL_AFTER COMMAND...
# DEADLINE and KILL_AFTER are positive integers, in seconds.
# Returns 124 when the deadline fires, 143 when this shell is signalled,
# otherwise the command's own status. The command's process group is empty
# before this returns.
supervise_group() {
  local deadline="$1"
  local kill_after="$2"
  shift 2
  local rc=0
  local flag_dir=""
  local flag=""
  local parent=""
  local monitor=0
  local errexit=0

  SUPERVISE_TIMED_OUT=0
  SUPERVISE_CANCELLED=0
  _sg_cancelled=0
  _sg_leader=""
  _sg_wd=""
  _sg_killer=""
  _sg_kill_after="${kill_after}"

  if [[ ! "${deadline}" =~ ^[1-9][0-9]*$ || ! "${kill_after}" =~ ^[1-9][0-9]*$ ]]; then
    echo "checked-pipe: deadlines must be positive integers" >&2
    return 2
  fi
  if [[ $# -eq 0 ]]; then
    echo "checked-pipe: missing command" >&2
    return 2
  fi

  parent="${CHECKED_PIPE_TMP:-${TMPDIR:-/tmp}}"
  flag_dir="$(mktemp -d "${parent}/supervise.XXXXXX")"
  chmod 700 "${flag_dir}"
  flag="${flag_dir}/flag"
  : > "${flag}"
  chmod 600 "${flag}"

  _sg_saved_term="$(trap -p TERM)"
  _sg_saved_int="$(trap -p INT)"
  trap _sg_on_signal TERM INT

  [[ $- == *m* ]] && monitor=1
  [[ $- == *e* ]] && errexit=1
  # Monitor mode would make this background job its own group before setsid
  # runs, and setsid would then fork. The waited pid must be the leader.
  set +m
  set +e
  setsid "$@" &
  _sg_leader=$!
  # $1 through $4 expand in the watchdog shell. Quoting them here would expand them now.
  # shellcheck disable=SC2016
  setsid bash -c 'sleep "$1"; printf "1\n" > "$2"; kill -TERM -"$3" 2>/dev/null || true; sleep "$4"; kill -KILL -"$3" 2>/dev/null || true' \
    bash "${deadline}" "${flag}" "${_sg_leader}" "${kill_after}" \
    >/dev/null 2>&1 </dev/null &
  _sg_wd=$!
  if [[ "${_sg_cancelled}" -eq 1 ]]; then
    _sg_on_signal
  fi
  # stderr is discarded so a signalled child is not also printed as Killed.
  wait "${_sg_leader}" 2>/dev/null
  rc=$?

  if [[ "${_sg_cancelled}" -eq 1 ]]; then
    kill -KILL -"${_sg_wd}" 2>/dev/null || true
    wait "${_sg_wd}" 2>/dev/null || true
    if [[ -n "${_sg_killer}" ]]; then
      wait "${_sg_killer}" 2>/dev/null || true
    else
      sleep "${kill_after}"
    fi
    kill -KILL -"${_sg_leader}" 2>/dev/null || true
    wait "${_sg_leader}" 2>/dev/null || true
    rc=143
    SUPERVISE_CANCELLED=1
  elif [[ -s "${flag}" ]]; then
    wait "${_sg_wd}" 2>/dev/null || true
    kill -KILL -"${_sg_leader}" 2>/dev/null || true
    wait "${_sg_leader}" 2>/dev/null || true
    rc=124
    SUPERVISE_TIMED_OUT=1
  else
    kill -KILL -"${_sg_wd}" 2>/dev/null || true
    wait "${_sg_wd}" 2>/dev/null || true
    if [[ -s "${flag}" ]]; then
      sleep "${kill_after}"
      rc=124
      SUPERVISE_TIMED_OUT=1
    fi
    kill -KILL -"${_sg_leader}" 2>/dev/null || true
    wait "${_sg_leader}" 2>/dev/null || true
  fi

  rm -rf "${flag_dir}"
  _sg_leader=""
  _sg_wd=""
  _sg_killer=""
  _sg_restore_traps
  if [[ "${monitor}" -eq 1 ]]; then
    set -m
  fi
  if [[ "${errexit}" -eq 1 ]]; then
    set -e
  else
    set +e
  fi
  return "${rc}"
}

_cp_finish() {
  local status="$1"
  if [[ -n "${_cp_dir}" ]]; then
    rm -rf "${_cp_dir}"
  fi
  _cp_dir=""
  if [[ "${_cp_errexit}" -eq 1 ]]; then
    set -e
  fi
  return "${status}"
}

checked_pipe() {
  local log="$1"
  local filter="$2"
  shift 2
  local smoke_deadline="${CHECKED_SMOKE_DEADLINE:-600}"
  local filter_deadline="${CHECKED_FILTER_DEADLINE:-30}"
  local kill_after="${CHECKED_KILL_AFTER:-5}"
  local parent="${CHECKED_PIPE_TMP:-${TMPDIR:-/tmp}}"
  local raw=""
  local clean=""
  local smoke_timeout=0
  local smoke_cancel=0

  CHECKED_SMOKE_RC=0
  CHECKED_FILTER_RC=0
  CHECKED_TEE_RC=0
  _cp_errexit=0
  _cp_dir=""
  [[ $- == *e* ]] && _cp_errexit=1

  if [[ ! "${smoke_deadline}" =~ ^[1-9][0-9]*$ \
    || ! "${filter_deadline}" =~ ^[1-9][0-9]*$ \
    || ! "${kill_after}" =~ ^[1-9][0-9]*$ ]]; then
    echo "checked-pipe: deadlines must be positive integers" >&2
    CHECKED_SMOKE_RC=2
    _cp_finish 2
    return $?
  fi
  if [[ $# -eq 0 || -z "${filter}" || -z "${log}" ]]; then
    echo "checked-pipe: usage: checked_pipe LOG FILTER COMMAND..." >&2
    CHECKED_SMOKE_RC=2
    _cp_finish 2
    return $?
  fi

  _cp_dir="$(mktemp -d "${parent}/checked-pipe.XXXXXX")"
  chmod 700 "${_cp_dir}"
  raw="${_cp_dir}/raw"
  clean="${_cp_dir}/clean"
  (
    umask 077
    : > "${raw}"
    : > "${clean}"
  )
  chmod 600 "${raw}" "${clean}"

  # Background jobs in this shell have stdin set to /dev/null, so the
  # command opens its own output file instead of inheriting a redirect.
  set +e
  # $0 and $@ expand in the command's shell. Quoting them here would expand them now.
  # shellcheck disable=SC2016
  supervise_group "${smoke_deadline}" "${kill_after}" \
    bash -c 'exec "$@" >"$0" 2>&1' "${raw}" \
    env API_SMOKE_BOUNDED=1 "$@"
  CHECKED_SMOKE_RC=$?
  smoke_timeout="${SUPERVISE_TIMED_OUT}"
  smoke_cancel="${SUPERVISE_CANCELLED}"
  if [[ "${_cp_errexit}" -eq 1 ]]; then
    set -e
  fi

  if [[ "${smoke_timeout}" -eq 1 || "${smoke_cancel}" -eq 1 ]]; then
    _cp_finish "${CHECKED_SMOKE_RC}"
    return $?
  fi

  set +e
  # $1, $2, and $3 expand in the filter's shell. Quoting them here would expand them now.
  # shellcheck disable=SC2016
  supervise_group "${filter_deadline}" "${kill_after}" \
    bash -c 'exec "$1" <"$2" >"$3"' _ \
    "${filter}" "${raw}" "${clean}"
  CHECKED_FILTER_RC=$?
  if [[ "${_cp_errexit}" -eq 1 ]]; then
    set -e
  fi
  if [[ "${CHECKED_FILTER_RC}" -ne 0 ]]; then
    _cp_finish 1
    return $?
  fi

  set +e
  tee -a "${log}" <"${clean}"
  CHECKED_TEE_RC=$?
  if [[ "${_cp_errexit}" -eq 1 ]]; then
    set -e
  fi
  if [[ "${CHECKED_TEE_RC}" -ne 0 ]]; then
    _cp_finish 1
    return $?
  fi
  _cp_finish "${CHECKED_SMOKE_RC}"
  return $?
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" != "supervise" || $# -lt 4 ]]; then
    echo "checked-pipe: usage: checked-pipe.sh supervise DEADLINE KILL_AFTER COMMAND..." >&2
    exit 2
  fi
  shift
  _deadline="$1"
  _kill_after="$2"
  shift 2
  supervise_group "${_deadline}" "${_kill_after}" "$@"
fi
