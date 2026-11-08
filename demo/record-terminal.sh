#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record each terminal chapter with VHS against the running cluster.
# Needs vhs, ttyd, ffmpeg, a Chrome/Chromium, and the JetBrains Mono font.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p demo/out

if command -v k3d >/dev/null 2>&1; then
  k3d kubeconfig merge uds --kubeconfig-merge-default >/dev/null
fi

# The tapes show the released package for this version (DEMO_VERSION,
# default the Release Please version). It is pulled here, before recording,
# so the SBOM and signature checks read a local file and the video does not
# wait on the network. The pull checks the signature too.
export DEMO_VERSION="${DEMO_VERSION:-$(python3 -c 'import json; print(json.load(open(".release-please-manifest.json"))["."])')}"
release_dir="${DEMO_RELEASE_DIR:-/tmp/demo-release}"
rm -rf "${release_dir}"
mkdir -p "${release_dir}" demo/out/shots
# The release workflow's keyless signing identity, as in demo/shell.sh.
RELEASE_WORKFLOW='^https://github\.com/jonathanagustin/(uds-k3d-takserver|uds-takserver)/\.github/workflows/release\.yaml@refs/(tags/v[0-9]+\.[0-9]+\.[0-9]+|heads/main)$'
RELEASE_ISSUER=https://token.actions.githubusercontent.com
uds zarf package pull "oci://ghcr.io/jonathanagustin/uds-k3d-takserver/takserver:${DEMO_VERSION}-upstream" \
  --architecture amd64 --certificate-identity-regexp "${RELEASE_WORKFLOW}" --certificate-oidc-issuer "${RELEASE_ISSUER}" \
  -o "${release_dir}" --no-progress
export DEMO_RELEASE_PACKAGE="${release_dir}/zarf-package-takserver-amd64-${DEMO_VERSION}-upstream.tar.zst"
test -s "${DEMO_RELEASE_PACKAGE}"

# demo/ragged.py turns each hand-written tape into uneven, chunked typing.
# demo/assemble.sh reads the generated tapes to time captions and zooms.
mkdir -p demo/out/tapes
for source in demo/tapes/*.tape; do
  tape="demo/out/tapes/$(basename "${source}")"
  python3 demo/ragged.py "${source}" "${tape}"
  echo "Recording ${tape}"
  vhs "${tape}"
done
