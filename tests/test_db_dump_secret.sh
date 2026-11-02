#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# The restore helper reads dump.sql.gz, falls back to the old dump.sql, and
# fails when a Secret has neither. A stub stands in for kubectl.
set -euo pipefail

root="$(cd "$(dirname "${0}")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

sql='CREATE TABLE uds_restore_marker (note text);'
gz_b64="$(printf '%s\n' "${sql}" | gzip -9 -n -c | base64 -w 0)"
plain_b64="$(printf '%s\n' "${sql}" | base64 -w 0)"

# Secrets: new (gz only), old (plain only), both (gz wins), empty.
cat > "${work}/kubectl" <<STUB
#!/usr/bin/env bash
name="\$3"
key="\$7"
case "\${name}:\${key}" in
  new:*sql\\\\.gz*) printf '%s' '${gz_b64}' ;;
  old:*sql\\\\.gz*) ;;
  old:*) printf '%s' '${plain_b64}' ;;
  both:*sql\\\\.gz*) printf '%s' '${gz_b64}' ;;
  both:*) printf '%s' 'bm90IHRoaXMK' ;;
  *) ;;
esac
STUB
chmod +x "${work}/kubectl"
export KUBECTL="${work}/kubectl"

for name in new old both; do
  got="$("${root}/tests/db-dump-secret.sh" takserver "${name}" 2>/dev/null)"
  if [[ "${got}" != "${sql}" ]]; then
    echo "${name}: got '${got}'" >&2
    exit 1
  fi
done
if "${root}/tests/db-dump-secret.sh" takserver empty >/dev/null 2>&1; then
  echo "empty: a Secret with no dump key did not fail" >&2
  exit 1
fi
echo "db-dump-secret: gz, plain fallback, gz preferred, and missing all behave"
