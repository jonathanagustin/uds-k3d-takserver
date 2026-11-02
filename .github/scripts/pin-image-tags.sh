#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Point this checkout's TAK, CloudTAK and PostGIS references at the tags keyed
# by this commit's image inputs (build.sh --tag), before CI creates a package.
#
# <version> and <version>-<arch> are written from main only, and another
# branch can build different inputs at any time. <version>-<key> only ever
# holds the image built from one set of inputs, so a package made after this
# runs deploys this commit's TAK, CloudTAK and PostGIS images, not whatever
# was pushed last. Releases do not run this and keep the tags in the files.
#
# Edits the working tree only. Do not commit the result.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "${root}"

cloudtak_version="$(git config -f .gitmodules submodule.upstream/cloudtak.branch)"
cloudtak_tag="$(./.github/container-and-chart/cloudtak/build.sh --tag)"
postgis_version="18-3.6"
postgis_tag="$(./.github/container-and-chart/postgis/build.sh --tag)"

tak_version="$(tr -d '[:space:]' < .github/container-and-chart/docker/version.txt)"
tak_tag="$(./.github/container-and-chart/docker/build.sh --tag)"

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
replace charts/cloudtak/values.yaml "tag: ${cloudtak_version} # cloudtak-version" "tag: ${cloudtak_tag} # cloudtak-version"

replace zarf.yaml "${repo}/postgis:${postgis_version}\"" "${repo}/postgis:${postgis_tag}\""
replace charts/cloudtak/values.yaml "${repo}/postgis:${postgis_version}" "${repo}/postgis:${postgis_tag}"
replace values/common-values.yaml "tag: \"${postgis_version}\"" "tag: \"${postgis_tag}\""

# The six TAK images, plus TAK_IMAGE_TAG wherever a package is created or a
# bundle is deployed, since the Helm values read the tag from that variable.
for name in takserver-api takserver-messaging takserver-config takserver-plugins takserver-database-setup takserver-ignite; do
  replace zarf.yaml "${repo}/${name}:${tak_version}\"" "${repo}/${name}:${tak_tag}\""
done
# zarf.yaml and tasks.yaml each have one default of the plain TAK tag.
replace zarf.yaml "default: ${tak_version}" "default: ${tak_tag}"
replace tasks.yaml "default: ${tak_version}" "default: ${tak_tag}"
replace bundle/uds-config.yaml "TAK_IMAGE_TAG: ${tak_version}" "TAK_IMAGE_TAG: ${tak_tag}"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "TAK images: ${repo}/takserver-*:${tak_tag}"
    echo "CloudTAK image: ${repo}/cloudtak:${cloudtak_tag}"
    echo "PostGIS image: ${repo}/postgis:${postgis_tag}"
  } >> "${GITHUB_STEP_SUMMARY}"
fi
