#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Copy admin.pem and admin.key out of ConfigMap cert-migration.
# The deploy-time Job writes that ConfigMap. The gateway tests present the admin cert.
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
  kctl get configmap cert-migration -n takserver -o "go-template={{index .binaryData \"${name}\"}}" | base64 -d > "${out}"
  if [[ ! -s "${out}" ]]; then
    echo "ConfigMap cert-migration has no ${name}" >&2
    exit 1
  fi
}

decode admin.pem "${dest}/admin.pem"
decode admin.key "${dest}/admin.key"
chmod 600 "${dest}/admin.key" "${dest}/admin.pem"
printf '%s\n' "${dest}"
