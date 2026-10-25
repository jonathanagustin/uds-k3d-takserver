#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The API smoke writes the standard-port client's callsign to
# /tmp/tak-stream-uid after that client is listed. When core-logging is
# installed, that callsign has to show up in Loki. Slim has no Loki Service.
set -euo pipefail

root="$(cd "$(dirname "${0}")/.." && pwd)"
cd "${root}"

svcs="$(uds zarf tools kubectl get svc -A -o name 2>/dev/null || true)"
if ! grep -qi 'loki' <<< "${svcs}"; then
  echo "No Loki Service. The client callsign check runs when core-logging is installed."
  exit 0
fi
if [[ ! -f /tmp/tak-stream-uid ]]; then
  echo "Loki is installed but the API smoke did not record a streaming client callsign" >&2
  exit 1
fi
uid="$(tr -d '[:space:]' < /tmp/tak-stream-uid)"
if [[ ! "${uid}" =~ ^[A-Za-z0-9._:-]+$ ]]; then
  echo "streaming client callsign has unexpected characters" >&2
  exit 1
fi
./tests/query-loki.sh \
  --query "{namespace=\"takserver\"} |= \"${uid}\"" \
  --match "${uid}" \
  --attempts 24 \
  --pause 5
echo "Loki returned the streaming client callsign"
