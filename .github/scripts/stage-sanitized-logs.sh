#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Copy logs into a new directory, redact them there, and mark the directory
# only after that finishes. Upload steps must use this directory and must run
# only when this script exits 0.
#
#   stage-sanitized-logs.sh DEST SRC...
#   stage-sanitized-logs.sh --check DEST
#
# --check fails unless DEST/SANITIZED exists and no payload file is newer
# than that marker. A cancelled or partial run has no marker, or has files
# written after it, and must not be uploaded.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_dir() {
  local dest="$1" marker newer
  marker="${dest}/SANITIZED"
  [[ -f "${marker}" ]] || return 1
  [[ -d "${dest}/payload" ]] || return 1
  newer="$(find "${dest}/payload" -type f -newer "${marker}" -print -quit 2>/dev/null || true)"
  [[ -z "${newer}" ]]
}

if [[ "${1:-}" == "--check" ]]; then
  check_dir "${2:?}"
  exit $?
fi

dest="${1:?}"
shift
rm -rf "${dest}"
mkdir -p "${dest}/payload"

cleanup() {
  rm -rf "${dest}"
}
trap cleanup ERR INT TERM

copy_one() {
  local src="$1" parent
  [[ -e "${src}" ]] || return 0
  if [[ "${src}" = /* ]]; then
    parent="${dest}/payload$(dirname "${src}")"
  else
    parent="${dest}/payload/$(dirname "${src}")"
  fi
  mkdir -p "${parent}"
  cp -a "${src}" "${parent}/"
}

for src in "$@"; do
  copy_one "${src}"
done

python3 "${here}/redact-logs.py" "${dest}/payload"
# The marker is last. --check rejects a payload file newer than it.
printf 'sanitized\n' > "${dest}/SANITIZED"
check_dir "${dest}"
trap - ERR INT TERM
