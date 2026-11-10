#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
support="${TAKX_COMPAT_SUPPORT_ROOT:-${here}}"
if [[ ! -s "${support}/src/main/java/android/net/Uri.java" ]]; then
  echo "Accepted Uri/Parcel prerequisites are required; set TAKX_COMPAT_SUPPORT_ROOT if separate" >&2
  exit 2
fi
work="$(mktemp -d)"
trap 'rm -rf -- "${work}"' EXIT
javac --release 11 -Xlint:all -d "${work}" \
  "${here}"/src/main/java/android/content/*.java \
  "${here}"/src/main/java/android/content/res/*.java \
  "${here}"/src/main/java/android/content/pm/*.java \
  "${support}"/src/main/java/android/net/*.java \
  "${support}/src/main/java/android/os/Parcel.java" \
  "${support}/src/main/java/android/os/Parcelable.java" \
  "${here}"/src/main/java/android/preference/*.java \
  "${here}/src/test/java/DesktopContextTest.java"
java -ea -cp "${work}" DesktopContextTest
