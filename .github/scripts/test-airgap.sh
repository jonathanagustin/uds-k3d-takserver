#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The host stays online to retrieve package archives and run the test tools.
# No application deploy happens until node OUTPUT/FORWARD egress is blocked.
set -euo pipefail
cd "$(dirname "$0")/../.."
state="${RUNNER_TEMP:-/tmp}/tak-airgap-state.json"
firewall=(python3 .github/scripts/node-airgap.py --state "${state}")
restore() { "${firewall[@]}" restore; }
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export AIRGAP_TEST=true

uds run deploy-slim-core --no-progress
uds run create-dev-package --set FLAVOR=upstream --no-progress
uds run fit-runner --no-progress
# Fetch the bundle's Core package archive while the runner is online.
uds run create:test-bundle --no-progress
"${firewall[@]}" block
# API access and the runner's own HTTPS remain usable under the restriction.
uds zarf tools kubectl get --raw /readyz
curl --fail --silent --show-error --max-time 20 https://api.github.com/zen >/dev/null
uds run deploy:test-bundle --with config=bundle/airgap-config.yaml --with options=--force-conflicts --no-progress
uds run setup:keycloak-user --with group=/UDS\ Core/Admin --no-progress
python3 tests/ensure-tak-group.py
python3 tests/ensure-outsider.py
python3 tests/ensure-map-user.py
python3 tests/sso-clients.py
# Includes local DNS, gateway TLS, SSO, CoT, files, CloudTAK and API workflows.
uds run test:all --no-progress
"${firewall[@]}" check
