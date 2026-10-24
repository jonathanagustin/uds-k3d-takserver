#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Matcher and URL builder only. This does not query a cluster.
set -euo pipefail

root="$(cd "$(dirname "${0}")/.." && pwd)"
cd "${root}"

QUERY_LOKI_SOURCE_ONLY=1
# shellcheck source=tests/query-loki.sh
source tests/query-loki.sh

body_has_match "Started TAK Server" "Started TAK Server" "TAK Server version"
body_has_match "line basemap: OSM" "ok - TAK user" "basemap:"

if body_has_match '{"stream":{"namespace":"takserver"},"values":[]}' "Started TAK Server" "Tomcat started on port"; then
  echo "a namespace label counted as a TAK startup line" >&2
  exit 1
fi

url="$(loki_query_url '{namespace="takserver"} |= "uds-std-ports-1"' "10" "20")"
case "${url}" in
  http://127.0.0.1:3100/loki/api/v1/query_range\?query=*) ;;
  *)
    echo "unexpected url ${url}" >&2
    exit 1
    ;;
esac
if ! grep -q '%7Bnamespace%3D%22takserver%22%7D%20%7C%3D%20%22uds-std-ports-1%22' <<< "${url}"; then
  echo "query was not encoded: ${url}" >&2
  exit 1
fi
if ! grep -q 'start=10&end=20&limit=200&direction=backward' <<< "${url}"; then
  echo "range missing: ${url}" >&2
  exit 1
fi

set +e
./tests/query-loki.sh >/tmp/query-loki-usage.out 2>/tmp/query-loki-usage.err
usage_rc="${?}"
set -e
if [[ "${usage_rc}" -ne 2 ]]; then
  echo "missing arguments exited ${usage_rc}, expected 2" >&2
  exit 1
fi

set +e
./tests/query-loki.sh --query '{namespace="takserver"}' --match 'Started TAK Server' --attempts 0 >/tmp/query-loki-attempts.out 2>/tmp/query-loki-attempts.err
attempts_rc="${?}"
set -e
if [[ "${attempts_rc}" -ne 2 ]]; then
  echo "attempts 0 exited ${attempts_rc}, expected 2" >&2
  exit 1
fi

echo "ok"
