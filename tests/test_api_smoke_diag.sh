#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The restore log's pipeline has three processes. Reading PIPESTATUS one
# index at a time clears it, and set -u then aborts a successful smoke.
# These runs use the same function as backup-restore.sh.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=.github/scripts/checked-pipe.sh
source "${root}/.github/scripts/checked-pipe.sh"
filter="${root}/.github/scripts/redact-then-filter.sh"
sentinel="smoke-sentinel-value"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

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

log="${work}/success.log"
: > "${log}"
if checked_pipe "${log}" cat true; then
  expect_status "success" 0 0 0
else
  bad "success pipeline returned ${?} statuses ${CHECKED_SMOKE_RC:-} ${CHECKED_FILTER_RC:-} ${CHECKED_TEE_RC:-}"
fi

log="${work}/smoke-fail.log"
: > "${log}"
if checked_pipe "${log}" cat false; then
  bad "failing command was treated as success"
else
  expect_status "command failure" 1 0 0
fi

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

url='https://sso.example/auth?code='"${sentinel}"'&access_token='"${sentinel}"'#frag'
landed="${url%%[\?#]*}"
if [[ "${landed}" == "https://sso.example/auth" && "${landed}" != *"${sentinel}"* ]]; then
  ok "login URL keeps no query or fragment"
else
  bad "login URL strip left ${landed}"
fi

if grep -q 'response body omitted' "${root}/tests/api-smoke.sh" \
  && ! grep -q 'out\[:2000\]' "${root}/tests/api-smoke.sh" \
  && ! grep -q '| head -n' "${root}/tests/api-smoke.sh"; then
  ok "api-smoke omits response bodies"
else
  bad "api-smoke still prints a cut response body"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
