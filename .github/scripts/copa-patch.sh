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

for image in "$@"; do
  docker image inspect "${image}" >/dev/null
  before_report="${work}/reports/before.json"
  scan "${image}" "${before_report}"
  before="$(count_fixable "${before_report}")"
  echo "${image}: ${before} fixable OS vulnerabilities"
  if [[ "${before}" -eq 0 ]]; then
    continue
  fi
  # setup-buildx-action leaves a docker-container builder current. Copa
  # uses that builder when it does not stay on the engine, and a container
  # builder cannot read an image that was only loaded into the daemon.
  # docker:// is the engine's buildkit, which can.
  "${copa}" patch \
    -i "${image}" \
    -r "${before_report}" \
    -t "${image}" \
    --addr docker:// \
    --timeout "${COPA_TIMEOUT:-15m}"
  after_report="${work}/reports/after.json"
  scan "${image}" "${after_report}"
  after="$(count_fixable "${after_report}")"
  echo "${image}: ${after} fixable OS vulnerabilities after patching"
done
