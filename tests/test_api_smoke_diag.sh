#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# A failed API smoke used to keep a response body that had already been cut,
# so a multiline secret survived. The diagnostic path redacts the whole body
# first. The restore log must not store the smoke's raw stdout.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
filter="${root}/.github/scripts/redact-then-filter.sh"
smoke="${root}/tests/api-smoke.sh"
restore="${root}/tests/backup-restore.sh"
sentinel="smoke-sentinel-value"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

half1="${sentinel:0:6}"
half2="${sentinel:6}"
{
  printf 'noise\n'
  printf 'secret="%s\n%s"\n' "${half1}" "${half2}"
  printf 'HTTP 500\n'
} > "${work}/body"

# Same order as redact_diag: the whole body, then a tail.
filtered="$(${filter} --tail 20 < "${work}/body")"
if grep -q "${sentinel}" <<< "${filtered}" || grep -q "${half1}" <<< "${filtered}" || grep -q "${half2}" <<< "${filtered}"; then
  bad "failure diagnostic kept a secret fragment"
elif grep -q 'secret="\[REDACTED\]"' <<< "${filtered}" && grep -q 'HTTP 500' <<< "${filtered}"; then
  ok "failure body is redacted before the tail"
else
  bad "failure diagnostic dropped the redacted line"
fi

if grep -q 'out\[:2000\]' "${smoke}" || grep -q 'subs\[:2000\]' "${smoke}"; then
  bad "api-smoke still slices a response before redaction"
elif grep -q '| head -n' "${smoke}"; then
  bad "api-smoke still heads a stream before redaction"
else
  ok "api-smoke does not cut a body before redaction"
fi

if grep -Eq 'api-smoke\.sh.*redact-then-filter\.sh.*tee -a' "${restore}"; then
  ok "restore log tees the redacted smoke"
else
  bad "restore log does not redact before tee"
fi

export REDACT_LOGS="${root}/.github/scripts/redact-logs.py"
python_out="$(python3 - "${sentinel}" <<'PY'
import os, subprocess, sys
sentinel = sys.argv[1]
text = 'secret="' + sentinel[:6] + '\n' + sentinel[6:] + '"\nHTTP 500\n'

def diag(label, body):
    script = os.environ["REDACT_LOGS"]
    proc = subprocess.run([sys.executable, script, "-"], input=body.encode(), capture_output=True)
    if proc.returncode != 0:
        print("omitted unsanitizable diagnostic")
        return
    redacted = proc.stdout.decode()
    print(label)
    print("\n".join(redacted.splitlines()[:40]))

diag("clientEndPoints", text)
PY
)"
if grep -q "${sentinel}" <<< "${python_out}"; then
  bad "python failure diagnostic printed the sentinel"
else
  ok "python failure diagnostic omits the sentinel"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
