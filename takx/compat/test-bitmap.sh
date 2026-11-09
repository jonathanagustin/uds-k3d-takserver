#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
source_dir=${ATAK_SOURCE_DIR:-"${root}/upstream/atak-civ"}
extra=${TAKX_COMPAT_EXTRA_SOURCE_DIR:-}
patch_file=${TAKX_BITMAP_PATCH:-"${root}/takx/patches/0001-kernel-remove-unused-colorfilter-import.patch"}
expected=9f6893dd657feacc35ec5de03dad721c2e44170e
expected_patch=dfafe9c5c670e4a2d62194ac1d6722e1b77b4e94d0d9ec494af6193c88cea2dc
actual_patch=$(sha256sum -- "${patch_file}")
[[ ${actual_patch%% *} == "${expected_patch}" ]] || {
  echo 'Bitmap tests require the reviewed unused-import patch.' >&2
  exit 1
}
[[ $(git -C "${source_dir}" rev-parse HEAD) == "${expected}" ]] || {
  echo 'Bitmap tests require the pinned official ATAK source.' >&2
  exit 1
}
files=(
  takkernel/engine/src/main/java/com/atakmap/util/ResourcePool.java
  takkernel/port/src/main/java/gov/tak/api/commons/graphics/Bitmap.java
  takkernel/port/src/main/java/gov/tak/api/commons/graphics/BitmapFactory.java
  takkernel/port/src/main/java/gov/tak/api/commons/graphics/ColorBlendMode.java
  takkernel/port/src/main/java/gov/tak/api/marshal/IMarshal.java
  takkernel/port/src/main/java/gov/tak/api/marshal/IMarshalService.java
  takkernel/port/src/main/java/gov/tak/platform/marshal/MarshalManager.java
  takkernel/port/src/main/java/gov/tak/platform/marshal/MarshalService.java
  takkernel/port/src/main/java/gov/tak/platform/marshal/PlatformMarshalsBase.java
  takkernel/port/src/main/java/gov/tak/platform/marshal/ColorBlendModeMarshal.java
  takkernel/port/src/jre/java/gov/tak/api/commons/graphics/BitmapMarshal.java
  takkernel/port/src/jre/java/gov/tak/platform/marshal/PlatformMarshals.java
)
git -C "${source_dir}" diff --exit-code HEAD -- "${files[@]}" >/dev/null
build=$(mktemp -d)
trap 'rm -rf -- "${build}"' EXIT
inputs=()
for file in "${files[@]}"; do
  mkdir -p "${build}/source/$(dirname -- "${file}")"
  cp -- "${source_dir}/${file}" "${build}/source/${file}"
  inputs+=("${build}/source/${file}")
done
# Apply the reviewed unused-import patch only to the disposable source copy.
patch --batch --fuzz=0 --dry-run -d "${build}/source" -p1 < "${patch_file}"
patch --batch --fuzz=0 -d "${build}/source" -p1 < "${patch_file}"
compat=("${root}/takx/compat/src/main/java/android/graphics/Bitmap.java"
        "${root}/takx/compat/src/main/java/android/graphics/BitmapFactory.java")
if [[ -n "${extra}" ]]; then
  compat+=("${extra}/android/graphics/PorterDuff.java")
else
  compat+=("${root}/takx/compat/src/main/java/android/graphics/PorterDuff.java")
fi
javac --release 11 -d "${build}/classes" "${compat[@]}" "${inputs[@]}" \
  "${root}/takx/compat/src/test/java/gov/tak/api/commons/graphics/BitmapCompatibilityTest.java"
java -Djava.awt.headless=true -cp "${build}/classes" gov.tak.api.commons.graphics.BitmapCompatibilityTest
