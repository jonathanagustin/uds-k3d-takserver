#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Copy cert-migration into Secret takserver-certs and drop private keys from
# the ConfigMap. The upstream chart can only mount a ConfigMap. The admission
# module points that volume at the Secret, so the pods never see the ConfigMap.
# ca-do-not-share.key stays in Secret takserver-ca-key. move-ca-key.sh runs
# first and removes it from the ConfigMap.
#
# Set SPLIT_KEY_SOURCE_ONLY=1 to load the functions without calling the API.

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

# Truststores and the legacy CA pkcs12 hold certificates only.
is_private_material() {
  case "$1" in
    *.key) return 0 ;;
    *truststore*) return 1 ;;
    *-legacy.p12) return 1 ;;
    *.jks | *.p12) return 0 ;;
    *) return 1 ;;
  esac
}

# Scanner state. data_fields reads one JSON document from stdin and prints
# name<TAB>value lines for the named object (binaryData or data). Values are
# base64, so they contain no quotes. A missing object prints nothing.
JSON=""
json_i=0
json_n=0
JSON_C=""
JSON_STR=""

json_peek() {
  if (( json_i >= json_n )); then
    JSON_C=""
    return 0
  fi
  JSON_C="${JSON:json_i:1}"
}

json_skip_ws() {
  local c
  while (( json_i < json_n )); do
    c="${JSON:json_i:1}"
    case "${c}" in
      [[:space:]]) json_i=$((json_i + 1)) ;;
      *) return 0 ;;
    esac
  done
}

json_parse_string() {
  local rest
  json_i=$((json_i + 1))
  rest="${JSON:json_i}"
  case "${rest}" in
    *\\*)
      JSON_STR=""
      while (( json_i < json_n )); do
        JSON_C="${JSON:json_i:1}"
        if [[ "${JSON_C}" == "\\" ]]; then
          JSON_STR="${JSON_STR}${JSON:json_i+1:1}"
          json_i=$((json_i + 2))
          continue
        fi
        if [[ "${JSON_C}" == '"' ]]; then
          json_i=$((json_i + 1))
          return 0
        fi
        JSON_STR="${JSON_STR}${JSON_C}"
        json_i=$((json_i + 1))
      done
      return 1
      ;;
    *\"*)
      JSON_STR="${rest%%\"*}"
      json_i=$((json_i + ${#JSON_STR} + 1))
      ;;
    *) return 1 ;;
  esac
}

json_skip_value() {
  local depth=0 in_str=0
  json_skip_ws
  json_peek
  case "${JSON_C}" in
    '"')
      json_parse_string || return 1
      ;;
    '{' | '[')
      while (( json_i < json_n )); do
        JSON_C="${JSON:json_i:1}"
        if [[ "${in_str}" -eq 1 ]]; then
          if [[ "${JSON_C}" == "\\" ]]; then
            json_i=$((json_i + 2))
            continue
          fi
          if [[ "${JSON_C}" == '"' ]]; then
            in_str=0
          fi
          json_i=$((json_i + 1))
          continue
        fi
        case "${JSON_C}" in
          '"') in_str=1 ;;
          '{' | '[') depth=$((depth + 1)) ;;
          '}' | ']')
            depth=$((depth - 1))
            json_i=$((json_i + 1))
            if (( depth == 0 )); then
              return 0
            fi
            continue
            ;;
          *) ;;
        esac
        json_i=$((json_i + 1))
      done
      ;;
    *)
      while (( json_i < json_n )); do
        JSON_C="${JSON:json_i:1}"
        case "${JSON_C}" in
          ',' | '}' | ']' | [[:space:]]) return 0 ;;
          *) json_i=$((json_i + 1)) ;;
        esac
      done
      ;;
  esac
}

data_fields() {
  local section="$1" key
  JSON="$(cat)"
  json_n=${#JSON}
  json_i=0
  json_skip_ws
  json_peek
  [[ "${JSON_C}" == "{" ]] || return 0
  json_i=$((json_i + 1))
  while (( json_i < json_n )); do
    json_skip_ws
    json_peek
    case "${JSON_C}" in
      '}') return 0 ;;
      ',')
        json_i=$((json_i + 1))
        continue
        ;;
      '"') ;;
      "") return 1 ;;
      *) return 1 ;;
    esac
    json_parse_string || return 1
    key="${JSON_STR}"
    json_skip_ws
    json_peek
    [[ "${JSON_C}" == ":" ]] || return 1
    json_i=$((json_i + 1))
    json_skip_ws
    json_peek
    if [[ "${key}" == "${section}" && "${JSON_C}" == "{" ]]; then
      json_i=$((json_i + 1))
      while (( json_i < json_n )); do
        json_skip_ws
        json_peek
        case "${JSON_C}" in
          '}') return 0 ;;
          ',')
            json_i=$((json_i + 1))
            continue
            ;;
          '"') ;;
          *) return 1 ;;
        esac
        json_parse_string || return 1
        key="${JSON_STR}"
        json_skip_ws
        json_peek
        [[ "${JSON_C}" == ":" ]] || return 1
        json_i=$((json_i + 1))
        json_skip_ws
        json_peek
        if [[ "${JSON_C}" == '"' ]]; then
          json_parse_string || return 1
          printf '%s\t%s\n' "${key}" "${JSON_STR}"
        else
          json_skip_value || return 1
        fi
      done
      return 1
    fi
    json_skip_value || return 1
  done
  return 1
}

if [[ "${SPLIT_KEY_SOURCE_ONLY:-}" == "1" ]]; then
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

secret_code="$(api_curl -o "${work}/secret.json" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" "${api}/secrets/takserver-certs")"
if [[ "${secret_code}" != "200" ]]; then
  : > "${work}/secret.json"
fi

declare -A merged=()
load_fields() {
  local file="$1" section="$2" name value
  [[ -s "${file}" ]] || return 0
  if ! data_fields "${section}" < "${file}" > "${work}/fields.txt"; then
    echo "could not read ${section} from ${file}" >&2
    exit 1
  fi
  while IFS=$'\t' read -r name value; do
    [[ -n "${name}" ]] || continue
    if [[ "${name}" == "ca-do-not-share.key" ]]; then
      continue
    fi
    merged["${name}"]="${value}"
  done < "${work}/fields.txt"
}
# Secret first, then the ConfigMap, so a key still sitting in the ConfigMap
# wins. The CA key is never copied into the Secret the pods mount.
load_fields "${work}/secret.json" data
load_fields "${work}/cm.json" binaryData

if [[ "${#merged[@]}" -eq 0 ]]; then
  echo "ConfigMap cert-migration has no certificate files to publish" >&2
  exit 1
fi

{
  printf '%s\n' '{'
  printf '%s\n' '  "apiVersion": "v1",'
  printf '%s\n' '  "kind": "Secret",'
  printf '%s\n' '  "metadata": {"name": "takserver-certs"},'
  printf '%s\n' '  "type": "Opaque",'
  printf '%s\n' '  "data": {'
  first=1
  for name in "${!merged[@]}"; do
    case "${name}" in
      *\"* | *\\* | *[[:space:]]*)
        echo "refusing certificate file name ${name}" >&2
        exit 1
        ;;
      *) ;;
    esac
    if [[ "${first}" -eq 0 ]]; then
      printf '%s\n' ','
    fi
    printf '    "%s": "%s"' "${name}" "${merged[${name}]}"
    first=0
  done
  printf '\n%s\n' '  }'
  printf '%s\n' '}'
} > "${work}/secret-body.json"

code="$(api_curl -o "${work}/secret-resp" -w '%{http_code}' --cacert "${ca}" \
  -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
  -X POST --data-binary @"${work}/secret-body.json" "${api}/secrets")"
if [[ "${code}" == "409" ]]; then
  code="$(api_curl -o "${work}/secret-resp" -w '%{http_code}' --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
    -X PUT --data-binary @"${work}/secret-body.json" "${api}/secrets/takserver-certs")"
fi
if [[ "${code}" != "200" && "${code}" != "201" ]]; then
  echo "Secret takserver-certs returned HTTP ${code}" >&2
  exit 1
fi

patch_names=()
if ! data_fields binaryData < "${work}/cm.json" > "${work}/cm-fields.txt"; then
  echo "could not read ConfigMap cert-migration" >&2
  exit 1
fi
while IFS=$'\t' read -r name _; do
  [[ -n "${name}" ]] || continue
  if is_private_material "${name}"; then
    patch_names+=("${name}")
  fi
done < "${work}/cm-fields.txt"

if [[ "${#patch_names[@]}" -gt 0 ]]; then
  {
    printf '%s' '{"binaryData":{'
    first=1
    for name in "${patch_names[@]}"; do
      if [[ "${first}" -eq 0 ]]; then
        printf '%s' ','
      fi
      printf '"%s":null' "${name}"
      first=0
    done
    printf '%s\n' '}}'
  } > "${work}/patch.json"
  code="$(api_curl -o "${work}/cm-resp" -w '%{http_code}' --cacert "${ca}" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/merge-patch+json" \
    -X PATCH --data-binary @"${work}/patch.json" \
    "${api}/configmaps/cert-migration")"
  if [[ "${code}" != "200" ]]; then
    echo "ConfigMap cert-migration update returned HTTP ${code}" >&2
    exit 1
  fi
fi

api_curl -f --cacert "${ca}" -H "Authorization: Bearer ${token}" \
  "${api}/configmaps/cert-migration" > "${work}/after.json"
if ! data_fields binaryData < "${work}/after.json" > "${work}/after-fields.txt"; then
  echo "could not read ConfigMap cert-migration after the update" >&2
  exit 1
fi
while IFS=$'\t' read -r name _; do
  if is_private_material "${name}"; then
    echo "private file ${name} is still in ConfigMap cert-migration" >&2
    exit 1
  fi
done < "${work}/after-fields.txt"
echo "Secret takserver-certs holds the certificate files. ConfigMap cert-migration has no private keys."
