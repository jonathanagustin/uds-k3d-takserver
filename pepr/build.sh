#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Builds the admission module and the Helm chart that Zarf packages. The chart
# is generated, not committed: every build creates a new webhook TLS key.
# Pepr needs Node 22.19 or newer. A host with an older Node runs the build
# under one fetched from the npm registry.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

build='npm ci --no-audit --no-fund && npm test && npm run build'

if node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 22 || (a === 22 && b >= 19) ? 0 : 1)' 2>/dev/null; then
  bash -c "${build}"
else
  echo "Node 22.19 or newer is required; using node@22.22.0 from npm" >&2
  npx --yes -p node@22.22.0 -c "${build}"
fi
