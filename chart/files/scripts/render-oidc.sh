#!/bin/bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Substitute only ${TAK_OIDC_CLIENT_SECRET}. The group regex ends in $ and
# must be left alone, so envsubst is given that one variable name.
set -euo pipefail

secret_file=/var/run/tak-sso/TAK_OIDC_CLIENT_SECRET
ready=0
for _ in $(seq 1 150); do
  if [ -s "${secret_file}" ]; then
    ready=1
    break
  fi
  sleep 2
done
if [ "${ready}" -ne 1 ]; then
  echo "TAK_OIDC_CLIENT_SECRET was not present" >&2
  exit 1
fi

# XML-escape before envsubst. envsubst inserts the value as text and does
# not expand $ inside it. Do not print the secret.
escaped="$(tr -d '\n' < "${secret_file}" | sed \
  -e 's/&/\&amp;/g' \
  -e 's/</\&lt;/g' \
  -e 's/>/\&gt;/g' \
  -e 's/"/\&quot;/g' \
  -e "s/'/\\&apos;/g")"
export TAK_OIDC_CLIENT_SECRET="${escaped}"
# shellcheck disable=SC2016 # envsubst must see the variable name, not its value.
envsubst '${TAK_OIDC_CLIENT_SECRET}' < /template/CoreConfig.xml > /conf/CoreConfig.xml
# shellcheck disable=SC2016
if grep -q 'secret="${TAK_OIDC_CLIENT_SECRET}"' /conf/CoreConfig.xml; then
  echo "OIDC client secret was not substituted" >&2
  exit 1
fi
chmod 0644 /conf/CoreConfig.xml
echo "CoreConfig OIDC secret substituted"
