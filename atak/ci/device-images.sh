#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Content-addressed ATAK device images. Each image gets a tag made of the
# ATAK version and a short hash of the files it is built from:
#
#   ghcr.io/jonathanagustin/uds-takserver/atak-civ-vm:5.5.1.10-<hash>
#
# When that tag is already in GHCR, nothing is built: the image is pulled.
# Building the APK takes about 25 minutes; a pull takes seconds.
#
#   device-images.sh keys      print KEY=value lines (tags and hashes)
#   device-images.sh missing   print the images whose tag is not in GHCR
#   device-images.sh build     build the missing images; PUSH=true pushes
#                              them under their tags, otherwise they are
#                              loaded into Docker
#   device-images.sh pull      pull every image and tag it LOCAL_TAG (dev)
#   device-images.sh wait      wait until every tag is in GHCR (another job
#                              pushes them), then pull
#   device-images.sh package-ref  print oci://<PKG_REF> when that Zarf
#                              package is in GHCR, nothing otherwise
#   device-images.sh publish-package DIR  publish the package created in
#                              DIR under PKG_REF, unless it is there already
#   device-images.sh release   point TAG (the ATAK version) at the keyed
#                              images and the keyed Zarf package in GHCR,
#                              without a pull or push
#
# The hash covers the git blobs of each image's inputs in the index, so it needs a
# git checkout and ignores unstaged edits. KEY_SALT invalidates every hash.
set -euo pipefail

REPO="${REPO:-ghcr.io/jonathanagustin/uds-takserver}"
CACHE="${CACHE:-${REPO}/build-cache}"
LOCAL_TAG="${LOCAL_TAG:-dev}"
KEY_SALT="${KEY_SALT:-v1}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${root}"

# The atak-civ submodule branch is the ATAK release (5.5.1.10).
ATAK_VERSION="${ATAK_VERSION:-$(git config -f .gitmodules submodule.upstream/atak-civ.branch)}"

# Inputs of each image. A path is a file or a directory; upstream/atak-civ
# is the submodule pin, and fetch-source.sh decides which LFS files it holds.
# This script is an input of every image: it holds the build commands
# (targets, flags), and a keyed tag is never rebuilt, so an edit here must
# not leave an image built by the old commands under a current key.
recipe=(atak/ci/device-images.sh)
apk_inputs=("${recipe[@]}" atak/apk atak/ci/build-apk.sh atak/ci/fetch-source.sh upstream/atak-civ)
driver_inputs=("${apk_inputs[@]}" atak/driver)
vm_inputs=("${recipe[@]}" atak/vm)
viewer_inputs=("${recipe[@]}" atak/viewer)

hash_of() {
  # git ls-files -s lists mode, object id and path: a change to any input
  # file, its mode, or the submodule commit changes the hash.
  { echo "${KEY_SALT}"; git ls-files -s -- "$@"; } | sha256sum | cut -c1-12
}

APK_KEY="$(hash_of "${apk_inputs[@]}")"
DRIVER_KEY="$(hash_of "${driver_inputs[@]}")"
VM_KEY="$(hash_of "${vm_inputs[@]}")"
VIEWER_KEY="$(hash_of "${viewer_inputs[@]}")"
# The optional Zarf package: its definition and manifests, the VM and viewer
# images it carries, the local tag it is created with, and the UDS CLI that
# creates it (UDS_VERSION, set by the workflow).
PKG_KEY="$( { echo "${KEY_SALT} ${LOCAL_TAG} ${UDS_VERSION:-}"; git ls-files -s -- atak/zarf.yaml atak/deploy; echo "${VM_KEY} ${VIEWER_KEY}"; } | sha256sum | cut -c1-12)"
PKG_REPO="${PKG_REPO:-${REPO}/packages}"
PKG_REF="${PKG_REPO}/atak-device:${ATAK_VERSION}-${PKG_KEY}"

# name|key|dockerfile|target
images=(
  "atak-civ-apk|${APK_KEY}|atak/apk/Dockerfile|apk"
  "atak-driver|${DRIVER_KEY}|atak/apk/Dockerfile|driver"
  "atak-civ-vm|${VM_KEY}|atak/vm/Dockerfile|"
  "atak-viewer|${VIEWER_KEY}|atak/viewer/Dockerfile|"
)

ref_of() { echo "${REPO}/$1:${ATAK_VERSION}-$2"; }

exists() { docker buildx imagetools inspect "$1" >/dev/null 2>&1; }

keys() {
  echo "ATAK_VERSION=${ATAK_VERSION}"
  echo "APK_KEY=${APK_KEY}"
  echo "DRIVER_KEY=${DRIVER_KEY}"
  echo "VM_KEY=${VM_KEY}"
  echo "VIEWER_KEY=${VIEWER_KEY}"
  echo "PKG_KEY=${PKG_KEY}"
  echo "PKG_REF=${PKG_REF}"
  echo "APK_IMAGE_KEYED=$(ref_of atak-civ-apk "${APK_KEY}")"
  echo "DRIVER_IMAGE_KEYED=$(ref_of atak-driver "${DRIVER_KEY}")"
  echo "VM_IMAGE_KEYED=$(ref_of atak-civ-vm "${VM_KEY}")"
  echo "VIEWER_IMAGE_KEYED=$(ref_of atak-viewer "${VIEWER_KEY}")"
}

# ONLY limits missing, pull and wait to some images ("atak-driver").
wanted() { [[ -z "${ONLY:-}" || " ${ONLY} " == *" $1 "* ]]; }

missing() {
  local entry name key
  for entry in "${images[@]}"; do
    IFS='|' read -r name key _ _ <<<"${entry}"
    wanted "${name}" || continue
    exists "$(ref_of "${name}" "${key}")" || echo "${name}"
  done
}

build() {
  local todo entry name key dockerfile target ref out
  mapfile -t todo < <(missing)
  if [[ "${#todo[@]}" -eq 0 ]]; then
    echo "Every device image is already in GHCR; nothing to build."
    [[ "${PUSH:-false}" = true ]] || pull
    return 0
  fi
  echo "To build: ${todo[*]}"
  out=(--load)
  [[ "${PUSH:-false}" = true ]] && out=(--push)
  # The APK and the driver share the long APK build. build-apk.sh builds it
  # one stage at a time with a keyed registry cache (see that script).
  if printf '%s\n' "${todo[@]}" | grep -qx -e atak-civ-apk -e atak-driver; then
    [[ -f upstream/atak-civ/depends/gdal-2.4.4-mod.tar.gz ]] || ./atak/ci/fetch-source.sh
    ./atak/ci/build-apk.sh
  fi
  for entry in "${images[@]}"; do
    IFS='|' read -r name key dockerfile target <<<"${entry}"
    printf '%s\n' "${todo[@]}" | grep -qx "${name}" || continue
    ref="$(ref_of "${name}" "${key}")"
    args=(-f "${dockerfile}" -t "${ref}" "${out[@]}")
    [[ -n "${target}" ]] && args+=(--target "${target}")
    case "${name}" in
      atak-civ-apk | atak-driver)
        # The stages build-apk.sh just wrote; nothing is rebuilt here.
        while read -r c; do args+=(--cache-from "${c}"); done < <(./atak/ci/build-apk.sh cache-from)
        ;;
      atak-civ-vm)
        args+=(--cache-from "type=registry,ref=${CACHE}:atak-vm")
        [[ "${PUSH:-false}" = true ]] && args+=(--cache-to "type=registry,ref=${CACHE}:atak-vm,mode=max,image-manifest=true,oci-mediatypes=true,ignore-error=true")
        ;;
      atak-viewer)
        args+=(--cache-from "type=registry,ref=${CACHE}:atak-viewer")
        [[ "${PUSH:-false}" = true ]] && args+=(--cache-to "type=registry,ref=${CACHE}:atak-viewer,mode=max,image-manifest=true,oci-mediatypes=true,ignore-error=true")
        ;;
      *) ;;
    esac
    start=$(date +%s)
    docker buildx build "${args[@]}" .
    echo "${name} built in $(($(date +%s) - start))s: ${ref}"
  done
  if [[ "${PUSH:-false}" != true ]]; then
    # Loaded images carry the keyed tag; add the local one. Images that were
    # not built come from GHCR.
    pull
  fi
}

pull() {
  local entry name key ref
  for entry in "${images[@]}"; do
    IFS='|' read -r name key _ _ <<<"${entry}"
    # The e2e test needs the driver, VM and viewer; the APK is inside the driver.
    [[ "${name}" = atak-civ-apk ]] && continue
    wanted "${name}" || continue
    ref="$(ref_of "${name}" "${key}")"
    docker image inspect "${ref}" >/dev/null 2>&1 || docker pull -q "${ref}"
    docker tag "${ref}" "${REPO}/${name}:${LOCAL_TAG}"
    echo "${REPO}/${name}:${LOCAL_TAG} = ${ref}"
  done
}

wait_for() {
  # The images job of the same run builds and pushes what is missing.
  local deadline=$(($(date +%s) + ${WAIT_SECONDS:-7200})) left
  while :; do
    left="$(missing | tr '\n' ' ')"
    [[ -z "${left// /}" ]] && break
    # IMAGES_JOB names the job that builds them. When it has finished
    # without pushing them, stop instead of waiting out the deadline.
    if [[ -n "${IMAGES_JOB:-}" && -n "${GITHUB_RUN_ID:-}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
      state="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/attempts/${GITHUB_RUN_ATTEMPT:-1}/jobs" \
        --jq ".jobs[] | select(.name == \"${IMAGES_JOB}\") | .status + \" \" + (.conclusion // \"\")" 2>/dev/null || true)"
      if [[ "${state}" == completed* ]] && [[ -n "$(missing)" ]]; then
        echo "Job ${IMAGES_JOB} ended (${state}) without pushing ${left}" >&2
        exit 1
      fi
    fi
    if (($(date +%s) > deadline)); then
      echo "Timed out waiting for ${left}" >&2
      exit 1
    fi
    echo "$(date -u +%H:%M:%S) waiting for ${left}"
    sleep 30
  done
  pull
}

release() {
  # Main only: TAG (5.5.1.10) points at the images the e2e run just tested.
  local tag="${TAG:?release tag}" entry name key
  for entry in "${images[@]}"; do
    IFS='|' read -r name key _ _ <<<"${entry}"
    [[ "${name}" = atak-civ-apk ]] && continue
    # crane copy keeps the digest: the release tag is the tested image.
    uds zarf tools registry copy "$(ref_of "${name}" "${key}")" "${REPO}/${name}:${tag}"
  done
  # The package the e2e run deployed gets the same plain tag, so
  # packages/atak-device:5.5.1.10 is the tested package, by digest.
  if ! pkg_exists; then
    echo "${PKG_REF} is not in GHCR; cannot tag it ${tag}" >&2
    return 1
  fi
  uds zarf tools registry copy "${PKG_REF}" "${PKG_REPO}/atak-device:${tag}"
}

# A Zarf package is an OCI artifact, not an image; crane reads any manifest.
pkg_exists() { uds zarf tools registry digest "${PKG_REF}" >/dev/null 2>&1; }

package_ref() {
  if pkg_exists; then
    echo "oci://${PKG_REF}"
  fi
}

publish_package() {
  local dir="${1:?package directory}" files
  if pkg_exists; then
    echo "${PKG_REF} exists; not publishing."
    return 0
  fi
  files=("${dir}"/zarf-package-atak-device-amd64-*.tar.zst)
  [[ -f "${files[0]}" ]] || { echo "No package in ${dir}" >&2; return 1; }
  uds zarf package publish "${files[0]}" "oci://${PKG_REPO}" --tag "${ATAK_VERSION}-${PKG_KEY}" --confirm
}

case "${1:-keys}" in
  keys) keys ;;
  missing) missing ;;
  build) build ;;
  pull) pull ;;
  wait) wait_for ;;
  release) release ;;
  package-ref) package_ref ;;
  publish-package) publish_package "${2:-}" ;;
  *) echo "usage: $0 keys|missing|build|pull|wait|release|package-ref|publish-package DIR" >&2; exit 2 ;;
esac
