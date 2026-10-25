#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Move ca-do-not-share.key out of ConfigMap cert-migration into Secret
# takserver-ca-key. The publish script in the config image does this on a
# fresh install. This still runs so an upgrade, or an older image that put
# the key in the ConfigMap, does not leave it where TAK pods mount it.
# Set MOVE_CA_KEY_SOURCE_ONLY=1 to load strip_ca_key_json without calling the API.

strip_ca_key_json() {
  sed -E \
    -e 's/,"ca-do-not-share\.key"[[:space:]]*:[[:space:]]*"[^"]*"//g' \
    -e 's/"ca-do-not-share\.key"[[:space:]]*:[[:space:]]*"[^"]*",//g'
}

# Retry a refused or reset handshake. Five tries, one second apart.
# --retry-all-errors covers a TLS reset (curl 35 or 56). --retry-connrefused
# covers ECONNREFUSED. An HTTP status is not an error unless the caller
# passes -f, so 409 still returns to the caller. The config image is UBI9,
# whose curl is new enough for --retry-all-errors.
api_curl() {
  curl \
    --silent \
    --show-error \
    --retry 5 \
    --retry-delay 1 \
    --retry-all-errors \
    --retry-connrefused \
    --connect-timeout 5 \
    "$@"
}

if [[ "${MOVE_CA_KEY_SOURCE_ONLY:-}" == "1" ]]; then
  return 0
fi

set -euo pipefail

ns="$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)"
token="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
ca="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
api="https://kubernetes.default.svc/api/v1/namespaces/${ns}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

api_curl -f --cacert "${ca}" -H "Authorization: Bearer ${token}" \
  "${api}/configmaps/cert-migration" > "${work}/cm.json"

key_b64="$(grep -o '"ca-do-not-share.key"[[:space:]]*:[[:space:]]*"[^"]*"' "${work}/cm.json" | head -n 1 | sed 's/.*:[[:space:]]*"\(.*\)"/\1/' || true)"
if [[ -z "${key_b64}" ]]; then
  code="$(api_curl -o /dev/null -w '%{http_code}' --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" "${api}/secrets/takserver-ca-key")"
  if [[ "${code}" == "200" ]]; then
    echo "CA key is in Secret takserver-ca-key and not in ConfigMap cert-migration"
    exit 0
  fi
  echo "ConfigMap cert-migration has no CA key and Secret takserver-ca-key is missing" >&2
  exit 1
fi

secret_body="$(printf '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"takserver-ca-key"},"type":"Opaque","data":{"ca-do-not-share.key":"%s"}}' "${key_b64}")"
code="$(api_curl -o "${work}/secret-resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
  -X POST --data-binary "${secret_body}" "${api}/secrets")"
if [[ "${code}" == "409" ]]; then
  code="$(api_curl -o "${work}/secret-resp" -w '%{http_code}' --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
    -X PUT --data-binary "${secret_body}" "${api}/secrets/takserver-ca-key")"
fi
if [[ "${code}" != "200" && "${code}" != "201" ]]; then
  echo "Secret takserver-ca-key returned HTTP ${code}" >&2
  exit 1
fi

# A JSON merge patch deletes the key. Rewriting the whole ConfigMap fails
# this check: the apiserver keeps the field name under managedFields as
# f:ca-do-not-share.key, and a line-oriented edit misses a pretty-printed
# last field. Search for the quoted key so that managedFields entry does
# not look like the binaryData field.
code="$(api_curl -o "${work}/cm-resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/merge-patch+json" \
  -X PATCH \
  --data '{"binaryData":{"ca-do-not-share.key":null}}' \
  "${api}/configmaps/cert-migration")"
if [[ "${code}" != "200" ]]; then
  echo "ConfigMap cert-migration update returned HTTP ${code}" >&2
  exit 1
fi
api_curl -f --cacert "${ca}" -H "Authorization: Bearer ${token}" \
  "${api}/configmaps/cert-migration" > "${work}/after.json"
if grep -q '"ca-do-not-share.key"' "${work}/after.json"; then
  echo "Could not remove the CA key from ConfigMap cert-migration" >&2
  exit 1
fi
echo "Moved the CA key from ConfigMap cert-migration to Secret takserver-ca-key"
