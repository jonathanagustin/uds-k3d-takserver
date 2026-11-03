#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Issue the client certificate the tak-health pod uses to reach TAK's
# client ports, and store it in Secret HEALTH_SECRET as ca.pem, client.pem,
# and client.key. The certificate is signed by the deploy-time CA, so TAK
# accepts the handshake. It is not added to TAK's user file, so it has no
# TAK groups and no admin role. The key is not encrypted, so the health pod
# does not need the keystore password.
# Runs in the cert-init Job after publish-cert-configmap.sh and before
# move-ca-key.sh. It issues a new certificate only when the Secret is
# missing, signed by a different CA, or expires within 30 days.

# Retry a refused or reset handshake. The k3s port-6443 tunnel refuses new
# connections for several seconds after this hook reads cert-migration, which
# is longer than five one-second tries. Twenty tries, two seconds apart.
# --retry-all-errors covers a TLS reset (curl 35 or 56). --retry-connrefused
# covers ECONNREFUSED. An HTTP status is not an error unless the caller
# passes -f, so 409 still returns to the caller. The config image is UBI9,
# whose curl is new enough for --retry-all-errors.
api_curl() {
  curl \
    --silent \
    --show-error \
    --retry 20 \
    --retry-delay 2 \
    --retry-all-errors \
    --retry-connrefused \
    --connect-timeout 5 \
    "$@"
}

set -euo pipefail

secret="${HEALTH_SECRET:-tak-health-client}"
cn="${HEALTH_CN:-tak-health}"
if [[ -z "${CAPASS:-}" ]]; then
  echo "CAPASS is not set. Secret takserver-keystore did not reach this Job." >&2
  exit 1
fi
pass="${CAPASS}"

# SA_DIR, KUBE_API, and CA_KEY_FILE are for tests/test_issue_health_cert.py.
sa="${SA_DIR:-/var/run/secrets/kubernetes.io/serviceaccount}"
ns="$(cat "${sa}/namespace")"
token="$(cat "${sa}/token")"
ca="${sa}/ca.crt"
base="${KUBE_API:-https://kubernetes.default.svc}/api/v1/namespaces/${ns}"
ca_key_file="${CA_KEY_FILE:-/opt/tak/certs/files/ca-do-not-share.key}"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

api_curl -f --cacert "${ca}" -H "Authorization: Bearer ${token}" \
  "${base}/configmaps/cert-migration" > "${work}/cm.json"

# Pull one key out of a JSON object. Base64 has no quotes.
field() {
  grep -o "\"$1\": *\"[^\"]*\"" "$2" | head -n 1 | sed 's/.*: *"\(.*\)"/\1/'
}

ca_b64="$(field ca.pem "${work}/cm.json" || true)"
if [[ -z "${ca_b64}" ]]; then
  echo "ConfigMap cert-migration has no ca.pem" >&2
  exit 1
fi
printf '%s' "${ca_b64}" | base64 -d > "${work}/ca.pem"

code="$(api_curl -o "${work}/secret.json" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" "${base}/secrets/${secret}")"
method="POST"
url="${base}/secrets"
if [[ "${code}" == "200" ]]; then
  method="PUT"
  url="${base}/secrets/${secret}"
  old_ca="$(field ca.pem "${work}/secret.json" || true)"
  old_cert="$(field client.pem "${work}/secret.json" || true)"
  if [[ -n "${old_cert}" ]] && [[ "${old_ca}" == "$(base64 -w 0 "${work}/ca.pem")" ]]; then
    printf '%s' "${old_cert}" | base64 -d > "${work}/old.pem"
    if openssl verify -CAfile "${work}/ca.pem" "${work}/old.pem" >/dev/null 2>&1 \
      && openssl x509 -in "${work}/old.pem" -noout -checkend 2592000 >/dev/null; then
      echo "Secret ${secret} already has a current client certificate"
      exit 0
    fi
  fi
  echo "Secret ${secret} is from another CA or expires soon. Issuing a new certificate."
elif [[ "${code}" != "404" ]]; then
  echo "Reading Secret ${secret} returned HTTP ${code}" >&2
  exit 1
fi

# The CA key is not left in the ConfigMap TAK pods mount. A fresh install
# still has it on local disk. Secret takserver-ca-key, or an older
# ConfigMap, covers the upgrade and a Job retry.
if [[ -s "${ca_key_file}" ]]; then
  cp "${ca_key_file}" "${work}/ca.key"
else
  api_curl --cacert "${ca}" -H "Authorization: Bearer ${token}" \
    "${base}/secrets/takserver-ca-key" > "${work}/cakey.json" || true
  key_b64="$(field ca-do-not-share.key "${work}/cakey.json" || true)"
  if [[ -z "${key_b64}" ]]; then
    key_b64="$(field ca-do-not-share.key "${work}/cm.json" || true)"
  fi
  printf '%s' "${key_b64}" | base64 -d > "${work}/ca.key"
fi
if [[ ! -s "${work}/ca.key" ]]; then
  echo "Could not read the CA key for the health client certificate" >&2
  exit 1
fi

cat > "${work}/ext.cnf" <<CNF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
CNF

openssl req -new -newkey rsa:2048 -nodes \
  -keyout "${work}/client.key" -out "${work}/client.csr" \
  -subj "/CN=${cn}/O=${ORGANIZATION:-TAK}/OU=${ORGANIZATIONAL_UNIT:-UDS}"
openssl x509 -req -in "${work}/client.csr" -days 730 -sha256 \
  -CA "${work}/ca.pem" -CAkey "${work}/ca.key" -passin "pass:${pass}" \
  -set_serial "0x$(openssl rand -hex 16)" \
  -extfile "${work}/ext.cnf" -out "${work}/client.pem"
openssl verify -CAfile "${work}/ca.pem" "${work}/client.pem"

printf '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"%s","labels":{"app":"tak-health"}},"type":"Opaque","data":{"ca.pem":"%s","client.pem":"%s","client.key":"%s"}}' \
  "${secret}" \
  "$(base64 -w 0 "${work}/ca.pem")" \
  "$(base64 -w 0 "${work}/client.pem")" \
  "$(base64 -w 0 "${work}/client.key")" > "${work}/secret-body.json"
code="$(api_curl -o "${work}/resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/json" \
  -X "${method}" --data-binary @"${work}/secret-body.json" "${url}")"
if [[ "${code}" != "200" ]] && [[ "${code}" != "201" ]]; then
  echo "Secret ${secret} ${method} returned HTTP ${code}" >&2
  exit 1
fi
echo "Issued client certificate CN=${cn} into Secret ${secret}"
