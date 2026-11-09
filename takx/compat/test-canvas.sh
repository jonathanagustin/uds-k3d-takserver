#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$(mktemp -d)
trap 'rm -rf -- "${build}"' EXIT
sources=(Bitmap BitmapEncoder BitmapFactory Canvas Paint Typeface Rect RectF)
inputs=()
for source in "${sources[@]}"; do
  inputs+=("${root}/takx/compat/src/main/java/android/graphics/${source}.java")
done
javac --release 11 -d "${build}" "${inputs[@]}" \
  "${root}/takx/compat/src/test/java/gov/tak/api/commons/graphics/CanvasCompatibilityTest.java"
java -Djava.awt.headless=true -cp "${build}" gov.tak.api.commons.graphics.CanvasCompatibilityTest
