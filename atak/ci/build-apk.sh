#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Builds atak/apk/Dockerfile one stage at a time, so each finished stage is
# written to the registry cache even when a later stage fails. The APK lands
# in ./out. CACHE is the cache image (without tag).
set -euo pipefail
CACHE="${CACHE:?registry cache image}"
start=$(date +%s)
for target in toolchain ttp deps cesium apk; do
  out=(--output type=cacheonly)
  if [ "${target}" = apk ]; then
    out=(--output "type=local,dest=out")
  fi
  docker buildx build -f atak/apk/Dockerfile --target "${target}" \
    --cache-from "type=registry,ref=${CACHE}:atak-apk-ttp" \
    --cache-from "type=registry,ref=${CACHE}:atak-apk-deps" \
    --cache-from "type=registry,ref=${CACHE}:atak-apk-cesium" \
    --cache-from "type=registry,ref=${CACHE}:atak-apk-apk" \
    --cache-to "type=registry,ref=${CACHE}:atak-apk-${target},mode=max,image-manifest=true,oci-mediatypes=true,ignore-error=true" \
    "${out[@]}" .
  echo "${target} done after $(($(date +%s) - start))s"
done
ls -la out
