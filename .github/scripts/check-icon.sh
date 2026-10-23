#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Fails when the dev.uds.icon annotation in zarf.yaml is not the base64 of
# assets/icon.svg. Regenerate with:
#   printf 'data:image/svg+xml;base64,%s\n' "$(base64 < assets/icon.svg | tr -d '\n')"
set -euo pipefail

cd "$(dirname "$0")/../.."
want="data:image/svg+xml;base64,$(base64 < assets/icon.svg | tr -d '\n')"
have="$(sed -n 's/^ *dev\.uds\.icon: *//p' zarf.yaml)"
if [[ "${have}" != "${want}" ]]; then
  echo "zarf.yaml dev.uds.icon does not match assets/icon.svg" >&2
  exit 1
fi
echo "dev.uds.icon matches assets/icon.svg"
