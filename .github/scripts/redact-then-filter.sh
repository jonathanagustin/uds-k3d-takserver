#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Redact all of stdin, then filter or tail the redacted text.
#
#   redact-then-filter.sh [--ignore-case] [--grep ERE] [--grep-v ERE]
#       [--before N] [--after N] [--tail N]
#
# Filtering before redaction can keep a fragment of a multiline secret after
# the attribute name has been cut off. This script does not print stdin until
# redaction has accepted the whole stream. On failure it prints one omission
# line and exits non-zero.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ignore_case=0
grep_pat=""
grep_v=""
before=""
after=""
tail_n=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ignore-case) ignore_case=1; shift ;;
    --grep) grep_pat="${2:?}"; shift 2 ;;
    --grep-v) grep_v="${2:?}"; shift 2 ;;
    --before) before="${2:?}"; shift 2 ;;
    --after) after="${2:?}"; shift 2 ;;
    --tail) tail_n="${2:?}"; shift 2 ;;
    *)
      echo "redact-then-filter: unknown argument" >&2
      exit 2
      ;;
  esac
done

tmp="$(mktemp)"
trap 'rm -f "${tmp}" "${tmp}.filtered"' EXIT

if ! python3 "${here}/redact-logs.py" - > "${tmp}"; then
  echo "omitted: unsanitizable stream"
  exit 1
fi

grep_args=()
if (( ignore_case )); then
  grep_args+=(-i)
fi
if [[ -n "${before}" ]]; then
  grep_args+=(-B "${before}")
fi
if [[ -n "${after}" ]]; then
  grep_args+=(-A "${after}")
fi
if [[ -n "${grep_pat}" ]]; then
  grep "${grep_args[@]}" -E "${grep_pat}" "${tmp}" > "${tmp}.filtered" || true
  mv "${tmp}.filtered" "${tmp}"
fi
if [[ -n "${grep_v}" ]]; then
  grep -E -v "${grep_v}" "${tmp}" > "${tmp}.filtered" || true
  mv "${tmp}.filtered" "${tmp}"
fi
if [[ -n "${tail_n}" ]]; then
  tail -n "${tail_n}" "${tmp}"
else
  cat "${tmp}"
fi
