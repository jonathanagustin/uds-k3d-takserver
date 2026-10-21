#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Wait until the six TAK images can be inspected in GHCR, each as a
# multi-arch index that lists every platform in REQUIRED_PLATFORMS.
# GHCR does not accept a raw GitHub token as a registry bearer token.
# Docker login exchanges it, then `docker manifest inspect` reads the tag.
# If the container workflow is not running, build and push them.
set -euo pipefail

tag="${IMAGE_TAG:-5.7-RELEASE-14}"
owner_repo="${IMAGE_OWNER_REPO:-jonathanagustin/uds-k3d-takserver}"
branch="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"
grace_seconds="${WAIT_GRACE_SECONDS:-300}"
sleep_seconds="${WAIT_SLEEP_SECONDS:-30}"
deadline_seconds="${WAIT_DEADLINE_SECONDS:-9000}"
build_if_missing="${BUILD_IF_MISSING:-true}"
check_once="${CHECK_ONCE:-false}"
# An amd64-only tag left by an older build must not pass for an arm64 test.
# Set REQUIRED_PLATFORMS="" to accept any manifest.
required_platforms="${REQUIRED_PLATFORMS-linux/amd64 linux/arm64}"
docker_logged_in="false"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "GH_TOKEN is required to read GHCR." >&2
  exit 1
fi

names=(
  takserver-api
  takserver-messaging
  takserver-config
  takserver-plugins
  takserver-database-setup
  takserver-ignite
)

ensure_docker_login() {
  if [ "${docker_logged_in}" = "true" ]; then
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not available" >&2
    return 1
  fi
  echo "${GH_TOKEN}" | docker login ghcr.io -u "${GITHUB_ACTOR:-github}" --password-stdin
  docker_logged_in="true"
}

# GHCR rejects a raw GitHub token. This exchanges it for a pull bearer token.
registry_token() {
  local repo_path="$1"
  curl -sS -u "${GITHUB_ACTOR:-github}:${GH_TOKEN}" \
    "https://ghcr.io/token?service=ghcr.io&scope=repository:${repo_path}:pull" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' || true
}

manifest_accept="application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json"

registry_manifest_code() {
  local repo_path="$1"
  local reg_token code
  reg_token="$(registry_token "${repo_path}")"
  if [ -z "${reg_token}" ]; then
    echo "000"
    return 0
  fi
  code="$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${reg_token}" \
    -H "Accept: ${manifest_accept}" \
    "https://ghcr.io/v2/${repo_path}/manifests/${tag}" || true)"
  echo "${code:-000}"
}

# Print the os/arch of each image in the tag's index, one per line. A
# single-platform manifest prints nothing, so it never satisfies the check.
registry_manifest_platforms() {
  local repo_path="$1"
  local reg_token
  reg_token="$(registry_token "${repo_path}")"
  if [ -z "${reg_token}" ]; then
    return 0
  fi
  curl -sS \
    -H "Authorization: Bearer ${reg_token}" \
    -H "Accept: ${manifest_accept}" \
    "https://ghcr.io/v2/${repo_path}/manifests/${tag}" \
    | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except ValueError:
    raise SystemExit(0)
for entry in doc.get("manifests", []):
    platform = entry.get("platform") or {}
    if platform.get("os") and platform.get("architecture") not in (None, "unknown"):
        print(platform["os"] + "/" + platform["architecture"])
' || true
}

has_required_platforms() {
  local repo_path="$1"
  local found want
  if [ -z "${required_platforms}" ]; then
    return 0
  fi
  found="$(registry_manifest_platforms "${repo_path}")"
  for want in ${required_platforms}; do
    if ! grep -qx "${want}" <<< "${found}"; then
      echo "ghcr.io/${repo_path}:${tag} has no ${want} image (has: $(echo "${found}" | tr '\n' ' '))"
      return 1
    fi
  done
}

images_published() {
  local name image repo_path missing=0 code
  ensure_docker_login || echo "docker login failed; checking the registry token instead"
  for name in "${names[@]}"; do
    image="ghcr.io/${owner_repo}/${name}:${tag}"
    repo_path="${owner_repo}/${name}"
    if [ "${docker_logged_in}" = "true" ] && DOCKER_CLI_EXPERIMENTAL=enabled docker manifest inspect "${image}" >/dev/null 2>&1; then
      code="200"
    else
      code="$(registry_manifest_code "${repo_path}")"
    fi
    if [ "${code}" = "200" ]; then
      if has_required_platforms "${repo_path}"; then
        echo "${image} present"
      else
        missing=1
      fi
      continue
    fi
    echo "${image} missing (registry HTTP ${code})"
    missing=1
  done
  [ "${missing}" = "0" ]
}

container_run_status() {
  local status
  if [ -z "${branch}" ] || ! command -v gh >/dev/null 2>&1; then
    echo "unknown"
    return 0
  fi
  # actions:read is required. A 403 here must not abort the wait.
  # Pull request runs record the head commit, which is not GITHUB_SHA.
  status="$(gh run list \
    --workflow container.yaml \
    --branch "${branch}" \
    --limit 5 \
    --json status,conclusion,headSha 2>/dev/null \
    | EXPECTED_SHA="${EXPECTED_SHA:-}" GITHUB_SHA="${GITHUB_SHA:-}" SAME_SHA_ONLY="${SAME_SHA_ONLY:-}" python3 -c '
import json, os, sys
raw = sys.stdin.read().strip()
if not raw:
    print("unknown")
    raise SystemExit(0)
runs = json.loads(raw)
want = {os.environ.get("EXPECTED_SHA", ""), os.environ.get("GITHUB_SHA", "")}
want.discard("")
match = next((run for run in runs if run.get("headSha") in want), None)
if match is None and os.environ.get("SAME_SHA_ONLY") != "true" and runs and runs[0].get("status") != "completed":
    match = runs[0]
if match is None:
    print("none")
elif match.get("status") != "completed":
    print(match.get("status") or "unknown")
else:
    print(match.get("conclusion") or "unknown")
' || true)"
  if [ -z "${status}" ]; then
    echo "unknown"
    return 0
  fi
  echo "${status}"
}

# Tags can already exist while this commit is rebuilding them. Using the old
# tags would hide a Dockerfile change. Wait only when a container run for
# this SHA shows up. CHECK_ONCE is the build job itself and must not wait.
await_same_sha_build() {
  local status start now
  start="$(date +%s)"
  while true; do
    status="$(SAME_SHA_ONLY=true container_run_status)"
    echo "container workflow status: ${status}"
    case "${status}" in
      queued | in_progress | waiting | pending | requested)
        ;;
      failure | cancelled | startup_failure | timed_out)
        echo "The container workflow finished as ${status}." >&2
        return 1
        ;;
      success)
        return 0
        ;;
      none | unknown)
        now="$(date +%s)"
        if [ $((now - start)) -ge 90 ]; then
          return 0
        fi
        ;;
    esac
    now="$(date +%s)"
    if [ $((now - start)) -ge "${deadline_seconds}" ]; then
      echo "Timed out waiting for the container workflow." >&2
      return 1
    fi
    sleep "${sleep_seconds}"
  done
}

if images_published; then
  if [ "${check_once}" != "true" ]; then
    await_same_sha_build
  fi
  echo "All six images are already published."
  exit 0
fi

if [ "${check_once}" = "true" ]; then
  echo "The six tags are not all readable." >&2
  exit 1
fi

start="$(date +%s)"
success_waits=0
while true; do
  now="$(date +%s)"
  if [ $((now - start)) -ge "${deadline_seconds}" ]; then
    echo "Timed out waiting for ghcr.io/${owner_repo}/*:${tag}." >&2
    exit 1
  fi

  status="$(container_run_status)"
  echo "container workflow status: ${status}"
  case "${status}" in
    queued | in_progress | waiting | pending | requested)
      success_waits=0
      sleep "${sleep_seconds}"
      images_published && exit 0
      continue
      ;;
    success)
      sleep "${sleep_seconds}"
      images_published && exit 0
      success_waits=$((success_waits + 1))
      if [ "${success_waits}" -ge 10 ]; then
        echo "The container workflow succeeded, but the six tags are still not readable." >&2
        exit 1
      fi
      continue
      ;;
    failure | cancelled | startup_failure | timed_out)
      echo "The container workflow finished as ${status} and the images are not published." >&2
      exit 1
      ;;
  esac

  if [ "${build_if_missing}" != "true" ] || [ $((now - start)) -lt "${grace_seconds}" ]; then
    sleep "${sleep_seconds}"
    images_published && exit 0
    continue
  fi

  # build.sh builds the runner's architecture only. Push it as <tag>-<arch>
  # and let the merge script write <tag>, which refuses to drop a platform.
  case "$(uname -m)" in
    x86_64) host_arch=amd64 ;;
    aarch64 | arm64) host_arch=arm64 ;;
    *) host_arch="$(uname -m)" ;;
  esac
  echo "No image build is running. Building and pushing ${tag}-${host_arch}."
  PUSH_IMAGES=true IMAGE_TAG="${tag}-${host_arch}" PLATFORMS="linux/${host_arch}" \
    ./.github/container-and-chart/docker/build.sh
  if ! IMAGE_TAG="${tag}" ./.github/scripts/merge-image-manifests.sh; then
    echo "Only ${host_arch} was built here. Run the Container workflow to build every architecture." >&2
    exit 1
  fi
  images_published
  exit 0
done
