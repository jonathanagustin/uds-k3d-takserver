#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Turn the image tags a job pushed into a checksums file for actions/attest
# (subject-checksums): one "<sha256 hex>  <image name>" line per digest.
#
#   subjects.sh <refs-file> <out-file>
#
# <refs-file> has one <registry>/<name>:<tag> per line. Each contributes the
# digest its tag points to. With INCLUDE_PLATFORMS=true (the default), an
# index also contributes each image manifest in it, which is the digest a
# node pulls for its architecture. BuildKit's attestation manifests
# (platform unknown/unknown) are left out. Prints the number of subjects.
set -euo pipefail

refs="$1"
out="$2"
: > "${out}"

if [[ -s "${refs}" ]]; then
  while IFS= read -r ref; do
    [[ -n "${ref}" ]] || continue
    name="${ref%:*}"
    manifest="$(docker buildx imagetools inspect "${ref}" --format '{{json .Manifest}}')"
    digest="$(jq -r '.digest' <<< "${manifest}")"
    if [[ ! "${digest}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
      echo "No digest for ${ref}" >&2
      exit 1
    fi
    echo "${digest#sha256:}  ${name}" >> "${out}"
    if [[ "${INCLUDE_PLATFORMS:-true}" = "true" ]]; then
      jq -r '.manifests[]? | select((.platform.os // "unknown") != "unknown") | .digest' <<< "${manifest}" \
        | while IFS= read -r child; do
          echo "${child#sha256:}  ${name}"
        done >> "${out}"
    fi
  done < "${refs}"
fi

sort -u -o "${out}" "${out}"
wc -l < "${out}" | tr -d ' '
