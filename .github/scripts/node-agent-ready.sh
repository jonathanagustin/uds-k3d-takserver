#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Read a Velero node-agent log on stdin. Succeed only when a line says the
# controller manager started. Velero 1.18 logs "Starting Controller". Older
# builds logged "Starting controllers". Other startup lines, including
# "Starting workers" and "Starting EventSource", do not count.
node_agent_controllers_started() {
  grep -F -e "Starting Controller" -e "Starting controllers" -q
}
