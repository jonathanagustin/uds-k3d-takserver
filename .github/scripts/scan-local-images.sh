#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Scan images that are already in the local Docker daemon.
# build.sh loads each tag before it pushes, so this must not pull them again.
# The vulnerability database is updated once, then the six scans run in turn.
set -euo pipefail

repo="${IMAGE_REPO:?}"
tag="${IMAGE_TAG:?}"
grype_image="${GRYPE_IMAGE:?}"
db_dir="${GRYPE_DB_DIR:-${RUNNER_TEMP:-/tmp}/grype-db}"
log_dir="${RUNNER_TEMP:-/tmp}/grype-logs"
# The image sets no HOME, so the default cache is /.cache/grype/db and a mount
# on /root/.cache/grype stays empty. Pin the cache for the update and each scan.
cache_mount="/grype-db"

names=(
  takserver-api
  takserver-messaging
  takserver-config
  takserver-plugins
  takserver-database-setup
  takserver-ignite
)

mkdir -p "${db_dir}" "${log_dir}"

for name in "${names[@]}"; do
  docker image inspect "${repo}/${name}:${tag}" >/dev/null
done

echo "Updating the Grype database"
docker run --rm \
  -v "${db_dir}:${cache_mount}" \
  -e GRYPE_DB_CACHE_DIR="${cache_mount}" \
  "${grype_image}" \
  db update

# Grype creates the schema directory mode 0700. Widen it so this user can
# copy a database for each scan.
if [ "$(id -u)" -eq 0 ]; then
  chmod -R a+rX "${db_dir}"
else
  sudo chmod -R a+rX "${db_dir}"
fi

# One shared database, scanned read-only. Copying it once per image filled the
# runner disk (ENOSPC on the sixth copy), so scan the images one after another.
fail=0
for name in "${names[@]}"; do
  image="${repo}/${name}:${tag}"
  echo "Grype ${image}"
  if docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${db_dir}:${cache_mount}" \
    -e GRYPE_DB_CACHE_DIR="${cache_mount}" \
    -e GRYPE_DB_AUTO_UPDATE=false \
    "${grype_image}" \
    "${image}" > "${log_dir}/${name}.log" 2>&1; then
    echo "Grype ${name} passed"
  else
    echo "Grype ${name} failed" >&2
    cat "${log_dir}/${name}.log" >&2
    fail=1
  fi
done

if [ "${fail}" -ne 0 ]; then
  exit 1
fi
