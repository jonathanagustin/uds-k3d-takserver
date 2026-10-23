#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Verify every subject in a checksums file the way a user would: gh
# attestation verify with this repository's owner and the workflow running
# this job as the signer, and the subject digest in the verified statement.
#
#   verify.sh <checksums-file>
set -euo pipefail

workflow_ref="${GITHUB_WORKFLOW_REF:?run this in GitHub Actions}"
owner="${GITHUB_REPOSITORY_OWNER:?run this in GitHub Actions}"
signer="${workflow_ref%@*}"
while read -r hex name; do
  gh attestation verify "oci://${name}@sha256:${hex}" \
      --owner "${owner}" \
      --signer-workflow "${signer}" \
      --format json \
    | jq -e --arg d "${hex}" \
      '[.[].verificationResult.statement.subject[]?.digest.sha256] | index($d) != null' > /dev/null
  echo "Verified ${name}@sha256:${hex} (signer ${signer})"
done < "$1"
