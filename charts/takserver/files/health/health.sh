#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# SPIKE: TAK client-port health for UDS Core uptime checks.
# A loop checks each TAK client port through the passthrough gateway, the
# way a TAK client reaches it, with a client certificate. It writes one
# result file per check. ncat answers each HTTP request from those files, so
# a probe never opens a TAK connection itself and gets an answer in
# milliseconds.
#   /stream  8089: mutual TLS, then a CoT ping (t-x-c-t). Passes on TAK's pong.
#   /api     8443 (443 SNI takserver-api): mutual TLS, GET /Marti/api/version.
#   /enroll  8446: TLS, GET /login. Passes on 200 from TAK.
# A result older than STALE_SECONDS answers 503.
set -uo pipefail

gw="${GATEWAY:?}"
domain="${DOMAIN:?}"
dir="${STATE_DIR:-/tmp/health}"
interval="${INTERVAL_SECONDS:-15}"
stale="${STALE_SECONDS:-90}"
certs="${CERT_DIR:-/certs}"
mkdir -p "${dir}"

tls() {
  # $1 port, $2 SNI, $3 client cert (yes|no). Reads the request on stdin.
  local args=(-quiet -verify_return_error -CAfile "${certs}/ca.pem"
    -connect "${gw}:$1" -servername "$2")
  if [[ "$3" == "yes" ]]; then
    args+=(-cert "${certs}/client.pem" -key "${certs}/client.key" -pass env:KEY_PASS)
  fi
  timeout 10 openssl s_client "${args[@]}" 2>&1
}

record() {
  # $1 name, $2 0|1, $3 detail
  printf '%s %s %s\n' "$(date +%s)" "$2" "$3" > "${dir}/$1.tmp"
  mv "${dir}/$1.tmp" "${dir}/$1"
  echo "check $1 ok=$2 $3"
}

check_stream() {
  local now out
  now="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
  out="$({ sleep 1
    printf "<event version='2.0' uid='uds-tak-health' type='t-x-c-t' how='h-g-i-g-o' time='%s' start='%s' stale='%s'><point lat='0' lon='0' hae='0' ce='9999999' le='9999999'/><detail/></event>" "${now}" "${now}" "${now}"
    sleep 3; } | tls 8089 "takserver-stream.${domain}" yes)"
  if grep -q "t-x-c-t-r" <<< "${out}"; then
    record stream 1 "pong"
  else
    record stream 0 "$(tr '\n' ' ' <<< "${out}" | cut -c1-200)"
  fi
}

check_http() {
  # $1 name, $2 port, $3 SNI, $4 path, $5 client cert
  local out status
  out="$(printf 'GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' "$4" "$3" | tls "$2" "$3" "$5")"
  status="$(grep -m1 -o '^HTTP/1\.[01] [0-9][0-9][0-9]' <<< "${out}")"
  status="${status##* }"
  if [[ "${status}" == "200" ]]; then
    record "$1" 1 "status 200"
  else
    record "$1" 0 "status ${status:-none}: $(tr '\n' ' ' <<< "${out}" | cut -c1-200)"
  fi
}

serve() {
  local line path name ts ok detail code body now
  IFS= read -r line || exit 0
  while IFS= read -r h; do [[ "${h}" == $'\r' || -z "${h}" ]] && break; done
  read -r _ path _ <<< "${line}"
  case "${path}" in
    /stream) name=stream ;;
    /api) name=api ;;
    /enroll) name=enroll ;;
    /healthz) printf 'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nok\n'; exit 0 ;;
    *) printf 'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'; exit 0 ;;
  esac
  now="$(date +%s)"
  code="503 Service Unavailable"
  body="no result yet"
  if read -r ts ok detail < "${dir}/${name}" 2>/dev/null; then
    body="${name} ok=${ok} age=$((now - ts))s ${detail}"
    if [[ "${ok}" == "1" ]] && (( now - ts <= stale )); then
      code="200 OK"
    fi
  fi
  body="${body}"$'\n'
  printf 'HTTP/1.1 %s\r\nContent-Type: text/plain\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s' "${code}" "${#body}" "${body}"
}

case "${1:-}" in
  serve) serve ;;
  *)
    (
      while true; do
        check_stream
        check_http api 443 "takserver-api.${domain}" /Marti/api/version yes
        check_http enroll 8446 "takserver-stream.${domain}" /login no
        sleep "${interval}"
      done
    ) &
    exec ncat -lk -p "${PORT:-8081}" --sh-exec "/bin/bash /health/health.sh serve"
    ;;
esac
