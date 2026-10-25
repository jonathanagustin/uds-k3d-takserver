#!/bin/bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Substitute ${TAK_OIDC_CLIENT_SECRET} and ${TAK_KEYSTORE_PASS}. The group
# regex ends in $ and must be left alone, so envsubst is given those names.
# Do not print either value.
set -euo pipefail

xml_escape() {
  tr -d '\n' | sed \
    -e 's/&/\&amp;/g' \
    -e 's/</\&lt;/g' \
    -e 's/>/\&gt;/g' \
    -e 's/"/\&quot;/g' \
    -e "s/'/\\&apos;/g"
}

wait_for() {
  local path="$1"
  local _i
  for _i in $(seq 1 150); do
    if [[ -s "${path}" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "${path} was not present" >&2
  return 1
}

wait_for /var/run/tak-sso/TAK_OIDC_CLIENT_SECRET
wait_for /var/run/tak-keystore/CAPASS

TAK_OIDC_CLIENT_SECRET="$(xml_escape < /var/run/tak-sso/TAK_OIDC_CLIENT_SECRET)"
TAK_KEYSTORE_PASS="$(xml_escape < /var/run/tak-keystore/CAPASS)"
export TAK_OIDC_CLIENT_SECRET TAK_KEYSTORE_PASS
# shellcheck disable=SC2016 # envsubst must see the names, not the values.
envsubst '${TAK_OIDC_CLIENT_SECRET}${TAK_KEYSTORE_PASS}' < /template/CoreConfig.xml > /conf/CoreConfig.xml
# shellcheck disable=SC2016
if grep -q '${TAK_OIDC_CLIENT_SECRET}' /conf/CoreConfig.xml \
  || grep -q '${TAK_KEYSTORE_PASS}' /conf/CoreConfig.xml; then
  echo "CoreConfig still has an unsubstituted secret" >&2
  exit 1
fi
chmod 0644 /conf/CoreConfig.xml
echo "CoreConfig secrets substituted"
