#!/bin/sh
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Node accepts one extra CA file. Keep the TAK CA and Core's optional bundle
# together, on a volume mounted read-only by the Node containers.
set -eu

tak_ca="$1"
bundle="$2"
output="$3"
test -s "${tak_ca}"
cat "${tak_ca}" > "${output}"
printf '\n' >> "${output}"
if [ -f "${bundle}" ]; then
  cat "${bundle}" >> "${output}"
  printf '\n' >> "${output}"
fi
chmod 0444 "${output}"
