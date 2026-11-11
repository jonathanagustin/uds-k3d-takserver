#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# Retain only complete, redacted failure evidence; never upload raw captures.
set -euo pipefail
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output="${1:?new diagnostic directory required}"
mkdir "${output}"
private="$(mktemp -d)"
trap 'rm -rf "${private}"' EXIT
report="${private}/report"
: > "${report}"
capture() {
  local label="$1" seconds="$2"
  shift 2
  printf '\n--- %s\n' "${label}" >> "${report}"
  # A failed, timed-out or oversized capture is omitted in full. In particular,
  # never sanitize a truncated multiline secret and publish its trailing fragment.
  if timeout --kill-after=2 "${seconds}" "$@" 2>&1 | head -c 4194305 > "${private}/raw" \
    && [[ $(wc -c < "${private}/raw") -le 4194304 ]]; then
    "${here}/redact-then-filter.sh" --tail 200 < "${private}/raw" >> "${report}"
  else
    echo 'omitted: capture failed, exceeded four MiB, or reached its deadline' >> "${report}"
  fi
}
capture 'runner memory, restarts and CoreConfig summaries' 90 "${here}/dump-memory.sh"
for workload in api messaging config plugins; do
  for container in "takserver-${workload}" wait-deps; do
    capture "${workload}/${container} current" 10 uds zarf tools kubectl logs "deploy/takserver-${workload}" -n takserver -c "${container}"
    capture "${workload}/${container} previous" 10 uds zarf tools kubectl logs "deploy/takserver-${workload}" -n takserver -c "${container}" --previous
  done
done
# Only this completed, sanitized file is eligible for the artifact upload.
mv "${report}" "${output}/tak-startup.log"
cat "${output}/tak-startup.log"
