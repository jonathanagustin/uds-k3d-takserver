#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Production checked_pipe, under set -u.
# The filter deadline starts only after the command exits. A command longer
# than the filter budget and shorter than the smoke budget must succeed.
# The process group is signalled and then killed, including a descendant
# that ignores SIGTERM and holds an output fd. Private files are removed
# on success, command failure, filter failure, timeout, and cancel.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=.github/scripts/checked-pipe.sh
source "${root}/.github/scripts/checked-pipe.sh"
filter="${root}/.github/scripts/redact-then-filter.sh"
sentinel="smoke-sentinel-value"
work="$(mktemp -d)"
pipe_tmp="${work}/pipe"
mkdir -p "${pipe_tmp}"
export CHECKED_PIPE_TMP="${pipe_tmp}"
self_pgid="$(ps -o pgid= -p $$ | tr -d '[:space:]')"
pgids=()

cleanup() {
  local p
  if ((${#pgids[@]})); then
    for p in "${pgids[@]}"; do
      if [[ -n "${p}" && "${p}" != "0" && "${p}" != "${self_pgid}" ]]; then
        kill -KILL -"${p}" 2>/dev/null || true
      fi
    done
  fi
  rm -rf "${work}"
}
trap cleanup EXIT

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

expect_status() {
  local name="$1" want_smoke="$2" want_filter="$3" want_tee="$4"
  if [[ "${CHECKED_SMOKE_RC}" -eq "${want_smoke}" \
    && "${CHECKED_FILTER_RC}" -eq "${want_filter}" \
    && "${CHECKED_TEE_RC}" -eq "${want_tee}" ]]; then
    ok "${name} statuses ${want_smoke} ${want_filter} ${want_tee}"
  else
    bad "${name} statuses ${CHECKED_SMOKE_RC:-missing} ${CHECKED_FILTER_RC:-missing} ${CHECKED_TEE_RC:-missing}"
  fi
}

assert_clean() {
  local name="$1"
  local left=""
  left="$(find "${pipe_tmp}" -mindepth 1 -print -quit)"
  if [[ -n "${left}" ]]; then
    bad "${name} left ${left}"
  else
    ok "${name} removed private files"
  fi
}

note_pg() {
  if [[ -s "$1" ]]; then
    pgids+=("$(tr -d '[:space:]' < "$1")")
  fi
}

log="${work}/success.log"
: > "${log}"
trap 'true' RETURN
if checked_pipe "${log}" cat true; then
  expect_status "success" 0 0 0
else
  bad "success pipeline returned ${?} statuses ${CHECKED_SMOKE_RC:-} ${CHECKED_FILTER_RC:-} ${CHECKED_TEE_RC:-}"
fi
if [[ "$(trap -p RETURN)" == "trap -- 'true' RETURN" ]]; then
  ok "caller RETURN trap preserved"
else
  bad "caller RETURN trap is $(trap -p RETURN)"
fi
trap - RETURN
assert_clean "success"

log="${work}/smoke-fail.log"
: > "${log}"
if checked_pipe "${log}" cat false; then
  bad "failing command was treated as success"
else
  expect_status "command failure" 1 0 0
fi
assert_clean "command failure"

publish_fail="${work}/publish-fail.sh"
cat > "${publish_fail}" <<'EOF'
#!/bin/bash
printf 'FAIL kept-after-exit\n'
exit 1
EOF
chmod +x "${publish_fail}"
log="${work}/publish-fail.log"
: > "${log}"
if checked_pipe "${log}" cat "${publish_fail}"; then
  bad "completed non-zero command was treated as success"
else
  expect_status "completed failure" 1 0 0
fi
if grep -q 'FAIL kept-after-exit' "${log}"; then
  ok "completed failure published its output"
else
  bad "completed failure dropped its output"
fi
assert_clean "completed failure"

fail_filter="${work}/fail-filter.sh"
cat > "${fail_filter}" <<'EOF'
#!/bin/bash
cat >/dev/null
exit 7
EOF
chmod +x "${fail_filter}"
log="${work}/filter-fail.log"
: > "${log}"
if checked_pipe "${log}" "${fail_filter}" true; then
  bad "failing filter was treated as success"
else
  expect_status "filter failure" 0 7 0
fi
assert_clean "filter failure"

log="${work}/missing/tee-fail.log"
if checked_pipe "${log}" cat true; then
  bad "failing tee was treated as success"
else
  if [[ "${CHECKED_SMOKE_RC}" -eq 0 && "${CHECKED_FILTER_RC}" -eq 0 && "${CHECKED_TEE_RC}" -ne 0 ]]; then
    ok "tee failure status ${CHECKED_TEE_RC}"
  else
    bad "tee failure statuses ${CHECKED_SMOKE_RC:-} ${CHECKED_FILTER_RC:-} ${CHECKED_TEE_RC:-}"
  fi
fi
assert_clean "tee failure"

half1="${sentinel:0:6}"
half2="${sentinel:6}"
secret_cmd="${work}/secret.sh"
cat > "${secret_cmd}" <<EOF
#!/bin/bash
printf 'login landed on https://sso.example/auth\n'
printf '  response body omitted\n'
printf 'secret="%s\n%s"\n' '${half1}' '${half2}'
EOF
chmod +x "${secret_cmd}"
log="${work}/redacted.log"
: > "${log}"
checked_pipe "${log}" "${filter}" "${secret_cmd}" || bad "redacting command failed"
if grep -q "${sentinel}" "${log}" || grep -q "${half1}" "${log}" || grep -q "${half2}" "${log}"; then
  bad "pipeline log kept a secret"
else
  ok "pipeline log has no sentinel"
fi
assert_clean "redaction"

url='https://sso.example/auth?code='"${sentinel}"'&access_token='"${sentinel}"'#frag'
landed="${url%%[\?#]*}"
if [[ "${landed}" == "https://sso.example/auth" && "${landed}" != *"${sentinel}"* ]]; then
  ok "login URL keeps no query or fragment"
else
  bad "login URL strip left ${landed}"
fi

bound="${work}/bound.log"
: > "${bound}"
checked_pipe "${bound}" cat bash -c 'printf "%s\n" "${API_SMOKE_BOUNDED}"' \
  || bad "bounded marker command failed"
if grep -qx '1' "${bound}"; then
  ok "checked_pipe marks the command so api-smoke does not stack a supervisor"
else
  bad "API_SMOKE_BOUNDED was not 1"
fi
assert_clean "bounded marker"

if grep -q 'response body omitted' "${root}/tests/api-smoke.sh" \
  && ! grep -q 'out\[:2000\]' "${root}/tests/api-smoke.sh" \
  && ! grep -q '| head -n' "${root}/tests/api-smoke.sh" \
  && ! grep -q -- '--foreground' "${root}/tests/api-smoke.sh" \
  && grep -q 'checked-pipe.sh" supervise 600 5' "${root}/tests/api-smoke.sh"; then
  ok "api-smoke omits response bodies and supervises its group"
else
  bad "api-smoke still prints a cut response body or uses --foreground"
fi

# Producer outlives the filter budget and finishes inside the smoke budget.
# The same checked_pipe is used; the deadlines are the production knobs.
slow="${work}/slow.sh"
cat > "${slow}" <<'EOF'
#!/bin/bash
sleep 2
printf 'slow-producer-marker\n'
EOF
chmod +x "${slow}"
log="${work}/slow.log"
mode_note="${work}/slow.mode"
: > "${log}"
: > "${mode_note}"
CHECKED_SMOKE_DEADLINE=5
CHECKED_FILTER_DEADLINE=1
CHECKED_KILL_AFTER=1
(
  raw_file=""
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    raw_file="$(find "${pipe_tmp}" -type f -name raw -print -quit)"
    if [[ -n "${raw_file}" ]]; then
      stat -c %a "${raw_file}" > "${mode_note}"
      stat -c %a "$(dirname "${raw_file}")" >> "${mode_note}"
      break
    fi
    sleep 0.05
  done
) &
mode_pid=$!
if checked_pipe "${log}" cat "${slow}"; then
  expect_status "slow producer" 0 0 0
else
  bad "slow producer returned ${?} statuses ${CHECKED_SMOKE_RC:-} ${CHECKED_FILTER_RC:-} ${CHECKED_TEE_RC:-}"
fi
wait "${mode_pid}"
raw_mode="$(sed -n '1p' "${mode_note}")"
dir_mode="$(sed -n '2p' "${mode_note}")"
if [[ "${raw_mode}" == "600" && "${dir_mode}" == "700" ]]; then
  ok "private buffer is mode 600 under 700"
else
  bad "private buffer modes raw=${raw_mode:-missing} dir=${dir_mode:-missing}"
fi
if grep -q 'slow-producer-marker' "${log}"; then
  ok "slow producer published output after the filter budget"
else
  bad "slow producer did not publish its marker"
fi
assert_clean "slow producer"
unset CHECKED_SMOKE_DEADLINE CHECKED_FILTER_DEADLINE CHECKED_KILL_AFTER

# A filter that would have blocked for longer than its budget, started only
# after the command, still fails on its own deadline and publishes nothing.
slow_filter="${work}/slow-filter.sh"
cat > "${slow_filter}" <<'EOF'
#!/bin/bash
printf 'partial-secret-value\n'
sleep 30
EOF
chmod +x "${slow_filter}"
log="${work}/slow-filter.log"
: > "${log}"
CHECKED_SMOKE_DEADLINE=5
CHECKED_FILTER_DEADLINE=1
CHECKED_KILL_AFTER=1
if checked_pipe "${log}" "${slow_filter}" true; then
  bad "slow filter was treated as success"
else
  expect_status "filter deadline" 0 124 0
fi
if grep -q 'partial-secret-value' "${log}"; then
  bad "filter deadline published partial output"
else
  ok "filter deadline published nothing"
fi
assert_clean "filter deadline"
unset CHECKED_SMOKE_DEADLINE CHECKED_FILTER_DEADLINE CHECKED_KILL_AFTER

# Timeout: a grandchild ignores SIGTERM and holds a fifo. The group kill
# must close that fd and remove the private directory without publishing.
hold_fifo="${work}/hold.fifo"
mkfifo "${hold_fifo}"
hold_out="${work}/hold.out"
hold_child="${work}/hold.child"
hold_pg="${work}/hold.pg"
: > "${hold_out}"
timeout 8 cat "${hold_fifo}" > "${hold_out}" &
hold_reader=$!
holder="${work}/holder.sh"
cat > "${holder}" <<EOF
#!/bin/bash
exec 3>"${hold_fifo}"
printf 'x\n' >&3
printf 'truncated-secret-value\n'
bash -c 'trap "" TERM; exec sleep 60' >&3 &
echo \$! > "${hold_child}"
ps -o pgid= -p \$\$ | tr -d '[:space:]' > "${hold_pg}"
wait
EOF
chmod +x "${holder}"
log="${work}/hold.log"
: > "${log}"
CHECKED_SMOKE_DEADLINE=1
CHECKED_FILTER_DEADLINE=2
CHECKED_KILL_AFTER=1
sleep 0.2
if checked_pipe "${log}" cat "${holder}"; then
  bad "held producer was treated as success"
else
  expect_status "group timeout" 124 0 0
fi
note_pg "${hold_pg}"
if [[ -s "${hold_child}" ]] && kill -0 "$(cat "${hold_child}")" 2>/dev/null; then
  bad "group timeout left child $(cat "${hold_child}") alive"
else
  ok "group timeout killed the child"
fi
if [[ -s "${hold_pg}" ]] && pgrep -g "$(cat "${hold_pg}")" >/dev/null 2>&1; then
  bad "group timeout left process group $(cat "${hold_pg}")"
else
  ok "group timeout left no process group"
fi
set +e
wait "${hold_reader}"
reader_rc=$?
set -e
if [[ "${reader_rc}" -eq 0 && "$(tr -d '[:space:]' < "${hold_out}")" == "x" ]]; then
  ok "group timeout closed the held fd"
else
  bad "held fd reader status ${reader_rc} output bytes $(wc -c < "${hold_out}")"
fi
if grep -q 'truncated-secret-value' "${log}"; then
  bad "group timeout published partial output"
else
  ok "group timeout published nothing"
fi
assert_clean "group timeout"
unset CHECKED_SMOKE_DEADLINE CHECKED_FILTER_DEADLINE CHECKED_KILL_AFTER

# The leader itself ignores SIGTERM. kill-after must still reap it.
ignore="${work}/ignore.sh"
ignore_pid="${work}/ignore.pid"
ignore_pg="${work}/ignore.pg"
cat > "${ignore}" <<EOF
#!/bin/bash
echo \$\$ > "${ignore_pid}"
ps -o pgid= -p \$\$ | tr -d '[:space:]' > "${ignore_pg}"
trap "" TERM
sleep 60
EOF
chmod +x "${ignore}"
log="${work}/ignore.log"
: > "${log}"
CHECKED_SMOKE_DEADLINE=1
CHECKED_FILTER_DEADLINE=1
CHECKED_KILL_AFTER=1
if checked_pipe "${log}" cat "${ignore}"; then
  bad "TERM-ignoring command was treated as success"
else
  expect_status "kill-after" 124 0 0
fi
note_pg "${ignore_pg}"
if [[ -s "${ignore_pid}" ]] && kill -0 "$(cat "${ignore_pid}")" 2>/dev/null; then
  bad "kill-after left the leader alive"
else
  ok "kill-after killed the leader"
fi
assert_clean "kill-after"
unset CHECKED_SMOKE_DEADLINE CHECKED_FILTER_DEADLINE CHECKED_KILL_AFTER

# Cancel the shell running checked_pipe. Descendants die, the fd closes,
# and the private directory is removed. Nothing is published.
cancel_fifo="${work}/cancel.fifo"
mkfifo "${cancel_fifo}"
cancel_out="${work}/cancel.out"
cancel_child="${work}/cancel.child"
cancel_pg="${work}/cancel.pg"
: > "${cancel_out}"
timeout 8 cat "${cancel_fifo}" > "${cancel_out}" &
cancel_reader=$!
canceller="${work}/canceller.sh"
cat > "${canceller}" <<EOF
#!/bin/bash
exec 3>"${cancel_fifo}"
printf 'x\n' >&3
printf 'truncated-secret-value\n'
bash -c 'trap "" TERM; exec sleep 60' >&3 &
echo \$! > "${cancel_child}"
ps -o pgid= -p \$\$ | tr -d '[:space:]' > "${cancel_pg}"
wait
EOF
chmod +x "${canceller}"
log="${work}/cancel.log"
: > "${log}"
export CHECKED_SMOKE_DEADLINE=30
export CHECKED_FILTER_DEADLINE=2
export CHECKED_KILL_AFTER=1
sleep 0.2
bash -c "
  set -u
  source '${root}/.github/scripts/checked-pipe.sh'
  checked_pipe '${log}' cat '${canceller}'
" &
cancel_shell=$!
saw_child=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
  if [[ -s "${cancel_child}" ]]; then
    saw_child=1
    break
  fi
  sleep 0.05
done
if [[ "${saw_child}" -eq 1 ]]; then
  kill -TERM "${cancel_shell}" 2>/dev/null || true
else
  bad "cancel test never saw the child"
  kill -TERM "${cancel_shell}" 2>/dev/null || true
fi
set +e
wait "${cancel_shell}"
cancel_rc=$?
set -e
note_pg "${cancel_pg}"
if [[ "${cancel_rc}" -eq 143 ]]; then
  ok "cancel returned 143"
else
  bad "cancel returned ${cancel_rc}"
fi
if [[ -s "${cancel_child}" ]] && kill -0 "$(cat "${cancel_child}")" 2>/dev/null; then
  bad "cancel left child $(cat "${cancel_child}") alive"
else
  ok "cancel killed the child"
fi
if [[ -s "${cancel_pg}" ]] && pgrep -g "$(cat "${cancel_pg}")" >/dev/null 2>&1; then
  bad "cancel left process group $(cat "${cancel_pg}")"
else
  ok "cancel left no process group"
fi
set +e
wait "${cancel_reader}"
cancel_reader_rc=$?
set -e
if [[ "${cancel_reader_rc}" -eq 0 ]]; then
  ok "cancel closed the held fd"
else
  bad "cancel fd reader status ${cancel_reader_rc}"
fi
if grep -q 'truncated-secret-value' "${log}"; then
  bad "cancel published partial output"
else
  ok "cancel published nothing"
fi
assert_clean "cancel"
unset CHECKED_SMOKE_DEADLINE CHECKED_FILTER_DEADLINE CHECKED_KILL_AFTER

# The entry point api-smoke execs. Same group stop, no private publish step.
cli_pid="${work}/cli.pid"
cli_pg="${work}/cli.pg"
cli_cmd="${work}/cli.sh"
cat > "${cli_cmd}" <<EOF
#!/bin/bash
echo \$\$ > "${cli_pid}"
ps -o pgid= -p \$\$ | tr -d '[:space:]' > "${cli_pg}"
trap "" TERM
sleep 60
EOF
chmod +x "${cli_cmd}"
set +e
"${root}/.github/scripts/checked-pipe.sh" supervise 1 1 "${cli_cmd}" >/dev/null
cli_rc=$?
set -e
note_pg "${cli_pg}"
if [[ "${cli_rc}" -eq 124 ]]; then
  ok "supervise entry returned 124"
else
  bad "supervise entry returned ${cli_rc}"
fi
if [[ -s "${cli_pid}" ]] && kill -0 "$(cat "${cli_pid}")" 2>/dev/null; then
  bad "supervise entry left the leader alive"
else
  ok "supervise entry killed the leader"
fi
assert_clean "supervise entry"

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
