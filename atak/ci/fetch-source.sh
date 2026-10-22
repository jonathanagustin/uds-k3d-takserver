#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
#
# Check out the ATAK-CIV submodule and the LFS files the Android build reads.
# Every workflow that builds the APK uses this script, so they all send the
# same build context and share the registry layer cache. A different set of
# LFS files changes the ttp layer and forces a cold build of about 60 minutes.
set -euo pipefail

git submodule update --init --depth 1 upstream/atak-civ
cd upstream/atak-civ
git lfs install --local
git lfs pull --exclude="takthirdparty/distfiles/pdfium/win*,takthirdparty/distfiles/pdfium/mac*,takthirdparty/distfiles/mrsid/win*,takthirdparty/distfiles/mrsid/ios*,takthirdparty/distfiles/mrsid/mac*"
du -sh .
