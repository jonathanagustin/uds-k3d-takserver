#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Create ConfigMap cert-migration from TAK's generateClusterCerts.sh.
# The scripts live in this image at /opt/tak/certs (TAK Server 5.7-RELEASE-14).
# A ConfigMap that already exists is left alone so an operator can supply certs.
set -euo pipefail

ns="$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)"
token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
api="https://kubernetes.default.svc/api/v1/namespaces/${ns}/configmaps"

# The Ignite server does not have TAK's classes. The chart mounts this jar,
# which the upstream build produces with :takserver-cluster:igniteExtensions.
# Without it the server halts on "Failed to find class ... IgniteCacheSql-
# HelperFunctions" and every API client loses its Ignite connection.
publish_ignite_extensions() {
  local jar="/ignite-extensions.jar"
  if [ ! -s "${jar}" ]; then
    echo "${jar} is not in this image" >&2
    exit 1
  fi
  {
    printf '%s\n' '{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "ignite-extensions"}, "binaryData": {'
    printf '    "ignite-extensions.jar": "%s"\n' "$(base64 -w 0 "${jar}")"
    printf '%s\n' '}}'
  } > /tmp/ignite-extensions.json
  local code
  code="$(curl -sS -o /tmp/ignite-extensions-response -w '%{http_code}' --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
    -X POST --data-binary @/tmp/ignite-extensions.json "${api}")"
  if [ "${code}" = "409" ]; then
    code="$(curl -sS -o /tmp/ignite-extensions-response -w '%{http_code}' --cacert "${ca}" \
      -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
      -X PUT --data-binary @/tmp/ignite-extensions.json "${api}/ignite-extensions")"
  fi
  if [ "${code}" != "200" ] && [ "${code}" != "201" ]; then
    echo "ConfigMap ignite-extensions returned HTTP ${code}" >&2
    cat /tmp/ignite-extensions-response >&2 || true
    exit 1
  fi
  echo "Published ConfigMap ignite-extensions"
}
publish_ignite_extensions

existing="$(curl -sS -o /dev/null -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  "${api}/cert-migration")"
if [ "${existing}" = "200" ]; then
  echo "ConfigMap cert-migration already exists"
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is not installed in this image" >&2
  exit 1
fi

export CA_NAME="${CA_NAME:-uds-tak-ca}"
export STATE="${STATE:-VA}"
export CITY="${CITY:-Arlington}"
export ORGANIZATION="${ORGANIZATION:-TAK}"
export ORGANIZATIONAL_UNIT="${ORGANIZATIONAL_UNIT:-UDS}"
# cert-metadata.sh defaults CAPASS and PASS to atakatak, the password in CoreConfig.xml.
export CAPASS="${CAPASS:-atakatak}"
export PASS="${PASS:-${CAPASS}}"
export HOME=/tmp

cd /opt/tak/certs
./generateClusterCerts.sh

for required in takserver.jks admin.pem admin.key user.pem ca.pem ca-do-not-share.key truststore-root.jks fed-truststore.jks; do
  if [ ! -s "files/${required}" ]; then
    echo "generateClusterCerts.sh did not write files/${required}" >&2
    exit 1
  fi
done

# makeCert.sh only writes a signing keystore for a CA certificate, and that
# path asks an interactive question. Build the keystore the enrollment
# endpoint reads from the root CA key the script already wrote.
(
  cd files
  openssl pkcs12 -export \
    -in ca.pem \
    -inkey ca-do-not-share.key \
    -out ca-signing.p12 \
    -name ca \
    -passin "pass:${CAPASS}" \
    -passout "pass:${CAPASS}"
  keytool -importkeystore -noprompt \
    -deststorepass "${CAPASS}" \
    -destkeypass "${CAPASS}" \
    -destkeystore ca-signing.jks \
    -srckeystore ca-signing.p12 \
    -srcstoretype PKCS12 \
    -srcstorepass "${CAPASS}" \
    -alias ca
  rm -f ca-signing.p12
)
if [ ! -s files/ca-signing.jks ]; then
  echo "ca-signing.jks was not written" >&2
  exit 1
fi

{
  printf '%s\n' '{'
  printf '%s\n' '  "apiVersion": "v1",'
  printf '%s\n' '  "kind": "ConfigMap",'
  printf '%s\n' '  "metadata": {"name": "cert-migration"},'
  printf '%s\n' '  "binaryData": {'
  first=1
  for file in files/*; do
    [ -f "${file}" ] || continue
    name="$(basename "${file}")"
    b64="$(base64 -w 0 "${file}")"
    if [ "${first}" -eq 0 ]; then
      printf '%s\n' ','
    fi
    printf '    "%s": "%s"' "${name}" "${b64}"
    first=0
  done
  printf '\n%s\n' '  }'
  printf '%s\n' '}'
} > /tmp/cert-migration.json

resp="/tmp/cert-migration-response"
code="$(curl -sS -o "${resp}" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/json" \
  -X POST \
  --data-binary @/tmp/cert-migration.json \
  "${api}")"
if [ "${code}" != "201" ] && [ "${code}" != "200" ] && [ "${code}" != "409" ]; then
  echo "ConfigMap create returned HTTP ${code}" >&2
  cat "${resp}" >&2 || true
  exit 1
fi
echo "Created ConfigMap cert-migration"
