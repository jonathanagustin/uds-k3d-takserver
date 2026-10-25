#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Issue the server certificate for the 8447 web connector and add it to
# ConfigMap cert-migration as takserver-web.jks. The tenant gateway connects
# to 8447 over TLS and verifies this certificate against the deploy-time CA,
# so its SANs are the in-cluster names of Service WEB_SERVICE.
# Runs in the cert-init Job after publish-cert-configmap.sh. On an upgrade
# the ConfigMap already exists, so the CA comes out of the ConfigMap.

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

service="${WEB_SERVICE:?WEB_SERVICE is not set}"
key_name="${WEB_KEYSTORE:-takserver-web.jks}"
if [[ -z "${CAPASS:-}" ]]; then
  echo "CAPASS is not set. Secret takserver-keystore did not reach this Job." >&2
  exit 1
fi
pass="${CAPASS}"

ns="$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)"
token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
api="https://kubernetes.default.svc/api/v1/namespaces/${ns}/configmaps/cert-migration"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

api_curl -f --cacert "${ca}" -H "Authorization: Bearer ${token}" "${api}" > "${work}/cm.json"

# Pull one binaryData key out of the ConfigMap JSON. Base64 has no quotes.
field() {
  grep -o "\"$1\": *\"[^\"]*\"" "${work}/cm.json" | head -n 1 | sed 's/.*: *"\(.*\)"/\1/'
}

if [[ -n "$(field "${key_name}")" ]]; then
  echo "ConfigMap cert-migration already has ${key_name}"
  exit 0
fi
# split-key-material.sh moves the keystore into the Secret. A later upgrade
# must not issue a second certificate just because the ConfigMap no longer
# has it.
secret_code="$(api_curl -o "${work}/certs.json" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  "https://kubernetes.default.svc/api/v1/namespaces/${ns}/secrets/takserver-certs")"
if [[ "${secret_code}" == "200" ]] && grep -F -q "\"${key_name}\"" "${work}/certs.json"; then
  echo "Secret takserver-certs already has ${key_name}"
  exit 0
fi

field ca.pem | base64 -d > "${work}/ca.pem"
# The CA key is not left in the ConfigMap TAK pods mount. A fresh install
# still has it on local disk. An older ConfigMap, or Secret takserver-ca-key,
# covers the upgrade and a Job retry.
if [[ -s /opt/tak/certs/files/ca-do-not-share.key ]]; then
  cp /opt/tak/certs/files/ca-do-not-share.key "${work}/ca.key"
else
  key_b64="$(api_curl --cacert "${ca}" -H "Authorization: Bearer ${token}" \
    "https://kubernetes.default.svc/api/v1/namespaces/${ns}/secrets/takserver-ca-key" \
    | grep -o '"ca-do-not-share.key": *"[^"]*"' | head -n 1 | sed 's/.*: *"\(.*\)"/\1/' || true)"
  if [[ -n "${key_b64}" ]]; then
    printf '%s' "${key_b64}" | base64 -d > "${work}/ca.key"
  else
    field ca-do-not-share.key | base64 -d > "${work}/ca.key"
  fi
fi
if [[ ! -s "${work}/ca.pem" ]] || [[ ! -s "${work}/ca.key" ]]; then
  echo "Could not read ca.pem and the CA key for the web certificate" >&2
  exit 1
fi

fqdn="${service}.${ns}.svc.cluster.local"
cat > "${work}/ext.cnf" <<CNF
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:${fqdn}, DNS:${service}.${ns}.svc, DNS:${service}.${ns}, DNS:${service}
CNF

openssl req -new -newkey rsa:2048 -nodes \
  -keyout "${work}/web.key" -out "${work}/web.csr" \
  -subj "/CN=${fqdn}/O=${ORGANIZATION:-TAK}/OU=${ORGANIZATIONAL_UNIT:-UDS}"
openssl x509 -req -in "${work}/web.csr" -days 730 -sha256 \
  -CA "${work}/ca.pem" -CAkey "${work}/ca.key" -passin "pass:${pass}" \
  -set_serial "0x$(openssl rand -hex 16)" \
  -extfile "${work}/ext.cnf" -out "${work}/web.pem"
openssl verify -CAfile "${work}/ca.pem" "${work}/web.pem"

openssl pkcs12 -export \
  -in "${work}/web.pem" -inkey "${work}/web.key" -certfile "${work}/ca.pem" \
  -name takserver-web -out "${work}/web.p12" -passout "pass:${pass}"
keytool -importkeystore -noprompt \
  -srckeystore "${work}/web.p12" -srcstoretype PKCS12 -srcstorepass "${pass}" \
  -destkeystore "${work}/web.jks" -deststoretype PKCS12 \
  -deststorepass "${pass}" -destkeypass "${pass}" -alias takserver-web

printf '{"binaryData": {"%s": "%s"}}' "${key_name}" "$(base64 -w 0 "${work}/web.jks")" > "${work}/patch.json"
code="$(api_curl -o "${work}/resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/merge-patch+json" \
  -X PATCH --data-binary @"${work}/patch.json" "${api}")"
if [[ "${code}" != "200" ]]; then
  echo "ConfigMap cert-migration patch returned HTTP ${code}" >&2
  cat "${work}/resp" >&2 || true
  exit 1
fi
echo "Added ${key_name} for ${fqdn} to ConfigMap cert-migration"
