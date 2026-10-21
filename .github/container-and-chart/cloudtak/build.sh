#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the CloudTAK image from the upstream/cloudtak submodule.
#
#   build.sh                 build and load into the local Docker daemon
#   PUSH_IMAGES=true build.sh   build and push to REGISTRY
#   build.sh --if-changed    with PUSH_IMAGES=true, skip the build when the
#                            published image already carries the same inputs
#   build.sh --wait          build nothing. Wait until the published image
#                            carries this commit's inputs (WAIT_SECONDS,
#                            default 5400). Needs no submodule checkout.
#
# The inputs label is the submodule commit plus the git tree of this
# directory. A change to either one makes a new image.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(git -C "${here}" rev-parse --show-toplevel)"
src="${root}/upstream/cloudtak"
registry="${REGISTRY:-ghcr.io/jonathanagustin/uds-k3d-takserver}"

published_inputs() {
  docker buildx imagetools inspect "$1" --format '{{ json .Image }}' 2>/dev/null \
    | python3 -c 'import json,sys; c=json.load(sys.stdin); print(((c.get("config") or {}).get("Labels") or {}).get("dev.uds-k3d-takserver.inputs",""))' 2>/dev/null || true
}

# The scan and package workflows run next to the Test workflow, which
# builds the image. They wait for it here instead of reading an old or
# missing image.
if [ "${1:-}" = "--wait" ]; then
  version="$(git -C "${root}" config -f .gitmodules submodule.upstream/cloudtak.branch)"
  inputs="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)-$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
  image="${registry}/cloudtak:${version}"
  deadline=$(( $(date +%s) + ${WAIT_SECONDS:-5400} ))
  while :; do
    current="$(published_inputs "${image}")"
    if [ "${current}" = "${inputs}" ]; then
      echo "${image} has inputs ${inputs}"
      exit 0
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      echo "${image} has inputs '${current:-none}', not ${inputs}" >&2
      exit 1
    fi
    echo "waiting for ${image} with inputs ${inputs} (now '${current:-none}')"
    sleep 30
  done
fi

if [ ! -f "${src}/Dockerfile" ]; then
  git -C "${root}" submodule update --init --depth 1 upstream/cloudtak
fi

pinned="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)"
sha="$(git -C "${src}" rev-parse HEAD)"
if [ "${sha}" != "${pinned}" ]; then
  echo "upstream/cloudtak is at ${sha}, but this commit pins ${pinned}" >&2
  echo "Run: git submodule update --init --depth 1 upstream/cloudtak" >&2
  exit 1
fi
if [ -n "$(git -C "${src}" status --porcelain --untracked-files=no)" ]; then
  echo "upstream/cloudtak has local changes" >&2
  exit 1
fi

version="$(git -C "${root}" config -f .gitmodules submodule.upstream/cloudtak.branch)"
# Committed tree of this directory. Uncommitted edits make a local-only key.
tree="$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
if [ -n "$(git -C "${root}" status --porcelain -- .github/container-and-chart/cloudtak)" ]; then
  tree="${tree}-dirty"
fi
inputs="${sha}-${tree}"
image="${registry}/cloudtak:${version}"

if [ "${1:-}" = "--if-changed" ] && [ "${PUSH_IMAGES:-false}" = "true" ]; then
  current="$(published_inputs "${image}")"
  if [ "${current}" = "${inputs}" ]; then
    echo "${image} already has inputs ${inputs}"
    exit 0
  fi
  echo "${image} has inputs '${current:-none}'. Building ${inputs}."
fi

export REGISTRY="${registry}" CLOUDTAK_VERSION="${version}" CLOUDTAK_SRC="${src}" UPSTREAM_SHA="${sha}" INPUTS="${inputs}"
output="--load"
if [ "${PUSH_IMAGES:-false}" = "true" ]; then
  output="--push"
fi
cd "${here}"
# The bake file reads the submodule, which is outside this directory.
# Buildx asks for that read to be granted.
allow=()
if docker buildx bake --help 2>/dev/null | grep -q -- '--allow'; then
  allow=(--allow "fs.read=${root}")
fi
docker buildx bake -f docker-bake.hcl "${allow[@]}" "${output}" cloudtak
