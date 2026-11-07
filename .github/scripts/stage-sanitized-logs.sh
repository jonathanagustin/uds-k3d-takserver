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
# actions/upload-artifact v7.0.2 follows symlinks (followSymbolicLinks: true
# in that action's search). A symlink kept in this directory would publish
# the target even when the redactor did not walk it. This script refuses
# symlinks instead of copying them. Archives and other non-text suffixes are
# not left in place: redaction replaces them and this script then fails, and
# the destination is removed. There is no unsanitized copy to upload.
#
# --check fails unless DEST/SANITIZED exists, no payload file is newer than
# that marker, and the payload has no symlink, archive, or other unsupported
# file. A cancelled or partial run must not be uploaded.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

unsupported() {
  local path="$1" lower
  lower="$(printf '%s' "${path}" | tr '[:upper:]' '[:lower:]')"
  [[ "${lower}" == *.gz || "${lower}" == *.tgz || "${lower}" == *.zip || \
    "${lower}" == *.tar || "${lower}" == *.zst || "${lower}" == *.bz2 || \
    "${lower}" == *.xz || "${lower}" == *.7z || "${lower}" == *.png || \
    "${lower}" == *.jpg || "${lower}" == *.jpeg || "${lower}" == *.webp || \
    "${lower}" == *.gif || "${lower}" == *.webm || "${lower}" == *.mp4 ]]
}

check_dir() {
  local dest="$1" marker newer link bad
  marker="${dest}/SANITIZED"
  [[ -f "${marker}" ]] || return 1
  [[ -d "${dest}/payload" ]] || return 1
  link="$(find -P "${dest}/payload" -type l -print -quit 2>/dev/null || true)"
  [[ -z "${link}" ]] || return 1
  bad="$(find -P "${dest}/payload" -type f -print 2>/dev/null | while IFS= read -r path; do
    if unsupported "${path}"; then
      printf '%s\n' "${path}"
      break
    fi
  done)"
  [[ -z "${bad}" ]] || return 1
  newer="$(find -P "${dest}/payload" -type f -newer "${marker}" -print -quit 2>/dev/null || true)"
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
  local src="$1" parent link
  [[ -e "${src}" || -L "${src}" ]] || return 0
  if [[ -L "${src}" ]]; then
    echo "stage-sanitized-logs: refusing symlink ${src}" >&2
    return 1
  fi
  if [[ -d "${src}" ]]; then
    link="$(find -P "${src}" -type l -print -quit 2>/dev/null || true)"
    if [[ -n "${link}" ]]; then
      echo "stage-sanitized-logs: refusing symlink ${link}" >&2
      return 1
    fi
  fi
  if [[ "${src}" = /* ]]; then
    parent="${dest}/payload$(dirname "${src}")"
  else
    parent="${dest}/payload/$(dirname "${src}")"
  fi
  mkdir -p "${parent}"
  # The source has no symlink. cp -a then copies regular files and directories.
  cp -a "${src}" "${parent}/"
}

for src in "$@"; do
  copy_one "${src}"
done

python3 "${here}/redact-logs.py" "${dest}/payload"
# The marker is last. --check rejects a payload file newer than it, and also
# rejects a symlink or unsupported file that a later bug left behind.
printf 'sanitized\n' > "${dest}/SANITIZED"
check_dir "${dest}"
trap - ERR INT TERM
