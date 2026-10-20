#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Deploy the slim UDS Core checkpoint. A restored package tarball skips the
# OCI pull. The first run pulls k3d-core-slim-dev into the cache directory.
set -euo pipefail

version="${SLIM_CORE_VERSION:-1.15.0}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
out="${SLIM_PACKAGE_DIR:-${root}/.cache/k3d-core-slim-dev}"
ref="oci://ghcr.io/defenseunicorns/dev/uds/checkpoints/k3d-core-slim-dev:${version}"

mkdir -p "${out}"
# uds bundles zarf and does not leave ./zarf in the repo until a zarf
# command has already run. `uds zarf` is that command.
if [ -x "${root}/zarf" ]; then
  zarf=("${root}/zarf")
elif command -v zarf >/dev/null 2>&1; then
  zarf=(zarf)
elif command -v uds >/dev/null 2>&1; then
  zarf=(uds zarf)
else
  echo "zarf is not available. Run this from uds so the CLI is present." >&2
  exit 1
fi

shopt -s nullglob
files=("${out}"/zarf-package-k3d-core-slim-dev-*.tar.zst)
if [ "${#files[@]}" -eq 0 ]; then
  echo "Pulling ${ref}"
  "${zarf[@]}" package pull "${ref}" --output-directory "${out}"
  files=("${out}"/zarf-package-k3d-core-slim-dev-*.tar.zst)
fi
shopt -u nullglob

if [ "${#files[@]}" -eq 0 ]; then
  echo "No k3d-core-slim-dev package in ${out}" >&2
  exit 1
fi

echo "Deploying ${files[0]}"
"${zarf[@]}" package deploy "${files[0]}" --confirm --features values=true
