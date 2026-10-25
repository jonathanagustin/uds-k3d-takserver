#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Patch fixable OS packages in local images.
#
# Trivy writes a report of fixed OS vulnerabilities. Copa applies the
# package upgrades and replaces the same tag. Set COPA=false to skip.
# A multi-arch image is not loaded in the local daemon, so the caller
# only passes single-architecture tags.
set -euo pipefail

if [[ "${COPA:-true}" != "true" ]]; then
  echo "COPA is not true. Leaving the images unchanged."
  exit 0
fi

if [[ "$#" -lt 1 ]]; then
  echo "usage: copa-patch.sh image [image...]" >&2
  exit 2
fi

trivy_image="${TRIVY_IMAGE:-aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c}"
registry_image="${COPA_REGISTRY_IMAGE:-docker.io/library/registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373}"
registry_name="copa-registry"
registry_port="5000"
builder_name="copa-patch"
started_registry=0
started_builder=0
copa_version="0.15.0"

case "$(uname -m)" in
  x86_64)
    copa_arch="amd64"
    copa_sha="cff3fe9320f3bd24bafcfd0ce877ef57e23acad0836da0ac6c253919f71c9cad"
    ;;
  aarch64 | arm64)
    copa_arch="arm64"
    copa_sha="2444b6109c6164beef980641ec5f2813bc42b1703add6dd73591ace23051ca8f"
    ;;
  *)
    echo "copa has no binary for $(uname -m)" >&2
    exit 1
    ;;
esac

work="$(mktemp -d)"
cleanup() {
  if [[ "${started_builder}" -eq 1 ]]; then
    docker buildx rm -f "${builder_name}" >/dev/null 2>&1 || true
  fi
  if [[ "${started_registry}" -eq 1 ]]; then
    docker rm -f "${registry_name}" >/dev/null 2>&1 || true
  fi
  # Trivy runs as root and leaves a cache this user cannot remove.
  docker run --rm --entrypoint /bin/rm \
    -v "${work}:/work" \
    "${trivy_image}" \
    -rf /work/cache /work/reports >/dev/null 2>&1 || true
  rm -rf "${work}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
mkdir -p "${work}/cache" "${work}/reports"

if [[ -n "${COPA_BIN:-}" ]]; then
  copa="${COPA_BIN}"
else
  tarball="copa_${copa_version}_linux_${copa_arch}.tar.gz"
  curl -fsSL -o "${work}/${tarball}" \
    "https://github.com/project-copacetic/copacetic/releases/download/v${copa_version}/${tarball}"
  echo "${copa_sha}  ${work}/${tarball}" | sha256sum -c -
  tar -C "${work}" -xzf "${work}/${tarball}"
  copa="${work}/copa"
fi

count_fixable() {
  python3 - "$1" << 'PY'
import json
import sys

report = json.load(open(sys.argv[1]))
count = 0
for result in report.get("Results") or []:
    count += len(result.get("Vulnerabilities") or [])
print(count)
PY
}

scan() {
  local image="$1"
  local report="$2"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${work}/cache:/root/.cache" \
    -v "${work}/reports:/out" \
    "${trivy_image}" image \
    --pkg-types os \
    --ignore-unfixed \
    --quiet \
    --format json \
    --output "/out/$(basename "${report}")" \
    "${image}"
}

# setup-buildx-action's container builder has the docker exporter Copa uses
# to load a patched image, and it cannot read a tag that was only loaded
# into the daemon. The engine buildkit can read that tag, and the GitHub
# runner's engine buildkit has no docker exporter. Publish the tag to a
# registry on the host and patch it with a host-network builder, which can
# pull 127.0.0.1 and still has the exporter.
ensure_registry() {
  local ready i state
  state="$(docker inspect -f '{{.State.Running}}' "${registry_name}" 2>/dev/null || true)"
  if [[ "${state}" != "true" ]]; then
    docker rm -f "${registry_name}" >/dev/null 2>&1 || true
    docker run -d --name "${registry_name}" \
      -p "127.0.0.1:${registry_port}:5000" \
      "${registry_image}" >/dev/null
    started_registry=1
  fi
  ready=0
  i=0
  while [[ "${i}" -lt 30 ]]; do
    if curl -fsS "http://127.0.0.1:${registry_port}/v2/" >/dev/null; then
      ready=1
      break
    fi
    i=$((i + 1))
    sleep 1
  done
  if [[ "${ready}" -ne 1 ]]; then
    echo "local registry did not start" >&2
    exit 1
  fi
}

ensure_builder() {
  if docker buildx inspect "${builder_name}" >/dev/null 2>&1; then
    return 0
  fi
  docker buildx create \
    --name "${builder_name}" \
    --driver docker-container \
    --driver-opt network=host >/dev/null
  started_builder=1
  docker buildx inspect --bootstrap "${builder_name}" >/dev/null
}

apply_patch() {
  local image="$1"
  local report="$2"
  local src="127.0.0.1:${registry_port}/copa:src"
  local dst="127.0.0.1:${registry_port}/copa:dst"
  ensure_registry
  ensure_builder
  docker tag "${image}" "${src}"
  docker push "${src}"
  # The builder cannot see this daemon tag. Drop it so the pull is the copy
  # the builder reads.
  docker rmi "${src}" >/dev/null
  "${copa}" patch \
    -i "${src}" \
    -r "${report}" \
    -t "${dst}" \
    --addr "buildx://${builder_name}" \
    --timeout "${COPA_TIMEOUT:-15m}"
  docker image inspect "${dst}" >/dev/null
  docker tag "${dst}" "${image}"
  docker rmi "${dst}" >/dev/null
}

for image in "$@"; do
  docker image inspect "${image}" >/dev/null
  before_report="${work}/reports/before.json"
  scan "${image}" "${before_report}"
  before="$(count_fixable "${before_report}")"
  echo "${image}: ${before} fixable OS vulnerabilities"
  if [[ "${before}" -eq 0 ]]; then
    continue
  fi
  apply_patch "${image}" "${before_report}"
  after_report="${work}/reports/after.json"
  scan "${image}" "${after_report}"
  after="$(count_fixable "${after_report}")"
  echo "${image}: ${after} fixable OS vulnerabilities after patching"
done
