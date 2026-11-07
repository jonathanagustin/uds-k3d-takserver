#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Redaction has to see the whole stream before a filter or a tail. A tail that
# runs first can keep the second half of a multiline secret after the attribute
# name is gone, and the redactor then has nothing to match.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
filter="${root}/.github/scripts/redact-then-filter.sh"
print_logs="${root}/.github/scripts/print-logs.sh"
dump="${root}/.github/scripts/dump-memory.sh"
sentinel="order-sentinel-value"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

half1="${sentinel:0:6}"
half2="${sentinel:6}"
stream="$(printf 'noise\nsecret="%s\n%s"\nlevel=error after\n' "${half1}" "${half2}")"

tailed="$(printf '%s\n' "${stream}" | tail -n 2)"
if grep -q "${half2}" <<< "${tailed}"; then
  ok "tail-first keeps the secret fragment, which is the bug under test"
else
  bad "the fixture no longer shows the tail-first leak"
fi

filtered="$(printf '%s\n' "${stream}" | "${filter}" --grep 'level=error|secret' --tail 5)"
if grep -q "${sentinel}" <<< "${filtered}" || grep -q "${half1}" <<< "${filtered}" || grep -q "${half2}" <<< "${filtered}"; then
  bad "redact-then-filter printed a secret fragment"
else
  if grep -q 'secret="\[REDACTED\]"' <<< "${filtered}" && grep -q 'level=error after' <<< "${filtered}"; then
    ok "full stream is redacted before the grep and tail"
  else
    bad "redact-then-filter dropped the redacted line: ${filtered}"
  fi
fi

k3s_pat='Starting k3s|level=fatal|level=error|panic|signal|shutting down|killed'
k3s="$(printf 'noise secret="%s"\nlevel=error secret="%s"\nStarting k3s\n' "${sentinel}" "${sentinel}" | "${filter}" --ignore-case --grep "${k3s_pat}" --grep-v 'Sending HTTP/1.1 50[23] response' --tail 40)"
if grep -q "${sentinel}" <<< "${k3s}"; then
  bad "k3s filter printed the secret"
elif grep -q 'level=error secret="\[REDACTED\]"' <<< "${k3s}" && grep -q 'Starting k3s' <<< "${k3s}" && ! grep -q '^noise' <<< "${k3s}"; then
  ok "k3s lines are redacted and then filtered"
else
  bad "k3s filter output was unexpected: ${k3s}"
fi

nul_out="${work}/nul.out"
set +e
printf 'level=error secret="%s"\0more\n' "${sentinel}" | "${filter}" --grep 'level=error' --tail 20 > "${nul_out}"
nul_status=$?
set -e
if (( nul_status == 0 )); then
  bad "NUL k3s stream exited 0"
elif grep -q "${sentinel}" "${nul_out}"; then
  bad "NUL k3s stream printed the secret"
else
  ok "NUL k3s stream is omitted"
fi

log="${work}/api.log"
{
  printf 'secret="%s\n%s"\n' "${half1}" "${half2}"
  printf 'filler\n'
  printf 'level=error tail\n'
} > "${log}"
printed="$(PRINT_LOG_LINES=2 "${print_logs}" "${log}")"
if grep -q "${sentinel}" <<< "${printed}" || grep -q "${half1}" <<< "${printed}" || grep -q "${half2}" <<< "${printed}"; then
  bad "print-logs tailed before redacting"
elif grep -q 'level=error tail' <<< "${printed}"; then
  ok "print-logs redacts the whole file before the tail"
else
  bad "print-logs output was unexpected: ${printed}"
fi

k3s_block="$(awk '/k3s starts, errors, and shutdown lines/{flag=1} flag{print} /omitted unsanitizable k3s log/{if(flag) exit}' "${dump}")"
if grep -q 'redact-then-filter.sh' <<< "${k3s_block}" && ! grep -q '| grep' <<< "${k3s_block}"; then
  ok "dump-memory redacts k3s logs before it filters them"
else
  bad "dump-memory k3s block does not redact first"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
