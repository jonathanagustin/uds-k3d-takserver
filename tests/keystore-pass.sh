#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Print the keystore password from Secret takserver-keystore. Callers must
# not echo it. There is no atakatak fallback: a missing Secret is a failure.
set -euo pipefail

if [[ -n "${TAK_CLIENT_KEY_PASSPHRASE:-}" ]]; then
  printf '%s' "${TAK_CLIENT_KEY_PASSPHRASE}"
  exit 0
fi

k() {
  if command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  elif [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

b64="$(k get secret takserver-keystore -n takserver -o jsonpath='{.data.CAPASS}')"
if [[ -z "${b64}" ]]; then
  echo "Secret takserver/takserver-keystore has no CAPASS" >&2
  exit 1
fi
printf '%s' "${b64}" | base64 -d
