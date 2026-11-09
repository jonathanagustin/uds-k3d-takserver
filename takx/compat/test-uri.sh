#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf -- "${work}"' EXIT
javac --release 11 -Xlint:all -d "${work}" \
  "${here}"/src/main/java/android/net/*.java \
  "${here}"/src/main/java/android/os/*.java \
  "${here}/src/test/java/UriCompatibilityTest.java" \
  "${here}/src/test/java/UriParcelCompatibilityTest.java"
java -ea -cp "${work}" android.net.UriCompatibilityTest
java -ea -cp "${work}" android.net.UriParcelCompatibilityTest
