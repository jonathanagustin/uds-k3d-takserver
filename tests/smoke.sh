#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# TLS handshake and HTTP status for the TAK ports exposed by the passthrough gateway.
# SNI selects the Service port:
#   https://takserver.uds.dev      -> takserver-api-service:8446
#   https://takserver-api.uds.dev  -> takserver-api-service:8443
# On k3d, host port 443 is the tenant gateway. The gateway task records the
# passthrough port-forward in /tmp/tak-gateway-port.
set -euo pipefail

if [[ -z "${TAK_HTTPS_URL:-}" ]] && [[ -f /tmp/tak-gateway-port ]]; then
  port="$(tr -d '[:space:]' < /tmp/tak-gateway-port)"
  TAK_HTTPS_URL="https://takserver.uds.dev:${port}/"
  TAK_CERT_URL="https://takserver-api.uds.dev:${port}/"
fi

if command -v uds >/dev/null 2>&1; then
  uds zarf tools kubectl get package -n takserver takserver
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cert_dir="$("${script_dir}/extract-certs.sh")"

check_endpoint() {
  local name="$1"
  local url="$2"
  local port="$3"
  local code
  local verify
  local cert="${TAK_CLIENT_CERT:-${cert_dir}/admin.pem}"
  local key="${TAK_CLIENT_KEY:-${cert_dir}/admin.key}"
  # generateClusterCerts.sh encrypts the key with the CoreConfig password.
  local pass="${TAK_CLIENT_KEY_PASSPHRASE:-atakatak}"

  echo "TLS handshake and HTTP status for ${name} (${url}, service port ${port})"
  # 8443 requires a client certificate. 8446 does not. With OAuth configured,
  # an anonymous request on 8446 is a redirect to Keycloak.
  code="$(curl -k --cert "${cert}" --key "${key}" --pass "${pass}" -sS -o /dev/null -w "%{http_code}" --max-time 30 "${url}")"
  verify="$(curl -k --cert "${cert}" --key "${key}" --pass "${pass}" -sS -o /dev/null -w "%{ssl_verify_result}" --max-time 30 "${url}")"
  echo "HTTP ${code}; ssl_verify_result ${verify}"

  if [[ -z "${code}" ]] || [[ "${code}" = "000" ]]; then
    echo "No TLS/HTTP response from ${url}." >&2
    return 1
  fi
}

check_endpoint "api-https" "${TAK_HTTPS_URL:-https://takserver.uds.dev/}" "8446"
check_endpoint "api-cert" "${TAK_CERT_URL:-https://takserver-api.uds.dev/}" "8443"

# 8443 and 8089 keep clientAuth. A handshake without a certificate must fail.
# 8089 is the streaming connector, so success with a certificate is a TLS
# handshake rather than an HTTP status.
port="443"
if [[ -f /tmp/tak-gateway-port ]]; then
  port="$(tr -d '[:space:]' < /tmp/tak-gateway-port)"
fi

reject_without_cert() {
  local name="$1"
  local sni="$2"
  local out
  # TLS 1.3 finishes the client side of the handshake before the server checks
  # the client certificate, so CONNECTION ESTABLISHED does not mean the server
  # accepted it. Keep stdin open long enough to read the server's alert.
  out="$({ printf 'GET / HTTP/1.0\r\n\r\n'; sleep 3; } |
    timeout 20 openssl s_client -brief -connect "127.0.0.1:${port}" -servername "${sni}" 2>&1 || true)"
  if ! grep -Eiq 'certificate required|alert number 11[0-9]|bad certificate|handshake failure|unknown ca' <<< "${out}"; then
    echo "${name} did not reject a client with no certificate" >&2
    printf '%s\n' "${out}" >&2
    return 1
  fi
  echo "${name} rejected a client with no certificate"
}

accept_with_cert() {
  local name="$1"
  local sni="$2"
  local out
  out="$(echo | openssl s_client -brief -connect "127.0.0.1:${port}" -servername "${sni}" \
    -cert "${cert_dir}/admin.pem" -key "${cert_dir}/admin.key" -pass "pass:atakatak" 2>&1 || true)"
  if ! grep -q "CONNECTION ESTABLISHED" <<< "${out}"; then
    echo "${name} did not complete TLS with the admin certificate" >&2
    printf '%s\n' "${out}" >&2
    return 1
  fi
  echo "${name} completed TLS with the admin certificate"
}

reject_without_cert "8443" "takserver-api.uds.dev"
reject_without_cert "8089" "takserver-stream.uds.dev"
accept_with_cert "8443" "takserver-api.uds.dev"
accept_with_cert "8089" "takserver-stream.uds.dev"

echo "Gateway endpoints completed a TLS handshake. 8443 and 8089 still require a client certificate."
