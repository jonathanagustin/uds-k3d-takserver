#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Join the per-architecture TAK image tags into one multi-arch index.
# The container workflow builds each architecture on its own native runner
# and pushes <tag>-<arch>. This writes <tag> as an index of those manifests,
# which is the tag zarf.yaml and the chart values reference. Zarf then pulls
# the entry that matches the package architecture.
#
#   IMAGE_REPO  default: ghcr.io/jonathanagustin/uds-k3d-takserver
#   IMAGE_TAG   default: 5.7-RELEASE-14
#   ARCHES      default: "amd64 arm64". Every one must be present.
set -euo pipefail

repo="${IMAGE_REPO:-ghcr.io/jonathanagustin/uds-k3d-takserver}"
tag="${IMAGE_TAG:-5.7-RELEASE-14}"
read -r -a arches <<< "${ARCHES:-amd64 arm64}"

names=(
  takserver-api
  takserver-messaging
  takserver-config
  takserver-plugins
  takserver-database-setup
  takserver-ignite
)

# A partial index would replace a good multi-arch tag with fewer platforms,
# so check every source before writing any target.
for name in "${names[@]}"; do
  for arch in "${arches[@]}"; do
    if ! docker buildx imagetools inspect "${repo}/${name}:${tag}-${arch}" >/dev/null; then
      echo "${repo}/${name}:${tag}-${arch} is missing. Not writing ${tag}." >&2
      exit 1
    fi
  done
done

for name in "${names[@]}"; do
  sources=()
  for arch in "${arches[@]}"; do
    sources+=("${repo}/${name}:${tag}-${arch}")
  done
  echo "Writing ${repo}/${name}:${tag} from ${sources[*]}"
  docker buildx imagetools create --tag "${repo}/${name}:${tag}" "${sources[@]}"
done

summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
{
  echo "### Multi-arch TAK images"
  echo
  echo '```text'
} >> "${summary}"
for name in "${names[@]}"; do
  docker buildx imagetools inspect "${repo}/${name}:${tag}" | tee -a "${summary}"
done
echo '```' >> "${summary}"
