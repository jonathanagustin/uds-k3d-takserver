#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Point this checkout's CloudTAK and PostGIS references at the tags keyed by
# this commit's image inputs (build.sh --tag), before CI creates a package.
#
# <version> and <version>-<arch> are written from main only, and another
# branch can build different inputs at any time. <version>-<key> only ever
# holds the image built from one set of inputs, so a package made after this
# runs deploys this commit's CloudTAK and PostGIS, not whatever was pushed
# last. Releases do not run this and keep the tags in the files.
#
# Edits the working tree only. Do not commit the result.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "${root}"

cloudtak_version="$(git config -f .gitmodules submodule.upstream/cloudtak.branch)"
cloudtak_tag="$(./.github/container-and-chart/cloudtak/build.sh --tag)"
postgis_version="15-3.4"
postgis_tag="$(./.github/container-and-chart/postgis/build.sh --tag)"

repo="ghcr.io/jonathanagustin/uds-k3d-takserver"

# Replace a literal string in a file and fail if it is not there, so a moved
# reference cannot be silently left on the mutable tag.
replace() {
  local file="$1" old="$2" new="$3"
  python3 - "${file}" "${old}" "${new}" <<'PY'
import sys
path, old, new = sys.argv[1:]
text = open(path, encoding="utf-8").read()
if old not in text:
    sys.exit(f"{path}: '{old}' not found")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
PY
  echo "${file}: ${old} -> ${new}"
}

replace zarf.yaml "${repo}/cloudtak:${cloudtak_version}\"" "${repo}/cloudtak:${cloudtak_tag}\""
replace cloudtak/chart/values.yaml "tag: ${cloudtak_version} # cloudtak-version" "tag: ${cloudtak_tag} # cloudtak-version"

replace zarf.yaml "${repo}/postgis:${postgis_version}\"" "${repo}/postgis:${postgis_tag}\""
replace cloudtak/chart/values.yaml "${repo}/postgis:${postgis_version}" "${repo}/postgis:${postgis_tag}"
replace values/common-values.yaml "tag: \"${postgis_version}\"" "tag: \"${postgis_tag}\""

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "CloudTAK image: ${repo}/cloudtak:${cloudtak_tag}"
    echo "PostGIS image: ${repo}/postgis:${postgis_tag}"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
