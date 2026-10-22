#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Build the CloudTAK image from the upstream/cloudtak submodule.
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
#                                5400). Needs no submodule checkout
#   build.sh --tag               print <version>-<key> for this commit
#
# The inputs label is the submodule commit plus the git tree of this
# directory. A change to either one makes a new image. <key> is the first 12
# hex digits of the SHA-256 of that label.
#
# A pushed build is tagged <version>-<key>-<arch>, and --merge writes
# <version>-<key>. Those tags only ever hold one set of inputs, so a pull
# request that deploys <version>-<key> (.github/scripts/pin-image-tags.sh)
# gets the image built from its own inputs, whatever another branch builds
# at the same time. <version> and <version>-<arch>, the tags zarf.yaml and the
# chart name and releases ship, are written only from main
# (GITHUB_REF=refs/heads/main) or with WRITE_VERSION_TAG=true.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(git -C "${here}" rev-parse --show-toplevel)"
src="${root}/upstream/cloudtak"
registry="${REGISTRY:-ghcr.io/jonathanagustin/uds-k3d-takserver}"

read -r -a arches <<< "${ARCHES:-amd64 arm64}"

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
has_all_arches_one() {
  grep -qx "linux/$2 $3" <<< "$1"
}

# True when every platform in ARCHES is present with the given inputs.
has_all_arches() {
  local listing="$1" want="$2" arch
  for arch in "${arches[@]}"; do
    if ! grep -qx "linux/${arch} ${want}" <<< "${listing}"; then
      return 1
    fi
  done
}

input_key() {
  printf '%s' "$1" | sha256sum | cut -c1-12
}

write_version_tag() {
  [[ "${WRITE_VERSION_TAG:-false}" = "true" ]] || [[ "${GITHUB_REF:-}" = "refs/heads/main" ]]
}

version="$(git -C "${root}" config -f .gitmodules submodule.upstream/cloudtak.branch)"

if [[ "${1:-}" = "--tag" ]]; then
  inputs="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)-$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
  echo "${version}-$(input_key "${inputs}")"
  exit 0
fi

# The scan and package workflows run next to the Test workflow, which
# builds the image. They wait for it here instead of reading an old or
# missing image.
if [[ "${1:-}" = "--wait" ]]; then
  inputs="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)-$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
  image="${registry}/cloudtak:${version}-$(input_key "${inputs}")"
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
  inputs="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)-$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
  keyed="${registry}/cloudtak:${version}-$(input_key "${inputs}")"
  targets=("${keyed}")
  if write_version_tag; then
    targets+=("${registry}/cloudtak:${version}")
  fi
  # A partial index would replace a good tag with fewer platforms, so check
  # every source before writing.
  sources=()
  for arch in "${arches[@]}"; do
    source="${keyed}-${arch}"
    if ! has_all_arches_one "$(published_inputs "${source}")" "${arch}" "${inputs}"; then
      echo "${source} is missing or does not have inputs ${inputs}. Not writing ${targets[*]}." >&2
      exit 1
    fi
    sources+=("${source}")
  done
  for image in "${targets[@]}"; do
    if has_all_arches "$(published_inputs "${image}")" "${inputs}"; then
      echo "${image} is already an index with inputs ${inputs} for ${arches[*]}"
      continue
    fi
    echo "Writing ${image} from ${sources[*]}"
    docker buildx imagetools create --tag "${image}" "${sources[@]}"
    docker buildx imagetools inspect "${image}"
  done
  exit 0
fi

if [[ ! -f "${src}/Dockerfile" ]]; then
  git -C "${root}" submodule update --init --depth 1 upstream/cloudtak
fi

pinned="$(git -C "${root}" rev-parse HEAD:upstream/cloudtak)"
sha="$(git -C "${src}" rev-parse HEAD)"
if [[ "${sha}" != "${pinned}" ]]; then
  echo "upstream/cloudtak is at ${sha}, but this commit pins ${pinned}" >&2
  echo "Run: git submodule update --init --depth 1 upstream/cloudtak" >&2
  exit 1
fi
if [[ -n "$(git -C "${src}" status --porcelain --untracked-files=no)" ]]; then
  echo "upstream/cloudtak has local changes" >&2
  exit 1
fi

# Committed tree of this directory. Uncommitted edits make a local-only key.
tree="$(git -C "${root}" rev-parse HEAD:.github/container-and-chart/cloudtak)"
if [[ -n "$(git -C "${root}" status --porcelain -- .github/container-and-chart/cloudtak)" ]]; then
  tree="${tree}-dirty"
fi
inputs="${sha}-${tree}"
# A pushed build is one architecture on a native runner, tagged
# <version>-<key>-<arch>. A local build is this machine's architecture under
# <version>.
case "$(uname -m)" in
  x86_64) host_arch=amd64 ;;
  aarch64 | arm64) host_arch=arm64 ;;
  *) host_arch="$(uname -m)" ;;
esac
arch="${ARCH:-${host_arch}}"
if [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  if [[ -z "${ARCH:-}" ]]; then
    echo "Set ARCH (amd64 or arm64) to push. build.sh --merge writes ${version}." >&2
    exit 1
  fi
  tag="${version}-$(input_key "${inputs}")-${arch}"
else
  tag="${version}"
fi
image="${registry}/cloudtak:${tag}"
version_arch="${registry}/cloudtak:${version}-${arch}"

# After a push, point <version>-<arch> at the keyed tag on main.
publish_version_arch() {
  if write_version_tag && ! has_all_arches_one "$(published_inputs "${version_arch}")" "${arch}" "${inputs}"; then
    echo "Writing ${version_arch} from ${image}"
    docker buildx imagetools create --tag "${version_arch}" "${image}"
  fi
}

if [[ "${1:-}" = "--if-changed" ]] && [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  current="$(published_inputs "${image}")"
  if has_all_arches_one "${current}" "${arch}" "${inputs}"; then
    echo "${image} already has inputs ${inputs}"
    publish_version_arch
    exit 0
  fi
  # An image built before the keyed tags existed: tag it, then check the copy.
  if has_all_arches_one "$(published_inputs "${version_arch}")" "${arch}" "${inputs}"; then
    docker buildx imagetools create --tag "${image}" "${version_arch}"
    if has_all_arches_one "$(published_inputs "${image}")" "${arch}" "${inputs}"; then
      echo "${image} copied from ${version_arch}, which has inputs ${inputs}"
      exit 0
    fi
  fi
  echo "${image} has '$(tr '\n' ' ' <<< "${current:-none}")'. Building ${inputs}."
fi

export REGISTRY="${registry}" CLOUDTAK_VERSION="${version}" CLOUDTAK_SRC="${src}" UPSTREAM_SHA="${sha}" INPUTS="${inputs}" PLATFORM="linux/${arch}" IMAGE_TAG="${tag}"
output="--load"
if [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
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
if [[ "${PUSH_IMAGES:-false}" = "true" ]]; then
  publish_version_arch
fi
