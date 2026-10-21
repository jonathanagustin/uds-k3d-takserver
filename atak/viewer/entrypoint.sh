#!/bin/sh
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
# Keeps adb connected to the device VM and serves ws-scrcpy plus phone.html.
set -eu
: "${DEVICE:?DEVICE must be host:port of the device adb listener}"
printf '{"device":"%s","player":"%s"}\n' "${DEVICE}" "${PLAYER:-mse}" > /app/dist/public/config.json
(
  while true; do
    adb connect "${DEVICE}" >/dev/null 2>&1 || true
    sleep 10
  done
) &
cd /app/dist
exec node index.js
