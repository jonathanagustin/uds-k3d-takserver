#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
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
# the target even when the redactor did not walk it. This script does not
# copy symlinks. save-logs copies /var/log with docker cp, which keeps the
# kubelet aliases in containers/*.log. Kubelet passes the absolute CRI log
# path to os.Symlink, so the text is /var/log/pods/... even after the tree
# is copied to /tmp/uds-containerd-logs. A relative ../pods/... link is the
# same file. Either form is omitted when one lexical hop names a regular
# file already under this tree's pods/ directory. The /var/log/pods prefix
# is rewritten onto that directory and is never opened on the host. Every
# other symlink still fails the staging and removes the destination. A
# relative source directory keeps the path it was given, so `out` is
# payload/out. Archives and other non-text suffixes are not left in place:
# redaction replaces them and this script then fails. There is no
# unsanitized copy to upload.
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

# Lexical only. This does not stat or follow the path.
normalize_path() {
  local path="$1" part joined=""
  local -a segments=() parts=()
  local abs=0
  [[ "${path}" == /* ]] && abs=1
  IFS='/' read -r -a segments <<< "${path}"
  for part in "${segments[@]}"; do
    case "${part}" in
      ""|.) ;;
      ..)
        if ((${#parts[@]} > 0)); then
          unset 'parts[-1]'
        elif ((abs == 0)); then
          parts+=("..")
        fi
        ;;
      *) parts+=("${part}") ;;
    esac
  done
  if ((${#parts[@]} == 0)); then
    if ((abs == 1)); then
      printf '/\n'
    else
      printf '.\n'
    fi
    return 0
  fi
  for part in "${parts[@]}"; do
    joined="${joined}/${part}"
  done
  if ((abs == 0)); then
    joined="${joined#/}"
  fi
  printf '%s\n' "${joined}"
}

# True when every component of TARGET under ROOT is a real directory and the
# final component is a regular file. A symlink component returns false before
# anything follows it.
regular_under() {
  local root="$1" target="$2" rel="${2#"${1}/"}" cur rest part
  [[ "${target}" == "${root}/"* && -n "${rel}" && "${rel}" != /* ]] || return 1
  cur="${root}"
  rest="${rel}"
  while [[ "${rest}" == */* ]]; do
    part="${rest%%/*}"
    [[ -n "${part}" && "${part}" != "." && "${part}" != ".." ]] || return 1
    cur="${cur}/${part}"
    [[ -L "${cur}" ]] && return 1
    [[ -d "${cur}" ]] || return 1
    rest="${rest#*/}"
  done
  [[ -n "${rest}" && "${rest}" != "." && "${rest}" != ".." ]] || return 1
  cur="${cur}/${rest}"
  [[ -L "${cur}" ]] && return 1
  [[ -f "${cur}" ]]
}

# Map a kubelet alias onto the regular file in this collected tree.
# Absolute /var/log/pods/... is the CRI path kubelet stored. After docker cp
# relocates /var/log to this directory, that prefix is only a spelling of
# ROOT/pods. This function does not stat or open the absolute path.
relocate_pod_log() {
  local root="$1" raw="$2" suffix relocated
  [[ "${raw}" == /var/log/pods/* ]] || return 1
  suffix="${raw#/var/log/pods/}"
  [[ -n "${suffix}" && "${suffix}" != /* ]] || return 1
  relocated="$(normalize_path "${root}/pods/${suffix}")"
  printf '%s\n' "${relocated}"
}

# Kubelet writes containers/<pod>_<namespace>_<container>-<id>.log as one
# symlink to the CRI log under pods/. The pods file is copied on its own.
container_alias() {
  local link="$1" root="$2" raw target parent_dir
  [[ -L "${link}" ]] || return 1
  parent_dir="$(dirname -- "${link}")"
  [[ "$(basename -- "${parent_dir}")" == "containers" ]] || return 1
  raw="$(readlink -- "${link}")"
  [[ -n "${raw}" ]] || return 1
  if [[ "${raw}" == /* ]]; then
    target="$(relocate_pod_log "${root}" "${raw}")" || return 1
  else
    target="$(normalize_path "${parent_dir}/${raw}")"
  fi
  [[ "${target}" == "${root}/pods/"* ]] || return 1
  regular_under "${root}" "${target}"
}

# Refuse before copying. cp -a would reproduce a symlink, fifo, socket, or
# device node, and opening a fifo to inspect it would block. A kubelet
# container alias is not a refusal: the regular pods file is the log.
refuse_special() {
  local path="$1" root="${2:-}" found item
  if [[ -L "${path}" || -p "${path}" || -S "${path}" || -b "${path}" || -c "${path}" ]]; then
    if [[ -n "${root}" && -L "${path}" ]] && container_alias "${path}" "${root}"; then
      return 0
    fi
    echo "stage-sanitized-logs: refusing non-regular ${path}" >&2
    return 1
  fi
  if [[ -d "${path}" ]]; then
    if [[ -z "${root}" ]]; then
      root="${path%/}"
    fi
    if ! found="$(find -P "${root}" \( ! -type d ! -type f \) -print)"; then
      echo "stage-sanitized-logs: could not read ${path}" >&2
      return 1
    fi
    while IFS= read -r item; do
      [[ -z "${item}" ]] && continue
      if [[ -L "${item}" ]] && container_alias "${item}" "${root}"; then
        continue
      fi
      echo "stage-sanitized-logs: refusing non-regular ${item}" >&2
      return 1
    done <<< "${found}"
  fi
}

# Copy a directory without reproducing symlinks. Allowed container aliases
# are skipped. Any other non-regular node is refused and nothing is published.
copy_directory() {
  local root="$1" path rel parent dest_root
  # Keep the source spelling. Absolutizing a relative directory with pwd
  # would publish payload/<checkout>/out instead of payload/out. An absolute
  # /tmp/... source stays absolute so the workflow upload of payload/tmp
  # still matches.
  if [[ "${root}" == /* ]]; then
    dest_root="${dest}/payload${root}"
  else
    dest_root="${dest}/payload/${root}"
  fi
  while IFS= read -r -d '' path; do
    if [[ "${path}" == "${root}" ]]; then
      continue
    fi
    if [[ -L "${path}" ]]; then
      if container_alias "${path}" "${root}"; then
        continue
      fi
      echo "stage-sanitized-logs: refusing non-regular ${path}" >&2
      return 1
    fi
    if [[ -d "${path}" ]]; then
      continue
    fi
    if [[ -f "${path}" ]]; then
      rel="${path#"${root}"}"
      parent="${dest_root}${rel%/*}"
      mkdir -p "${parent}"
      cp -a "${path}" "${parent}/"
      continue
    fi
    echo "stage-sanitized-logs: refusing non-regular ${path}" >&2
    return 1
  done < <(find -P "${root}" -print0)
}

copy_one() {
  local src="$1" parent root
  [[ -e "${src}" || -L "${src}" ]] || return 0
  if [[ -d "${src}" && ! -L "${src}" ]]; then
    root="${src%/}"
    refuse_special "${src}" "${root}"
    copy_directory "${root}"
    return 0
  fi
  refuse_special "${src}"
  if [[ "${src}" = /* ]]; then
    parent="${dest}/payload$(dirname "${src}")"
  else
    parent="${dest}/payload/$(dirname "${src}")"
  fi
  mkdir -p "${parent}"
  # The source has no non-regular node. cp -a then copies this file.
  cp -a "${src}" "${parent}/"
}

for src in "$@"; do
  copy_one "${src}"
done

set +e
python3 "${here}/redact-logs.py" "${dest}/payload"
redact_rc=$?
set -e
# 1 is a read or listing failure. The tree may still hold original bytes.
if [[ "${redact_rc}" -eq 1 ]]; then
  exit 1
fi
if [[ "${redact_rc}" -ne 0 && "${redact_rc}" -ne 2 ]]; then
  exit "${redact_rc}"
fi
# The redactor replaces an archive or image with a stub but keeps the name.
# --check rejects that name, so drop it. A pod log that was not valid text
# keeps a regular omission stub and the other logs stay.
while IFS= read -r -d '' path; do
  if unsupported "${path}"; then
    rm -f "${path}"
  fi
done < <(find -P "${dest}/payload" -type f -print0)
if ! find -P "${dest}/payload" -type f -print -quit | grep -q .; then
  echo "stage-sanitized-logs: no log text remained" >&2
  exit 1
fi
# The marker is last. --check rejects a payload file newer than it, and also
# rejects a symlink, fifo, device, or unsupported file left behind.
printf 'sanitized\n' > "${dest}/SANITIZED"
check_dir "${dest}"
