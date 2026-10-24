#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Ask loki-gateway for log lines over the last hour. Exit 0 when the response
# contains one of the match strings. Exit 3 when no Loki Service exists so a
# slim cluster can skip. An instant query is one nanosecond wide and comes
# back empty for these lines, so this uses query_range.
set -euo pipefail

body_has_match() {
  local body="${1}"
  shift
  local needle
  for needle in "${@}"; do
    if grep -F -q -- "${needle}" <<< "${body}"; then
      return 0
    fi
  done
  return 1
}

loki_query_url() {
  local query="${1}" start="${2}" end="${3}"
  python3 -c 'import urllib.parse, sys
query, start, end = sys.argv[1:]
print(
    "http://127.0.0.1:3100/loki/api/v1/query_range?query="
    + urllib.parse.quote(query, safe="")
    + "&start=" + start
    + "&end=" + end
    + "&limit=200&direction=backward"
)
' "${query}" "${start}" "${end}"
}

if [[ "${QUERY_LOKI_SOURCE_ONLY:-}" == "1" ]]; then
  return 0
fi

query=""
attempts="24"
pause="5"
matches=()

while [[ "${#}" -gt 0 ]]; do
  case "${1}" in
    --query)
      query="${2:?--query needs a value}"
      shift 2
      ;;
    --match)
      matches+=("${2:?--match needs a value}")
      shift 2
      ;;
    --attempts)
      attempts="${2:?--attempts needs a value}"
      shift 2
      ;;
    --pause)
      pause="${2:?--pause needs a value}"
      shift 2
      ;;
    *)
      echo "unknown argument: ${1}" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${query}" || "${#matches[@]}" -eq 0 ]]; then
  echo "query and at least one match are required" >&2
  exit 2
fi
if [[ ! "${attempts}" =~ ^[1-9][0-9]*$ || ! "${pause}" =~ ^[0-9]+$ ]]; then
  echo "attempts and pause must be non-negative integers, and attempts at least 1" >&2
  exit 2
fi

svcs="$(uds zarf tools kubectl get svc -A -o name 2>/dev/null || true)"
if ! grep -qi 'loki' <<< "${svcs}"; then
  echo "no loki service"
  exit 3
fi

uds zarf tools kubectl port-forward -n loki svc/loki-gateway 3100:80 >/tmp/loki-pf.log 2>&1 &
pf_pid="${!}"
cleanup() {
  kill "${pf_pid}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

found="0"
try="1"
while [[ "${try}" -le "${attempts}" ]]; do
  end="$(python3 -c 'import time; print(time.time_ns())')"
  start="$((end - 3600000000000))"
  url="$(loki_query_url "${query}" "${start}" "${end}")"
  body="$(curl -fsS --max-time 10 "${url}" || true)"
  if body_has_match "${body}" "${matches[@]}"; then
    found="1"
    break
  fi
  if [[ "${try}" -lt "${attempts}" ]]; then
    sleep "${pause}"
  fi
  try="$((try + 1))"
done

if [[ "${found}" != "1" ]]; then
  echo "Loki query did not return a matching line" >&2
  echo "query: ${query}" >&2
  cat /tmp/loki-pf.log >&2 || true
  exit 1
fi
