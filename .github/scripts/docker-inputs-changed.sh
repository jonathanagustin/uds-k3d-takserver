#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Exit 0 when the latest commit touches the Docker build inputs.
# Exit 1 when it does not. Callers skip the image wait on exit 1.
# The container workflow rebuilds only for that commit, so a later commit
# that leaves this directory alone can use the tags already published.
set -euo pipefail

path=".github/container-and-chart/docker"
head="${HEAD_SHA:-${GITHUB_SHA:-HEAD}}"

if ! git cat-file -e "${head}^{commit}" 2>/dev/null; then
  if ! git fetch --no-tags --depth=2 origin "${head}"; then
    echo "Could not fetch ${head}. Treating Docker inputs as changed."
    exit 0
  fi
fi

if ! git rev-parse --verify "${head}~1" >/dev/null 2>&1; then
  if ! git fetch --no-tags --deepen=2 origin; then
    echo "No parent for ${head}. Treating Docker inputs as changed."
    exit 0
  fi
fi

if ! git rev-parse --verify "${head}~1" >/dev/null 2>&1; then
  echo "No parent for ${head}. Treating Docker inputs as changed."
  exit 0
fi

if git diff --quiet "${head}~1" "${head}" -- "${path}"; then
  echo "Docker inputs are unchanged."
  exit 1
fi

git diff --name-only "${head}~1" "${head}" -- "${path}"
exit 0
