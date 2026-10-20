#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Fail when a private key or Java keystore is in the working tree.
# gitleaks misses empty files. This check does not.
set -euo pipefail

found="$(find . -type f \( -name '*.key' -o -name '*.p12' -o -name '*.jks' \) \
  -not -path './.git/*' \
  -not -path './build/*' \
  -not -path './node_modules/*' \
  -not -path './zarf-sbom/*' \
  -not -path './tests/.playwright/*' \
  -print)"
if [ -n "${found}" ]; then
  printf '%s\n' "${found}" >&2
  echo "Private key or keystore files are not allowed in this tree." >&2
  exit 1
fi
