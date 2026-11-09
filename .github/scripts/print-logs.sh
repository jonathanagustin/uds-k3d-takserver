#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Print the tail of each log the job is about to upload, in a collapsed group,
# so the job log keeps them when actions/upload-artifact hangs (its step
# timeout has not always stopped it).
# Usage: print-logs.sh PATH... (files or directories; globs expanded by the caller)
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Redact at print time as well as in the earlier file rewrite, so a log copied
# afterwards still cannot put a config secret into the job log.
lines="${PRINT_LOG_LINES:-300}"
max_files="${PRINT_LOG_MAX_FILES:-60}"
count=0
for path in "$@"; do
  [[ -e "${path}" ]] || continue
  while IFS= read -r -d '' file; do
    count=$((count + 1))
    if (( count > max_files )); then
      echo "print-logs: stopped after ${max_files} files; the rest are in the artifact"
      exit 0
    fi
    echo "::group::${file}"
    tmp="$(mktemp)"
    if python3 "${here}/redact-logs.py" --stdout "${file}" > "${tmp}"; then
      tail -n "${lines}" -- "${tmp}" || true
    else
      echo "omitted unsanitizable file"
    fi
    rm -f "${tmp}"
    echo "::endgroup::"
  done < <(find "${path}" -type f \( -name '*.log' -o -name '*.txt' -o -name '*.json' \) -print0 2>/dev/null || true)
done
exit 0
