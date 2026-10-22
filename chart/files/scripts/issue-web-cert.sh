#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Issue the server certificate for the 8447 web connector and add it to
# ConfigMap cert-migration as takserver-web.jks. The tenant gateway connects
# to 8447 over TLS and verifies this certificate against the deploy-time CA,
# so its SANs are the in-cluster names of Service WEB_SERVICE.
# Runs in the cert-init Job after publish-cert-configmap.sh. On an upgrade
# the ConfigMap already exists, so the CA comes out of the ConfigMap.
set -euo pipefail

service="${WEB_SERVICE:?WEB_SERVICE is not set}"
key_name="${WEB_KEYSTORE:-takserver-web.jks}"
pass="${CAPASS:-atakatak}"

ns="$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)"
token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
api="https://kubernetes.default.svc/api/v1/namespaces/${ns}/configmaps/cert-migration"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

curl -sS -f --cacert "${ca}" -H "Authorization: Bearer ${token}" "${api}" > "${work}/cm.json"

# Pull one binaryData key out of the ConfigMap JSON. Base64 has no quotes.
field() {
  grep -o "\"$1\": *\"[^\"]*\"" "${work}/cm.json" | head -n 1 | sed 's/.*: *"\(.*\)"/\1/'
}

if [[ -n "$(field "${key_name}")" ]]; then
  echo "ConfigMap cert-migration already has ${key_name}"
  exit 0
fi

field ca.pem | base64 -d > "${work}/ca.pem"
field ca-do-not-share.key | base64 -d > "${work}/ca.key"
if [[ ! -s "${work}/ca.pem" ]] || [[ ! -s "${work}/ca.key" ]]; then
  echo "ConfigMap cert-migration has no ca.pem or ca-do-not-share.key" >&2
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
code="$(curl -sS -o "${work}/resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/merge-patch+json" \
  -X PATCH --data-binary @"${work}/patch.json" "${api}")"
if [[ "${code}" != "200" ]]; then
  echo "ConfigMap cert-migration patch returned HTTP ${code}" >&2
  cat "${work}/resp" >&2 || true
  exit 1
fi
echo "Added ${key_name} for ${fqdn} to ConfigMap cert-migration"
