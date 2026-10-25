#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Copy admin.pem and admin.key for the gateway tests.
# Secret takserver-certs holds the key. An older install still has both
# files in ConfigMap cert-migration.
set -euo pipefail

dest="${1:-/tmp/tak-certs}"
mkdir -p "${dest}"

if [[ -s "${dest}/admin.pem" ]] && [[ -s "${dest}/admin.key" ]]; then
  printf '%s\n' "${dest}"
  exit 0
fi

kctl() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

decode() {
  local name="$1"
  local out="$2"
  local escaped b64=""
  escaped="${name//./\\.}"
  if kctl get secret takserver-certs -n takserver >/dev/null 2>&1; then
    b64="$(kctl get secret takserver-certs -n takserver -o "jsonpath={.data.${escaped}}")"
  fi
  if [[ -z "${b64}" ]]; then
    b64="$(kctl get configmap cert-migration -n takserver -o "jsonpath={.binaryData.${escaped}}")"
  fi
  if [[ -z "${b64}" ]]; then
    echo "takserver-certs and cert-migration have no ${name}" >&2
    exit 1
  fi
  printf '%s' "${b64}" | base64 -d > "${out}"
  if [[ ! -s "${out}" ]]; then
    echo "${name} decoded empty" >&2
    exit 1
  fi
}

decode admin.pem "${dest}/admin.pem"
decode admin.key "${dest}/admin.key"
chmod 600 "${dest}/admin.key" "${dest}/admin.pem"
printf '%s\n' "${dest}"
