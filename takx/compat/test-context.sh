#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf -- "${work}"' EXIT
javac --release 17 -Xlint:all -d "${work}" \
  "${here}"/src/main/java/android/content/*.java \
  "${here}"/src/main/java/android/content/res/*.java \
  "${here}"/src/main/java/android/preference/*.java \
  "${here}/src/test/java/DesktopContextTest.java"
java -ea -cp "${work}" DesktopContextTest
