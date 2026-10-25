#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Start a PostgreSQL 15 PostGIS database, then start IMAGE on the same
# directory and check the row, the server major, and the PostGIS version.
#
#   smoke.sh ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:18-3.6-<key>-amd64
#
# OLD_IMAGE defaults to the 15-3.4 tag this repository still publishes.
set -euo pipefail

image="${1:?usage: smoke.sh IMAGE}"
old_image="${OLD_IMAGE:-ghcr.io/jonathanagustin/uds-k3d-takserver/postgis:15-3.4}"
if ! docker image inspect "${old_image}" >/dev/null 2>&1; then
  docker pull "${old_image}"
fi
if ! docker image inspect "${image}" >/dev/null 2>&1; then
  docker pull "${image}"
fi

run_case() {
  local name="$1" uid="$2" mount="$3" pgdata="$4" user="$5" db="$6"
  local volume="postgis-smoke-${name}-$$"
  docker volume rm "${volume}" >/dev/null 2>&1 || true
  docker volume create "${volume}" >/dev/null
  docker run --rm -v "${volume}:${mount}" alpine:3.20 chown "${uid}:${uid}" "${mount}"
  docker run -d --name "${volume}" --user "${uid}:${uid}" \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_USER="${user}" \
    -e POSTGRES_DB="${db}" \
    -e PGDATA="${pgdata}" \
    -v "${volume}:${mount}" \
    "${old_image}" >/dev/null
  local i
  for i in $(seq 1 30); do
    if docker exec "${volume}" pg_isready -h 127.0.0.1 -U "${user}" -d "${db}" >/dev/null 2>&1; then
      break
    fi
    if [[ "${i}" -eq 30 ]]; then
      docker logs "${volume}" >&2 || true
      echo "${name}: PostgreSQL 15 did not become ready" >&2
      exit 1
    fi
    sleep 2
  done
  docker exec "${volume}" psql -U "${user}" -d "${db}" -v ON_ERROR_STOP=1 \
    -c "CREATE SCHEMA upgrade_test; CREATE TABLE upgrade_test.retained_state (marker text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now()); INSERT INTO upgrade_test.retained_state (marker) VALUES ('keep-me');"
  local before
  before="$(docker exec "${volume}" psql -U "${user}" -d "${db}" -At -c "SELECT marker || '|' || created_at::text FROM upgrade_test.retained_state;")"
  docker stop "${volume}" >/dev/null
  docker rm "${volume}" >/dev/null
  docker run -d --name "${volume}" --user "${uid}:${uid}" \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_USER="${user}" \
    -e POSTGRES_DB="${db}" \
    -e PGDATA="${pgdata}" \
    -v "${volume}:${mount}" \
    "${image}" >/dev/null
  for i in $(seq 1 60); do
    if docker exec "${volume}" pg_isready -h 127.0.0.1 -U "${user}" -d "${db}" >/dev/null 2>&1; then
      break
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "${volume}")" != "true" || "${i}" -eq 60 ]]; then
      docker logs "${volume}" >&2 || true
      echo "${name}: PostgreSQL 18 did not become ready" >&2
      exit 1
    fi
    sleep 2
  done
  local after version postgis
  after="$(docker exec "${volume}" psql -U "${user}" -d "${db}" -At -c "SELECT marker || '|' || created_at::text FROM upgrade_test.retained_state;")"
  version="$(docker exec "${volume}" psql -U "${user}" -d "${db}" -At -c "SHOW server_version_num;")"
  postgis="$(docker exec "${volume}" psql -U "${user}" -d "${db}" -At -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis';")"
  docker logs "${volume}" >&2 || true
  docker rm -f "${volume}" >/dev/null
  docker volume rm "${volume}" >/dev/null
  if [[ "${after}" != "${before}" || "${version}" -lt 180000 || "${postgis}" != 3.6.* ]]; then
    echo "${name}: row ${after} (was ${before}), server ${version}, postgis ${postgis}" >&2
    exit 1
  fi
  echo "PASS ${name}: PostgreSQL ${version}, PostGIS ${postgis}, row kept"
}

run_case bitnami 1001 /bitnami/postgresql /bitnami/postgresql/data postgres cot
run_case cloudtak 999 /var/lib/postgresql/data /var/lib/postgresql/data/pgdata cloudtak cloudtak

# A new directory has to init, not try to upgrade.
fresh="postgis-smoke-fresh-$$"
docker volume create "${fresh}" >/dev/null
docker run --rm -v "${fresh}:/bitnami/postgresql" alpine:3.20 chown 1001:1001 /bitnami/postgresql
docker run -d --name "${fresh}" --user 1001:1001 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=cot -e PGDATA=/bitnami/postgresql/data \
  -v "${fresh}:/bitnami/postgresql" "${image}" >/dev/null
for i in $(seq 1 30); do
  if docker exec "${fresh}" pg_isready -h 127.0.0.1 -U postgres -d cot >/dev/null 2>&1; then
    break
  fi
  if [[ "${i}" -eq 30 ]]; then
    docker logs "${fresh}" >&2 || true
    echo "fresh init did not become ready" >&2
    exit 1
  fi
  sleep 2
done
fresh_postgis="$(docker exec "${fresh}" psql -U postgres -d cot -At -c "SELECT extversion FROM pg_extension WHERE extname = 'postgis';")"
docker rm -f "${fresh}" >/dev/null
docker volume rm "${fresh}" >/dev/null
if [[ "${fresh_postgis}" != 3.6.* ]]; then
  echo "fresh init PostGIS is ${fresh_postgis}" >&2
  exit 1
fi
echo "PASS fresh init: PostGIS ${fresh_postgis}"
