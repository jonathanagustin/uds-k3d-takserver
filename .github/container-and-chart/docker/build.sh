#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the six TAK Server images.
#
# Docker Buildx bake is the supported path. The six targets share one
# Gradle builder and build together. Podman is a best-effort override:
# set CONTAINER_RUNTIME=podman.
# The host does not need a JDK. Gradle runs in the builder stage.
#
#   PLATFORMS     default: the host architecture. Example: linux/amd64,linux/arm64
#   PUSH_IMAGES   true pushes the tags. Multi-arch pushes from buildx.
#   IMAGE_REPO    default: ghcr.io/jonathanagustin/uds-k3d-takserver
#   IMAGE_TAG     default: the contents of version.txt
#   GRADLE_SEED   directory of a previous Gradle home. CI restores one.
#   CACHE_SCOPE   GitHub Actions BuildKit cache scope. default: takserver.
#                 CI sets one per architecture so the two native builds do
#                 not overwrite each other's cache.
#
# The TAK source is the git submodule at upstream/takserver. It is checked
# out here if it is empty (a clone without --recurse-submodules).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
runtime="${CONTAINER_RUNTIME:-docker}"
repo="${IMAGE_REPO:-ghcr.io/jonathanagustin/uds-k3d-takserver}"
tag="${IMAGE_TAG:-$(tr -d '[:space:]' < "${here}/version.txt")}"
push="${PUSH_IMAGES:-false}"
cache_scope="${CACHE_SCOPE:-takserver}"
root="$(cd "${here}/../../.." && pwd)"

if ! command -v "${runtime}" >/dev/null 2>&1; then
  echo "Container runtime '${runtime}' is not on PATH." >&2
  exit 1
fi

if [ -z "${PLATFORMS:-}" ]; then
  machine="$(uname -m)"
  case "${machine}" in
    x86_64) PLATFORMS="linux/amd64" ;;
    aarch64 | arm64) PLATFORMS="linux/arm64" ;;
    *) PLATFORMS="linux/${machine}" ;;
  esac
fi

multi="false"
case "${PLATFORMS}" in
  *,*) multi="true" ;;
esac

if [ "${runtime}" != "docker" ]; then
  echo "Podman is best-effort. Multi-arch buildx is verified with Docker." >&2
fi

src="${root}/upstream/takserver"
if [ ! -e "${src}/src/build.gradle" ]; then
  echo "Checking out the upstream/takserver submodule"
  git -C "${root}" submodule update --init --depth 1 upstream/takserver
fi
upstream_sha="$(git -C "${src}" rev-parse HEAD)"
upstream_tree="$(git -C "${src}" rev-parse 'HEAD^{tree}')"
pinned_sha="$(git -C "${root}" rev-parse HEAD:upstream/takserver)"
if [ "${upstream_sha}" != "${pinned_sha}" ]; then
  echo "upstream/takserver is at ${upstream_sha}, but this commit pins ${pinned_sha}." >&2
  echo "Run: git submodule update --init --depth 1 upstream/takserver" >&2
  exit 1
fi
if [ -n "$(git -C "${src}" status --porcelain)" ]; then
  echo "upstream/takserver has local changes. The build uses the pinned commit only." >&2
  exit 1
fi
echo "TAK source: upstream/takserver ${upstream_sha} (tree ${upstream_tree})"

targets="takserver-config takserver-messaging takserver-api takserver-plugins takserver-database-setup takserver-ignite"

use_bake="false"
if [ "${runtime}" = "docker" ] && docker buildx version >/dev/null 2>&1; then
  use_bake="true"
fi

if [ "${use_bake}" = "true" ] && [ "${multi}" = "true" ]; then
  if ! docker buildx inspect takserver-builder >/dev/null 2>&1; then
    docker buildx create --name takserver-builder --driver docker-container --use
  else
    docker buildx use takserver-builder
  fi
fi

seed="${GRADLE_SEED:-}"
if [ -z "${seed}" ]; then
  if [ -d "${root}/.cache/gradle-user-home/caches" ]; then
    seed="${root}/.cache/gradle-user-home"
  else
    seed="${here}/gradle-seed"
  fi
fi

export REPO="${repo}"
export TAG="${tag}"
export PLATFORMS
export GRADLE_SEED="${seed}"
export TAK_SRC="${src}"
export UPSTREAM_SHA="${upstream_sha}"
export UPSTREAM_TREE="${upstream_tree}"

bake() {
  # bake resolves a relative context from the working directory. CI runs
  # this script from the repository root, where there is no Dockerfile.
  set -- \
    -f "${here}/docker-bake.hcl" \
    --set "*.context=${here}" \
    --set "*.dockerfile=Dockerfile" \
    "$@"
  if [ "${runtime}" = "docker" ] && [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    set -- \
      --set "takserver-*.cache-from=type=gha,scope=${cache_scope}" \
      --set "takserver-*.cache-to=type=gha,mode=max,scope=${cache_scope}" \
      "$@"
  fi
  "${runtime}" buildx bake "$@"
}

save_gradle_cache() {
  local dest="${root}/.cache/gradle-user-home.next"
  # Local export is one platform. The first requested platform is the one
  # bake just built, including a multi-arch run.
  local platform="${PLATFORMS%%,*}"
  rm -rf "${dest}"
  mkdir -p "${dest}"
  bake gradle-export \
    --set "gradle-export.platforms=${platform}" \
    --set "gradle-export.output=type=local,dest=${dest}"
  if [ -d "${dest}/caches" ]; then
    rm -rf "${root}/.cache/gradle-user-home"
    mkdir -p "${root}/.cache"
    mv "${dest}" "${root}/.cache/gradle-user-home"
    echo "Saved the Gradle cache to .cache/gradle-user-home"
  else
    rm -rf "${dest}"
    echo "Gradle export had no caches directory."
  fi
}

if [ "${use_bake}" = "true" ]; then
  echo "Building ${targets} for ${PLATFORMS} with buildx bake"
  if [ "${multi}" = "true" ] && [ "${push}" = "true" ]; then
    bake --push
  elif [ "${multi}" = "true" ]; then
    mkdir -p "${root}/build/oci"
    for target in ${targets}; do
      bake "${target}" --set "${target}.output=type=oci,dest=${root}/build/oci/${target}.tar"
    done
  else
    # --load keeps the tags in the local daemon for the Grype scan.
    bake --load
    if [ "${push}" = "true" ]; then
      for target in ${targets}; do
        "${runtime}" push "${repo}/${target}:${tag}"
      done
    fi
  fi
  save_gradle_cache
  echo "Built ${targets} (${PLATFORMS}) from ${here}"
  exit 0
fi

for target in ${targets}; do
  image="${repo}/${target}:${tag}"
  echo "Building ${image} for ${PLATFORMS} with ${runtime}"

  set -- \
    --file "${here}/Dockerfile" \
    --target "${target}" \
    --platform "${PLATFORMS}" \
    --tag "${image}" \
    --build-context "gradle-seed=${seed}" \
    --build-context "takserver-src=${src}" \
    --build-arg "UPSTREAM_SHA=${upstream_sha}" \
    --build-arg "UPSTREAM_TREE=${upstream_tree}" \
    "${here}"

  if [ "${runtime}" = "docker" ] && [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    set -- \
      --cache-from "type=gha,scope=${cache_scope}" \
      --cache-to "type=gha,mode=max,scope=${cache_scope}" \
      "$@"
  fi

  if [ "${multi}" = "true" ]; then
    echo "${runtime} has no buildx, so it cannot build ${PLATFORMS} in one invocation." >&2
    exit 1
  fi
  echo "${runtime} has no buildx. Falling back to '${runtime} build' for ${PLATFORMS}." >&2
  "${runtime}" build "$@"
  if [ "${push}" = "true" ]; then
    "${runtime}" push "${image}"
  fi
done

echo "Built ${targets} (${PLATFORMS}) from ${here}"
