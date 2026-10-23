#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the PostGIS image used by TAK and CloudTAK.
#
#   build.sh                     build for this machine's architecture and
#                                load it into the local Docker daemon
#   ARCH=<arch> PUSH_IMAGES=true build.sh [--if-changed]
#                                build linux/<arch> on a native runner and
#                                push <version>-<key>-<arch>. --if-changed skips the
#                                build when that tag already carries the same
#                                inputs
#   build.sh --merge             write <version>-<key> as a multi-arch index
#                                of the <version>-<key>-<arch> tags (ARCHES,
#                                default "amd64 arm64"). Every one must carry
#                                this commit's inputs. On main it also writes
#                                <version>
#   build.sh --wait              build nothing. Wait until <version>-<key> is
#                                an index whose every ARCHES platform carries
#                                this commit's inputs (WAIT_SECONDS, default
#                                5400)
#   build.sh --tag               print <version>-<key> for this commit
#
# The inputs label is the git tree of this directory, so a change to the
# Dockerfile or the init script makes a new image. <key> is the first 12 hex
# digits of the SHA-256 of that label.
#
# A pushed build is tagged <version>-<key>-<arch>, and --merge writes
# <version>-<key>. Those tags only ever hold one set of inputs, so a pull
# request that deploys <version>-<key> (.github/scripts/pin-image-tags.sh)
# gets the image built from its own inputs. <version> and <version>-<arch>,
# the tags zarf.yaml and the charts name and releases ship, are written only
# from main (GITHUB_REF=refs/heads/main) or with WRITE_VERSION_TAG=true.
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
version_image="${registry}/postgis:${version}"

read -r -a arches <<< "${ARCHES:-amd64 arm64}"

# Committed tree of this directory. Uncommitted edits make a local-only key.
inputs="$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/postgis)"
if [[ -n "$(git -C "${root}" status --porcelain -- .github/container-and-chart/postgis)" ]]; then
  inputs="${inputs}-dirty"
fi
key="$(printf '%s' "${inputs}" | sha256sum | cut -c1-12)"
image="${registry}/postgis:${version}-${key}"

# PUSHED_REFS names a file that gets one line per tag this run pushed or
# wrote as an index. The workflows attest those (.github/actions/attest-images).
record_push() {
  if [[ -n "${PUSHED_REFS:-}" ]]; then
    echo "$1" >> "${PUSHED_REFS}"
  fi
}

write_version_tag() {
  [[ "${WRITE_VERSION_TAG:-false}" = "true" ]] || [[ "${GITHUB_REF:-}" = "refs/heads/main" ]]
}

if [[ "${1:-}" = "--tag" ]]; then
  echo "${version}-${key}"
  exit 0
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
  targets=("${image}")
  if write_version_tag; then
    targets+=("${version_image}")
  fi
  # A partial index would replace a good tag with fewer platforms, so check
  # every source before writing.
  sources=()
  for arch in "${arches[@]}"; do
    source="${image}-${arch}"
    if ! has_arch "$(published_inputs "${source}")" "${arch}" "${inputs}"; then
      echo "${source} is missing or does not have inputs ${inputs}. Not writing ${targets[*]}." >&2
      exit 1
    fi
    sources+=("${source}")
  done
  for target in "${targets[@]}"; do
    if has_all_arches "$(published_inputs "${target}")" "${inputs}"; then
      echo "${target} is already an index with inputs ${inputs} for ${arches[*]}"
      continue
    fi
    echo "Writing ${target} from ${sources[*]}"
    docker buildx imagetools create --tag "${target}" "${sources[@]}"
    docker buildx imagetools inspect "${target}"
    record_push "${target}"
  done
  exit 0
fi

# A pushed build is one architecture on a native runner, tagged
# <version>-<key>-<arch>. A local build is this machine's architecture under
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
    echo "Set ARCH (amd64 or arm64) to push. build.sh --merge writes ${version}-${key}." >&2
    exit 1
  fi
  tag="${version}-${key}-${arch}"
  output="--push"
fi
keyed_arch="${image}-${arch}"
version_arch="${version_image}-${arch}"

# After a push, point <version>-<arch> at the keyed tag on main.
publish_version_arch() {
  if write_version_tag && ! has_arch "$(published_inputs "${version_arch}")" "${arch}" "${inputs}"; then
    echo "Writing ${version_arch} from ${keyed_arch}"
    docker buildx imagetools create --tag "${version_arch}" "${keyed_arch}"
  fi
}

if [[ "${1:-}" = "--if-changed" ]] && [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  current="$(published_inputs "${keyed_arch}")"
  if has_arch "${current}" "${arch}" "${inputs}"; then
    echo "${keyed_arch} already has inputs ${inputs}"
    publish_version_arch
    exit 0
  fi
  # An image built before the keyed tags existed: tag it, then check the copy.
  if has_arch "$(published_inputs "${version_arch}")" "${arch}" "${inputs}"; then
    docker buildx imagetools create --tag "${keyed_arch}" "${version_arch}"
    if has_arch "$(published_inputs "${keyed_arch}")" "${arch}" "${inputs}"; then
      echo "${keyed_arch} copied from ${version_arch}, which has inputs ${inputs}"
      exit 0
    fi
  fi
  echo "${keyed_arch} has '$(tr '\n' ' ' <<< "${current:-none}")'. Building ${inputs}."
fi

args=(--platform "linux/${arch}" --build-arg "INPUTS=${inputs}" --tag "${registry}/postgis:${tag}")
if [[ -n "${POSTGRES_IMAGE:-}" ]]; then
  args+=(--build-arg "POSTGRES_IMAGE=${POSTGRES_IMAGE}")
fi
docker buildx build "${args[@]}" "${output}" "${here}"
if [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  record_push "${registry}/postgis:${tag}"
  publish_version_arch
fi
