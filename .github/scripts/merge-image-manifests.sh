#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Join the per-architecture TAK image tags into one multi-arch index.
# The container workflow builds each architecture on its own native runner
# and pushes <tag>-<arch>. This writes <tag> as an index of those manifests.
# Zarf then pulls the entry that matches the package architecture.
#
# <tag> defaults to <version>-<key> from docker/build.sh --tag, which only
# ever holds images built from this commit's inputs. On main (or with
# WRITE_VERSION_TAG=true) the same images are also written as <version> and
# <version>-<arch>, the tags zarf.yaml and releases reference.
#
#   IMAGE_REPO         default: ghcr.io/jonathanagustin/uds-k3d-takserver
#   IMAGE_TAG          default: docker/build.sh --tag
#   ARCHES             default: "amd64 arm64". Every one must be present.
#   WRITE_VERSION_TAG  true also writes <version> outside main.
set -euo pipefail

repo="${IMAGE_REPO:-ghcr.io/jonathanagustin/uds-k3d-takserver}"
tag="${IMAGE_TAG:-$(./.github/container-and-chart/docker/build.sh --tag)}"
version="$(tr -d '[:space:]' < .github/container-and-chart/docker/version.txt)"
read -r -a arches <<< "${ARCHES:-amd64 arm64}"

names=(
  takserver-api
  takserver-messaging
  takserver-config
  takserver-plugins
  takserver-database-setup
  takserver-ignite
)

write_version_tag() {
  [[ "${tag}" != "${version}" ]] \
    && { [[ "${WRITE_VERSION_TAG:-false}" = "true" ]] || [[ "${GITHUB_REF:-}" = "refs/heads/main" ]]; }
}

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

targets=("${tag}")
if write_version_tag; then
  targets+=("${version}")
fi

for name in "${names[@]}"; do
  sources=()
  for arch in "${arches[@]}"; do
    sources+=("${repo}/${name}:${tag}-${arch}")
  done
  for target in "${targets[@]}"; do
    echo "Writing ${repo}/${name}:${target} from ${sources[*]}"
    docker buildx imagetools create --tag "${repo}/${name}:${target}" "${sources[@]}"
  done
  if write_version_tag; then
    for arch in "${arches[@]}"; do
      echo "Writing ${repo}/${name}:${version}-${arch} from ${repo}/${name}:${tag}-${arch}"
      docker buildx imagetools create --tag "${repo}/${name}:${version}-${arch}" "${repo}/${name}:${tag}-${arch}"
    done
  fi
done

summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
{
  echo "### Multi-arch TAK images"
  echo
  echo "Tags written: ${targets[*]}"
  echo
  echo '```text'
} >> "${summary}"
for name in "${names[@]}"; do
  docker buildx imagetools inspect "${repo}/${name}:${tag}" | tee -a "${summary}"
done
echo '```' >> "${summary}"
