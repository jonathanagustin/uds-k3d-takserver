#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Fail when a UDS Exemption rendered by the chart has no section in
# docs/justifications.md, or when a matcher name is a bare wildcard.
set -euo pipefail

rendered="$(helm template takserver charts/takserver --namespace takserver)"

names="$(awk '
  /^---/ { kind = ""; name = ""; next }
  /^kind: Exemption/ { kind = "Exemption" }
  kind == "Exemption" && /^metadata:/ { inmeta = 1; next }
  inmeta && /^  name:/ { print $2; inmeta = 0 }
' <<< "${rendered}")"

status=0
while read -r name; do
  [[ -z "${name}" ]] && continue
  if ! grep -qx "## ${name}" docs/justifications.md; then
    echo "Exemption ${name} has no '## ${name}' section in docs/justifications.md" >&2
    status=1
  fi
done <<< "${names}"

if grep -Eq '^\s+name: "?\^?\.\*\$?"?\s*$' <<< "${rendered}"; then
  echo "An Exemption matcher name is a bare wildcard" >&2
  status=1
fi
exit "${status}"
