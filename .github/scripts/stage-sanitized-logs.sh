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
  local dest="$1" marker newer special bad
  marker="${dest}/SANITIZED"
  [[ -f "${marker}" && ! -L "${marker}" ]] || return 1
  [[ -d "${dest}/payload" && ! -L "${dest}/payload" ]] || return 1
  # A listing error is a failure. Hiding it would let a marker through while
  # a fifo, device, or unreadable directory stayed in the tree.
  if ! special="$(find -P "${dest}/payload" \( ! -type d ! -type f \) -print -quit)"; then
    return 1
  fi
  [[ -z "${special}" ]] || return 1
  if ! bad="$(find -P "${dest}/payload" -type f -print | while IFS= read -r path; do
    if unsupported "${path}"; then
      printf '%s\n' "${path}"
      break
    fi
  done)"; then
    return 1
  fi
  [[ -z "${bad}" ]] || return 1
  if ! newer="$(find -P "${dest}/payload" -type f -newer "${marker}" -print -quit)"; then
    return 1
  fi
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
  local status=$?
  # Any failure, including a refused fifo or a redactor error, removes the
  # tree. A successful exit leaves it for the upload.
  if [[ "${status}" -ne 0 ]]; then
    rm -rf "${dest}"
  fi
}
trap cleanup EXIT

# Refuse before cp -a. cp -a would reproduce a symlink, fifo, socket, or device
# node, and opening a fifo to inspect it would block.
refuse_special() {
  local path="$1" found
  if [[ -L "${path}" || -p "${path}" || -S "${path}" || -b "${path}" || -c "${path}" ]]; then
    echo "stage-sanitized-logs: refusing non-regular ${path}" >&2
    return 1
  fi
  if [[ -d "${path}" ]]; then
    if ! found="$(find -P "${path}" \( ! -type d ! -type f \) -print -quit)"; then
      echo "stage-sanitized-logs: could not read ${path}" >&2
      return 1
    fi
    if [[ -n "${found}" ]]; then
      echo "stage-sanitized-logs: refusing non-regular ${found}" >&2
      return 1
    fi
  fi
}

copy_one() {
  local src="$1" parent
  [[ -e "${src}" || -L "${src}" ]] || return 0
  refuse_special "${src}"
  if [[ "${src}" = /* ]]; then
    parent="${dest}/payload$(dirname "${src}")"
  else
    parent="${dest}/payload/$(dirname "${src}")"
  fi
  mkdir -p "${parent}"
  # The source has no non-regular node. cp -a then copies files and directories.
  cp -a "${src}" "${parent}/"
}

for src in "$@"; do
  copy_one "${src}"
done

python3 "${here}/redact-logs.py" "${dest}/payload"
# The marker is last. --check rejects a payload file newer than it, and also
# rejects a symlink, fifo, device, or unsupported file left behind.
printf 'sanitized\n' > "${dest}/SANITIZED"
check_dir "${dest}"
