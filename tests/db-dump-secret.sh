#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Prints the SQL held in a dump Secret (tak-db-dump or cloudtak-db-dump).
#   tests/db-dump-secret.sh <namespace> <secret> > dump.sql
# Key dump.sql.gz (gzipped, written since the dumps were compressed) wins.
# A Secret from before that has only key dump.sql, which is read as is, so
# an old backup restores without a manual step. KUBECTL overrides the client.
set -euo pipefail

dump_kubectl() {
  if [[ -n "${KUBECTL:-}" ]]; then
    "${KUBECTL}" "$@"
  elif [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

secret_dump_sql() {
  local ns="$1"
  local name="$2"
  local data
  data="$(dump_kubectl get secret "${name}" -n "${ns}" -o jsonpath='{.data.dump\.sql\.gz}')"
  if [[ -n "${data}" ]]; then
    base64 -d <<< "${data}" | gunzip -c
    return 0
  fi
  data="$(dump_kubectl get secret "${name}" -n "${ns}" -o jsonpath='{.data.dump\.sql}')"
  if [[ -n "${data}" ]]; then
    echo "${ns}/${name} has only key dump.sql (written before the dumps were gzipped)" >&2
    base64 -d <<< "${data}"
    return 0
  fi
  echo "${ns}/${name} has neither dump.sql.gz nor dump.sql" >&2
  return 1
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 <namespace> <secret>" >&2
    exit 2
  fi
  secret_dump_sql "$1" "$2"
fi
