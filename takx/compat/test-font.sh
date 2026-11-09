#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
source_dir=${ATAK_SOURCE_DIR:-"${root}/upstream/atak-civ"}
expected=9f6893dd657feacc35ec5de03dad721c2e44170e
[[ $(git -C "${source_dir}" rev-parse HEAD) == "${expected}" ]] || {
  echo 'The font test requires the pinned official ATAK source.' >&2
  exit 1
}
files=()
for name in Font FontMetrics DisplaySettings; do
  files+=("takkernel/port/src/main/java/gov/tak/api/commons/graphics/${name}.java")
done
git -C "${source_dir}" diff --exit-code HEAD -- "${files[@]}" >/dev/null
build=$(mktemp -d)
trap 'rm -rf -- "${build}"' EXIT
inputs=()
for file in "${files[@]}"; do inputs+=("${source_dir}/${file}"); done
javac --release 11 -d "${build}" \
  "${root}/takx/compat/src/main/java/android/graphics/Typeface.java" \
  "${root}/takx/compat/src/main/java/android/graphics/Paint.java" \
  "${inputs[@]}" "${root}/takx/compat/src/test/java/FontCompatibilityTest.java"
java -Djava.awt.headless=true -cp "${build}" FontCompatibilityTest
