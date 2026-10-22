#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Deploys the demo with the same commands `uds run demo-deploy` runs through
# its tasks, printing each one before it runs, so the Demo Video workflow can
# record the real deployment (asciinema) for the opening chapter:
#   1. UDS Core (slim) on a new k3d cluster
#   2. zarf package create
#   3. uds create bundle
#   4. uds deploy
# demo/render-cast.py splits the recording at the printed prompts.
# Runner housekeeping (fit-runner) and the post-deploy setup run outside the
# recording.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
arch="${UDS_ARCH:-amd64}"
flavor="${FLAVOR:-upstream}"
core="${SLIM_CORE_VERSION:-1.15.0}"
var() { uds zarf tools yq ".variables[] | select(.name == \"$1\") | .default" tasks.yaml; }
domain="$(var DOMAIN)"
tak_tag="$(var TAK_IMAGE_TAG)"
log="${DEPLOY_LOG:-/tmp/demo-deploy-extra.log}"
# Extra create flags, as for `uds run create-dev-package` (e.g. a registry override).
read -ra create_options <<< "${CREATE_OPTIONS:-}"

prompt() { printf '\n\033[38;5;141muds-k3d-takserver\033[0m \033[38;5;245m$\033[0m %s\n' "$*"; }
run() {
  prompt "$*"
  "$@"
}

run uds zarf package deploy "oci://ghcr.io/defenseunicorns/dev/uds/checkpoints/k3d-core-slim-dev:${core}" \
  --architecture "${arch}" --confirm --features values=true --no-progress
./.github/scripts/fit-runner.sh >> "${log}" 2>&1

run uds zarf package create . --confirm --architecture "${arch}" --flavor "${flavor}" --features values=true \
  --skip-sbom --set DOMAIN="${domain}" --set TAK_IMAGE_TAG="${tak_tag}" --no-progress "${create_options[@]}"

# The test bundle refers to the package without its flavor suffix
# (uds-common create:test-bundle does the same copy).
for pkg in zarf-package-*-"${arch}"-*-"${flavor}".tar.zst; do
  cp "${pkg}" "${pkg%-"${flavor}".tar.zst}.tar.zst"
done
run uds create bundle --confirm --architecture "${arch}" --no-progress

name="$(uds zarf tools yq -r .metadata.name bundle/uds-bundle.yaml)"
version="$(uds zarf tools yq -r .metadata.version bundle/uds-bundle.yaml)"
export UDS_CONFIG=bundle/uds-config.yaml
run uds deploy "bundle/uds-bundle-${name}-${arch}-${version}.tar.zst" --confirm --no-progress --force-conflicts
prompt ""
