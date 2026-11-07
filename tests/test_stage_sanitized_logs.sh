#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The staging script is what CI uploads. A failed or partial sanitize must
# not leave a directory that --check accepts.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stage="${root}/.github/scripts/stage-sanitized-logs.sh"
sentinel="stage-sentinel-value"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fails=0
ok() { echo "ok: $1"; }
bad() { echo "not ok: $1" >&2; fails=$((fails + 1)); }

src="${work}/src"
mkdir -p "${src}"
printf 'secret="%s"\n' "${sentinel}" > "${src}/api.log"
dest="${work}/staged"
if "${stage}" "${dest}" "${src}/api.log"; then
  copied="$(find "${dest}/payload" -type f -name api.log -print -quit)"
  if "${stage}" --check "${dest}" \
    && [[ -n "${copied}" ]] \
    && ! grep -q "${sentinel}" "${copied}" \
    && grep -q 'secret="\[REDACTED\]"' "${copied}"; then
    ok "clean log is staged and the value is gone"
  else
    bad "clean log was not staged safely"
  fi
else
  bad "clean log staging failed"
fi

nul="${work}/nul.log"
printf 'secret="%s"\n' "${sentinel}" > "${nul}"
printf '\0' >> "${nul}"
dirty="${work}/dirty"
if "${stage}" "${dirty}" "${nul}"; then
  bad "NUL log staging exited 0"
else
  if [[ -e "${dirty}" ]]; then
    bad "failed staging left ${dirty}"
  elif "${stage}" --check "${dirty}" 2>/dev/null; then
    bad "missing staging directory passed --check"
  else
    ok "NUL log removes the staging directory and --check fails"
  fi
fi

partial="${work}/partial"
mkdir -p "${partial}/payload"
printf 'secret="%s"\n' "${sentinel}" > "${partial}/payload/late.log"
if "${stage}" --check "${partial}"; then
  bad "staging without a marker passed --check"
else
  ok "staging without a marker is not uploadable"
fi

marked="${work}/marked"
mkdir -p "${marked}/payload"
printf 'plain\n' > "${marked}/payload/a.log"
printf 'sanitized\n' > "${marked}/SANITIZED"
sleep 1
printf 'secret="%s"\n' "${sentinel}" > "${marked}/payload/late.log"
if "${stage}" --check "${marked}"; then
  bad "a file newer than the marker passed --check"
else
  ok "a file written after the marker is not uploadable"
fi

if (( fails > 0 )); then
  echo "${fails} case(s) failed" >&2
  exit 1
fi
