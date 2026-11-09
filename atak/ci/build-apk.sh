#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Builds atak/apk/Dockerfile one stage at a time, so each finished stage is
# written to the registry cache even when a later stage fails. The APK lands
# in ./out. CACHE is the cache image (without tag).
#
# Each stage's cache tag carries a hash of that stage's inputs
# (atak-apk-<stage>-<hash>). A keyed tag is written once, by the build that
# produced it, and never rewritten. A stage whose keyed tag already exists is
# not built again. The untagged-by-hash atak-apk-<stage> tags are still read
# (and written after a real build) so an input change reuses the earlier
# layers it did not touch.
#
#   build-apk.sh              build the stages and write the APK to ./out
#   build-apk.sh cache-from   print the --cache-from values for this tree
set -euo pipefail
CACHE="${CACHE:?registry cache image}"
KEY_SALT="${KEY_SALT:-v1}"
cd "$(dirname "$0")/../.."

stage_inputs() {
  # Cumulative: a stage depends on everything the stage before it does.
  local base=(atak/apk/Dockerfile atak/apk/requirements.txt)
  case "$1" in
    toolchain) echo "${base[*]}" ;;
    ttp) echo "${base[*]} upstream/atak-civ atak/ci/fetch-source.sh" ;;
    deps | cesium) echo "${base[*]} upstream/atak-civ atak/ci/fetch-source.sh atak/apk/prebuild.sh atak/apk/conan" ;;
    apk) echo "${base[*]} upstream/atak-civ atak/ci/fetch-source.sh atak/apk/prebuild.sh atak/apk/conan atak/apk/build-apk.sh" ;;
    *) echo "unknown stage $1" >&2; exit 2 ;;
  esac
}
key_of() {
  # shellcheck disable=SC2046 # word splitting of the path list is intended
  { echo "${KEY_SALT} $1"; git ls-files -s -- $(stage_inputs "$1"); } | sha256sum | cut -c1-12
}

stages=(toolchain ttp deps cesium apk)
declare -A key
for s in "${stages[@]}"; do key[${s}]="$(key_of "${s}")"; done

cache_from() {
  local s
  for s in "${stages[@]}"; do
    [[ "${s}" = toolchain ]] && continue
    echo "type=registry,ref=${CACHE}:atak-apk-${s}-${key[${s}]}"
  done
  # Fallback for a changed input: the layers before the change.
  for s in ttp deps cesium apk; do
    echo "type=registry,ref=${CACHE}:atak-apk-${s}"
  done
}

if [[ "${1:-}" = cache-from ]]; then
  cache_from
  exit 0
fi

from=()
while read -r c; do from+=(--cache-from "${c}"); done < <(cache_from)

exists() { docker buildx imagetools inspect "$1" >/dev/null 2>&1; }

start=$(date +%s)
for target in "${stages[@]}"; do
  keyed="${CACHE}:atak-apk-${target}-${key[${target}]}"
  have=false
  exists "${keyed}" && have=true
  if [[ "${have}" = true && "${target}" != apk ]]; then
    echo "${target}: ${keyed} exists, skipped"
    continue
  fi
  out=(--output type=cacheonly)
  if [[ "${target}" = apk ]]; then
    out=(--output "type=local,dest=out")
  fi
  to=()
  if [[ "${have}" != true ]]; then
    # Rewriting a tag from a build that was entirely cached can leave a
    # cache manifest whose records point at no layers; the next build then
    # misses. So the keyed tag is written only when it does not exist.
    to=(--cache-to "type=registry,ref=${keyed},mode=max,image-manifest=true,oci-mediatypes=true,ignore-error=true"
      --cache-to "type=registry,ref=${CACHE}:atak-apk-${target},mode=max,image-manifest=true,oci-mediatypes=true,ignore-error=true")
  fi
  docker buildx build -f atak/apk/Dockerfile --target "${target}" \
    "${from[@]}" "${to[@]}" "${out[@]}" .
  echo "${target} done after $(($(date +%s) - start))s"
done
ls -la out
