#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the PostGIS image used by TAK and CloudTAK.
#
#   build.sh                     build for this machine's architecture and
#                                load it into the local Docker daemon
#   ARCH=<arch> PUSH_IMAGES=true build.sh [--if-changed]
#                                build linux/<arch> on a native runner and
#                                push <version>-<arch>. --if-changed skips the
#                                build when that tag already carries the same
#                                inputs
#   build.sh --merge             write <version> as a multi-arch index of the
#                                <version>-<arch> tags (ARCHES, default
#                                "amd64 arm64"). Every one must carry this
#                                commit's inputs. Nothing is written if the
#                                index already does
#   build.sh --wait              build nothing. Wait until <version> is an
#                                index whose every ARCHES platform carries this
#                                commit's inputs (WAIT_SECONDS, default 5400)
#
# The inputs label is the git tree of this directory, so a change to the
# Dockerfile or the init script makes a new image. zarf.yaml and the chart
# values reference <version>, and Zarf pulls the platform that matches the
# package architecture.
#
#   REGISTRY       default: ghcr.io/jonathanagustin/uds-k3d-takserver
#   POSTGRES_IMAGE override the pinned base image, for example to pull it
#                  through a mirror when Docker Hub limits anonymous pulls
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(git -C "${here}" rev-parse --show-toplevel)"
registry="${REGISTRY:-ghcr.io/jonathanagustin/uds-k3d-takserver}"
# PostgreSQL major and PostGIS major.minor, the tag the chart and zarf.yaml use.
version="15-3.4"
image="${registry}/postgis:${version}"

read -r -a arches <<< "${ARCHES:-amd64 arm64}"

# Committed tree of this directory. Uncommitted edits make a local-only key.
inputs="$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/postgis)"
if [[ -n "$(git -C "${root}" status --porcelain -- .github/container-and-chart/postgis)" ]]; then
  inputs="${inputs}-dirty"
fi

# Print "<os>/<arch> <inputs label>" for each platform of an image or index.
# Attestation entries (unknown/unknown) are skipped.
published_inputs() {
  docker buildx imagetools inspect "$1" --format '{{ json .Image }}' 2>/dev/null \
    | python3 -c '
import json, sys
data = json.load(sys.stdin)
images = {str(data.get("os")) + "/" + str(data.get("architecture")): data} if "config" in data else data
for platform, image in sorted(images.items()):
    if platform.startswith("unknown"):
        continue
    labels = ((image or {}).get("config") or {}).get("Labels") or {}
    print(platform, labels.get("dev.uds-k3d-takserver.inputs", ""))
' 2>/dev/null || true
}

# True when the listing has linux/<arch> with the given inputs.
has_arch() {
  grep -qx "linux/$2 $3" <<< "$1"
}

# True when every platform in ARCHES is present with the given inputs.
has_all_arches() {
  local listing="$1" want="$2" arch
  for arch in "${arches[@]}"; do
    if ! has_arch "${listing}" "${arch}" "${want}"; then
      return 1
    fi
  done
}

if [[ "${1:-}" = "--wait" ]]; then
  deadline=$(( $(date +%s) + ${WAIT_SECONDS:-5400} ))
  while :; do
    current="$(published_inputs "${image}")"
    if has_all_arches "${current}" "${inputs}"; then
      echo "${image} has inputs ${inputs} for ${arches[*]}"
      exit 0
    fi
    if [[ "$(date +%s)" -ge "${deadline}" ]]; then
      echo "${image} does not have inputs ${inputs} for every one of ${arches[*]}. Published:" >&2
      printf '%s\n' "${current:-none}" >&2
      exit 1
    fi
    echo "waiting for ${image} with inputs ${inputs} for ${arches[*]} (now: $(tr '\n' ' ' <<< "${current:-none}"))"
    sleep 30
  done
fi

if [[ "${1:-}" = "--merge" ]]; then
  if has_all_arches "$(published_inputs "${image}")" "${inputs}"; then
    echo "${image} is already an index with inputs ${inputs} for ${arches[*]}"
    exit 0
  fi
  # A partial index would replace a good tag with fewer platforms, so check
  # every source before writing.
  sources=()
  for arch in "${arches[@]}"; do
    source="${image}-${arch}"
    if ! has_arch "$(published_inputs "${source}")" "${arch}" "${inputs}"; then
      echo "${source} is missing or does not have inputs ${inputs}. Not writing ${image}." >&2
      exit 1
    fi
    sources+=("${source}")
  done
  echo "Writing ${image} from ${sources[*]}"
  docker buildx imagetools create --tag "${image}" "${sources[@]}"
  docker buildx imagetools inspect "${image}"
  exit 0
fi

# A pushed build is one architecture on a native runner, tagged
# <version>-<arch>. A local build is this machine's architecture under
# <version>.
case "$(uname -m)" in
  x86_64) host_arch=amd64 ;;
  aarch64 | arm64) host_arch=arm64 ;;
  *) host_arch="$(uname -m)" ;;
esac
arch="${ARCH:-${host_arch}}"
tag="${version}"
output="--load"
if [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  if [[ -z "${ARCH:-}" ]]; then
    echo "Set ARCH (amd64 or arm64) to push. build.sh --merge writes ${version}." >&2
    exit 1
  fi
  tag="${version}-${arch}"
  output="--push"
fi

if [[ "${1:-}" = "--if-changed" ]] && [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  current="$(published_inputs "${image}-${arch}")"
  if has_arch "${current}" "${arch}" "${inputs}"; then
    echo "${image}-${arch} already has inputs ${inputs}"
    exit 0
  fi
  echo "${image}-${arch} has '$(tr '\n' ' ' <<< "${current:-none}")'. Building ${inputs}."
fi

args=(--platform "linux/${arch}" --build-arg "INPUTS=${inputs}" --tag "${registry}/postgis:${tag}")
if [[ -n "${POSTGRES_IMAGE:-}" ]]; then
  args+=(--build-arg "POSTGRES_IMAGE=${POSTGRES_IMAGE}")
fi
docker buildx build "${args[@]}" "${output}" "${here}"
