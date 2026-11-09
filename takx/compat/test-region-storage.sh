#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build=$(mktemp -d)
trap 'rm -rf -- "${build}"' EXIT
javac --release 11 -sourcepath "${root}/takx/compat/src/main/java" -d "${build}" \
  "${root}/takx/compat/src/main/java/android/graphics/Bitmap.java" \
  "${root}/takx/compat/src/main/java/android/graphics/BitmapEncoder.java" \
  "${root}/takx/compat/src/test/java/android/graphics/BitmapRegionStorageTest.java"
java -Djava.awt.headless=true -cp "${build}" android.graphics.BitmapRegionStorageTest
