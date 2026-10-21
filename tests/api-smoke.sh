#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Marti API smoke test. uds run test:all calls this after install and after upgrade.
#
# 8443 (passthrough, mTLS) uses the deploy-time admin certificate.
# 8447 (tenant gateway) uses a Keycloak access token for the test user. The
# token comes from TAK's authorization-code flow: GET /login/auth, post the
# Keycloak form, read the access_token cookie. There is no second client.
# TAK 5.7 has no /Marti/api/whoami. Identity is /Marti/api/util/user/roles,
# /Marti/api/util/isAdmin, and /Marti/api/groups/all. The script still requests
# /Marti/api/whoami and records a 404.
# 8446 (passthrough) enrolls a client certificate and serves the OIDC document.
# 8089 (passthrough) must accept a stream with that certificate and reject a
# client that presents none.
#
# Each check prints PASS or FAIL. The last line is the count. Exit status is
# non-zero when any check fails.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
passes=0
failures=0

cleanup() {
  rm -rf "${work}"
}
trap cleanup EXIT

pass() {
  printf 'PASS %s\n' "$*"
  passes=$((passes + 1))
}

fail() {
  printf 'FAIL %s\n' "$*"
  failures=$((failures + 1))
}

finish() {
  printf 'api-smoke: %s passed, %s failed\n' "${passes}" "${failures}"
  if [ "${failures}" -ne 0 ]; then
    exit 1
  fi
}

gw_port="18443"
if [ -f /tmp/tak-gateway-port ]; then
  gw_port="$(tr -d '[:space:]' < /tmp/tak-gateway-port)"
fi

tenant="${TAK_SSO_URL:-https://takserver.uds.dev/}"
case "${tenant}" in
  */) ;;
  *) tenant="${tenant}/" ;;
esac
api8446="${TAK_HTTPS_URL:-https://takserver.uds.dev:${gw_port}/}"
api8443="${TAK_CERT_URL:-https://takserver-api.uds.dev:${gw_port}/}"
case "${api8446}" in
  */) ;;
  *) api8446="${api8446}/" ;;
esac
case "${api8443}" in
  */) ;;
  *) api8443="${api8443}/" ;;
esac

user_name="${KEYCLOAK_USER:-doug}"
user_pass="${KEYCLOAK_PASSWORD:-unicorn123!@#UN}"
expected_version="${TAK_VERSION:-5.7}"

cert_dir="$("${script_dir}/extract-certs.sh")"
admin_cert="${TAK_CLIENT_CERT:-${cert_dir}/admin.pem}"
admin_key="${TAK_CLIENT_KEY:-${cert_dir}/admin.key}"
admin_pass="${TAK_CLIENT_KEY_PASSPHRASE:-atakatak}"

# request <body-file> -- curl args
# Sets REPLY_CODE. A transport error is code 000.
request() {
  local dest="$1"
  shift
  local code
  if code="$(curl -k -sS --max-time 40 -o "${dest}" -w "%{http_code}" "$@" 2>"${work}/curl.err")"; then
    REPLY_CODE="${code}"
  else
    REPLY_CODE="000"
  fi
}

show_err() {
  if [ -s "${work}/curl.err" ]; then
    sed 's/^/  /' "${work}/curl.err" >&2 || true
  fi
}

expect_ok() {
  local name="$1"
  local code="$2"
  local needle="$3"
  local body="$4"
  if [ "${code}" != "200" ] && [ "${code}" != "201" ]; then
    fail "${name} HTTP ${code}"
    show_err
    if [ -s "${body}" ]; then
      sed 's/^/  /' "${body}" | head -n 20 >&2 || true
    fi
    return 0
  fi
  if [ -n "${needle}" ] && ! grep -q "${needle}" "${body}"; then
    fail "${name} HTTP ${code} missing ${needle}"
    sed 's/^/  /' "${body}" | head -n 20 >&2 || true
    return 0
  fi
  pass "${name} HTTP ${code}"
}

expect_rejected() {
  local name="$1"
  local code="$2"
  case "${code}" in
    000 | 401 | 403)
      pass "${name} rejected (${code})"
      ;;
    301 | 302 | 303 | 307 | 308)
      pass "${name} redirected (${code})"
      ;;
    *)
      fail "${name} was not rejected (HTTP ${code})"
      show_err
      ;;
  esac
}

mtls=(--cert "${admin_cert}" --key "${admin_key}" --pass "${admin_pass}")

printf 'api-smoke gateway port %s\n' "${gw_port}"

request "${work}/ver" "${mtls[@]}" "${api8443}Marti/api/version"
expect_ok "8443 GET /Marti/api/version" "${REPLY_CODE}" "${expected_version}" "${work}/ver"

request "${work}/groups" "${mtls[@]}" "${api8443}Marti/api/groups/all"
expect_ok "8443 GET /Marti/api/groups/all" "${REPLY_CODE}" "" "${work}/groups"

request "${work}/contacts" "${mtls[@]}" "${api8443}Marti/api/contacts/all"
expect_ok "8443 GET /Marti/api/contacts/all" "${REPLY_CODE}" "" "${work}/contacts"

mission="udssmokemission$(date +%s)"
request "${work}/mission-create" -X PUT "${mtls[@]}" \
  "${api8443}Marti/api/missions/${mission}?creatorUid=admin&description=api-smoke&tool=public"
expect_ok "8443 PUT mission ${mission}" "${REPLY_CODE}" "${mission}" "${work}/mission-create"

request "${work}/mission-get" "${mtls[@]}" "${api8443}Marti/api/missions/${mission}"
expect_ok "8443 GET mission ${mission}" "${REPLY_CODE}" "${mission}" "${work}/mission-get"

request "${work}/mission-del" -X DELETE "${mtls[@]}" "${api8443}Marti/api/missions/${mission}"
expect_ok "8443 DELETE mission ${mission}" "${REPLY_CODE}" "" "${work}/mission-del"

request "${work}/mission-gone" "${mtls[@]}" "${api8443}Marti/api/missions/${mission}"
# TAK answers 410 Gone for a mission that was deleted. 404 means never created.
if [ "${REPLY_CODE}" = "404" ] || [ "${REPLY_CODE}" = "410" ]; then
  pass "8443 GET mission ${mission} after delete is ${REPLY_CODE}"
else
  fail "8443 GET mission ${mission} after delete is HTTP ${REPLY_CODE}"
fi

for path in "Marti/api/version" "Marti/api/groups/all" "Marti/api/contacts/all" "Marti/api/missions/${mission}"; do
  request "${work}/nocert" "${api8443}${path}"
  expect_rejected "8443 ${path} without a certificate" "${REPLY_CODE}"
done

# Authorization-code login on the tenant gateway. Cookies stay in the jar.
login_jar="${work}/cookies"
login_html="${work}/login.html"
login_url="$(curl -k -sS --max-time 40 -c "${login_jar}" -b "${login_jar}" -L --max-redirs 15 \
  -o "${login_html}" -w "%{url_effective}" -A "uds-tak-api-smoke" "${tenant}login/auth" || true)"

if [ ! -s "${login_html}" ] || ! python3 - "${login_html}" "${login_url}" "${user_name}" "${user_pass}" "${work}/form.tsv" <<'PY'
import html
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin

page, page_url, username, password, dest = sys.argv[1:]
text = open(page, encoding="utf-8", errors="replace").read()

class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = ""
        self.in_form = False
        self.fields = []

    def handle_starttag(self, tag, attrs):
        data = {key: value for key, value in attrs}
        if tag == "form" and not self.action:
            self.in_form = True
            self.action = html.unescape(data.get("action") or "")
        elif tag == "input" and self.in_form:
            name = data.get("name")
            if name:
                self.fields.append((name, data.get("value") or ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False

form = Form()
form.feed(text)
if not form.action:
    match = re.search(r"<form[^>]*action=['\"]([^'\"]+)['\"]", text, re.I)
    if match:
        form.action = html.unescape(match.group(1))
if not form.action:
    sys.stderr.write("Keycloak login form was not found\n")
    open(dest, "w", encoding="utf-8").close()
    sys.exit(0)
action = urljoin(page_url, form.action)
seen = set()
rows = [("action", action)]
for name, value in form.fields:
    if name in ("username", "password"):
        continue
    if name in seen:
        continue
    seen.add(name)
    rows.append((name, value))
rows.append(("username", username))
rows.append(("password", password))
with open(dest, "w", encoding="utf-8") as handle:
    for name, value in rows:
        handle.write(name + "\t" + value.replace("\t", " ") + "\n")
PY
then
  fail "8447 Keycloak login form"
  : > "${work}/form.tsv"
fi

action=""
post_args=()
while IFS="$(printf '\t')" read -r field value; do
  if [ "${field}" = "action" ]; then
    action="${value}"
    continue
  fi
  post_args+=(--data-urlencode "${field}=${value}")
done < "${work}/form.tsv"

if [ -z "${action}" ]; then
  fail "8447 Keycloak login form"
else
  after="${work}/after-login.html"
  after_url="$(curl -k -sS --max-time 40 -c "${login_jar}" -b "${login_jar}" -L --max-redirs 20 \
    -o "${after}" -w "%{url_effective}" -A "uds-tak-api-smoke" "${post_args[@]}" "${action}" || true)"
  printf 'login landed on %s\n' "${after_url}"
fi

token="$(python3 - "${login_jar}" <<'PY'
import sys
jar = sys.argv[1]
parts = []
for raw in open(jar, encoding="utf-8", errors="replace"):
    line = raw.rstrip("\n")
    if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
        continue
    if line.startswith("#HttpOnly_"):
        line = line[len("#HttpOnly_"):]
    fields = line.split("\t")
    if len(fields) < 7:
        continue
    name, value = fields[5], fields[6]
    if name.startswith("access_token"):
        parts.append((name, value))
parts.sort()
sys.stdout.write("".join(value for _, value in parts))
PY
)"

if [ "${#token}" -lt 20 ]; then
  fail "8447 authorization-code token"
  if [ -s "${work}/after-login.html" ]; then
    python3 - "${work}/after-login.html" <<'PY' >&2 || true
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
title = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
if title:
    print("  login page title:", " ".join(title.group(1).split())[:200])
PY
  fi
else
  pass "8447 authorization-code token"
fi

# The gateway re-encrypts to 8447, so TAK sees a secure request and marks its
# cookies Secure. curl's cookie jar has TRUE in the fourth field for those.
insecure_cookies="$(python3 - "${login_jar}" <<'PY'
import sys
bad = []
for raw in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = raw.rstrip("\n")
    if line.startswith("#HttpOnly_"):
        line = line[len("#HttpOnly_"):]
    elif not line or line.startswith("#"):
        continue
    fields = line.split("\t")
    if len(fields) < 7 or not fields[0].lstrip(".").startswith("takserver."):
        continue
    if fields[3] != "TRUE":
        bad.append(fields[5])
print(" ".join(sorted(set(bad))))
PY
)"
if [ -n "${insecure_cookies}" ]; then
  fail "8447 cookies without Secure: ${insecure_cookies}"
else
  pass "8447 cookies from TAK are Secure"
fi

auth=(-H "Authorization: Bearer ${token}")

if [ "${#token}" -ge 20 ]; then
  if ! python3 - "${token}" "${work}/claims" <<'PY'
import base64, json, sys
token, dest = sys.argv[1:]
pieces = token.split(".")
if len(pieces) < 2:
    sys.stderr.write("access token is not a JWT\n")
    sys.exit(1)
payload = pieces[1]
payload += "=" * (-len(payload) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
name = str(claims.get("preferred_username", ""))
groups = claims.get("groups") or []
if not isinstance(groups, list):
    groups = [str(groups)]
with open(dest, "w", encoding="utf-8") as handle:
    handle.write(name + "\n")
    for item in groups:
        handle.write(str(item) + "\n")
PY
  then
    fail "8447 token claims"
  else
    claim_name="$(head -n 1 "${work}/claims")"
    if [ "${claim_name}" = "${user_name}" ]; then
      pass "8447 token preferred_username ${claim_name}"
    else
      fail "8447 token preferred_username ${claim_name:-empty}"
    fi
    if grep -q "Operators" "${work}/claims"; then
      pass "8447 token groups include Operators"
    else
      fail "8447 token groups do not include Operators"
    fi
  fi

  request "${work}/tver" "${auth[@]}" "${tenant}Marti/api/version"
  expect_ok "8447 GET /Marti/api/version" "${REPLY_CODE}" "${expected_version}" "${work}/tver"

  request "${work}/troles" "${auth[@]}" "${tenant}Marti/api/util/user/roles"
  expect_ok "8447 GET /Marti/api/util/user/roles" "${REPLY_CODE}" "ROLE_ADMIN" "${work}/troles"

  request "${work}/tadmin" "${auth[@]}" "${tenant}Marti/api/util/isAdmin"
  expect_ok "8447 GET /Marti/api/util/isAdmin" "${REPLY_CODE}" "true" "${work}/tadmin"

  request "${work}/tgroups" "${auth[@]}" "${tenant}Marti/api/groups/all"
  expect_ok "8447 GET /Marti/api/groups/all" "${REPLY_CODE}" "Operators" "${work}/tgroups"

  # The admin UI banner reads this. "true" means no connector is plaintext.
  request "${work}/issecure" "${auth[@]}" "${tenant}Marti/api/security/isSecure"
  if [ "${REPLY_CODE}" = "200" ] && grep -Eq '"data" *: *"true"' "${work}/issecure"; then
    pass "8447 GET /Marti/api/security/isSecure reports no non-secure ports"
  else
    fail "8447 GET /Marti/api/security/isSecure HTTP ${REPLY_CODE}: $(head -c 200 "${work}/issecure" 2>/dev/null)"
  fi

  request "${work}/whoami" "${auth[@]}" "${tenant}Marti/api/whoami"
  if [ "${REPLY_CODE}" = "200" ]; then
    if grep -q "${user_name}" "${work}/whoami" && grep -q "Operators" "${work}/whoami"; then
      pass "8447 GET /Marti/api/whoami shows ${user_name} and Operators"
    else
      fail "8447 GET /Marti/api/whoami HTTP 200 did not show the user and Operators"
    fi
  elif [ "${REPLY_CODE}" = "404" ]; then
    pass "8447 GET /Marti/api/whoami is 404. User ${user_name} is ROLE_ADMIN and groups include Operators"
  else
    fail "8447 GET /Marti/api/whoami HTTP ${REPLY_CODE}"
  fi

  bad="$(python3 - "${token}" <<'PY'
import sys
token = sys.argv[1]
head, body, sig = token.split(".")
# Change a character in the middle. The last base64url character of an RS256
# signature carries unused bits, so changing it can leave the bytes the same.
mid = len(sig) // 2
swap = "A" if sig[mid] != "A" else "B"
sys.stdout.write(head + "." + body + "." + sig[:mid] + swap + sig[mid + 1:])
PY
)"
  request "${work}/bad" -H "Authorization: Bearer ${bad}" "${tenant}Marti/api/version"
  # TAK treats a token it cannot verify like no token and redirects to login
  # (302); 401/403 are also a rejection. Only a 2xx would be a failure.
  if [ "${REPLY_CODE}" = "401" ] || [ "${REPLY_CODE}" = "403" ] || [ "${REPLY_CODE}" = "302" ]; then
    pass "8447 token with a bad signature rejected (${REPLY_CODE})"
  else
    fail "8447 token with a bad signature is HTTP ${REPLY_CODE}"
    show_err
  fi
fi

request "${work}/anon" "${tenant}Marti/api/version"
expect_rejected "8447 GET /Marti/api/version without a token" "${REPLY_CODE}"
request "${work}/anon-groups" "${tenant}Marti/api/groups/all"
expect_rejected "8447 GET /Marti/api/groups/all without a token" "${REPLY_CODE}"

request "${work}/oidc" "${api8446}login/.well-known/openid-configuration"
if [ "${REPLY_CODE}" = "200" ] && grep -q "authorization_endpoint" "${work}/oidc" && grep -q "token_endpoint" "${work}/oidc" && grep -Eq "sso.uds.dev|realms/uds" "${work}/oidc"; then
  pass "8446 GET /login/.well-known/openid-configuration"
  # TAK relays only authorization_endpoint and token_endpoint, so derive the
  # standard certs path from token_endpoint when jwks_uri is not included.
  jwks_uri="$(python3 -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
u = d.get("jwks_uri", "")
t = d.get("token_endpoint", "")
if not u and t.endswith("/token"):
    u = t[: -len("/token")] + "/certs"
print(u)' "${work}/oidc")"
  if [ -z "${jwks_uri}" ]; then
    fail "8446 openid document has no jwks_uri or token_endpoint; keys: $(python3 -c 'import json,sys; print(sorted(json.load(open(sys.argv[1], encoding="utf-8"))))' "${work}/oidc")"
  else
    request "${work}/jwks" "${jwks_uri}"
    if [ "${REPLY_CODE}" = "200" ] && python3 -c 'import json,sys; keys=json.load(open(sys.argv[1], encoding="utf-8")).get("keys") or []; raise SystemExit(0 if keys else 1)' "${work}/jwks"; then
      pass "JWKS has at least one key"
    else
      fail "JWKS HTTP ${REPLY_CODE}"
      show_err
    fi
  fi
else
  fail "8446 GET /login/.well-known/openid-configuration HTTP ${REPLY_CODE}"
  show_err
  if [ -s "${work}/oidc" ]; then
    sed 's/^/  /' "${work}/oidc" | head -n 20 >&2 || true
  fi
fi

if [ "${#token}" -ge 20 ]; then
  openssl req -new -newkey rsa:2048 -nodes \
    -keyout "${work}/client.key" \
    -out "${work}/client.csr" \
    -subj "/CN=${user_name}/O=TAK/OU=UDS" >/dev/null 2>&1
  request "${work}/enroll.json" -X POST "${auth[@]}" \
    -H "Accept: application/json" \
    -H "Content-Type: text/plain" \
    --data-binary @"${work}/client.csr" \
    "${api8446}Marti/api/tls/signClient/v2?clientUid=${user_name}&version=1"
  if [ "${REPLY_CODE}" = "200" ] && grep -q "signedCert" "${work}/enroll.json"; then
    pass "8446 POST /Marti/api/tls/signClient/v2"
    python3 - "${work}/enroll.json" "${work}/client.pem" <<'PY'
import json, sys
src, dest = sys.argv[1:]
body = json.load(open(src, encoding="utf-8"))
cert = body["signedCert"].strip()
# TAK returns the certificate as bare base64 DER; wrap it as PEM.
if "BEGIN CERTIFICATE" not in cert:
    cert = "".join(cert.split())
    cert = "-----BEGIN CERTIFICATE-----\n" + "\n".join(cert[i:i + 64] for i in range(0, len(cert), 64)) + "\n-----END CERTIFICATE-----"
open(dest, "w", encoding="utf-8").write(cert + "\n")
PY
    subject="$(openssl x509 -in "${work}/client.pem" -noout -subject)"
    if grep -q "CN[[:space:]]*=[[:space:]]*${user_name}" <<< "${subject}"; then
      pass "8446 enrolled certificate subject ${subject}"
    else
      fail "8446 enrolled certificate subject ${subject}"
    fi
    # TAK closes the stream right after the handshake when it cannot
    # authenticate the certificate. For a certificate enrolled with a bearer
    # token that means validating the token against the Keycloak keys from
    # the messaging pod. Hold stdin open and require the stream to still be
    # up when timeout ends it (exit 124).
    stream_rc=0
    stream="$({ sleep 15; } | timeout 8 openssl s_client -brief -connect "127.0.0.1:${gw_port}" \
      -servername takserver-stream.uds.dev \
      -cert "${work}/client.pem" -key "${work}/client.key" 2>&1)" || stream_rc=$?
    if grep -q "CONNECTION ESTABLISHED" <<< "${stream}" && [ "${stream_rc}" = "124" ]; then
      pass "8089 TLS with the enrolled certificate, stream still open after 8s"
    else
      fail "8089 stream with the enrolled certificate (openssl exit ${stream_rc}; TAK closed it if not 124)"
      printf '%s\n' "${stream}" | head -n 20 >&2 || true
    fi
  else
    fail "8446 POST /Marti/api/tls/signClient/v2 HTTP ${REPLY_CODE}"
    show_err
    if [ -s "${work}/enroll.json" ]; then
      sed 's/^/  /' "${work}/enroll.json" | head -n 20 >&2 || true
    fi
  fi
fi

# TLS 1.3 finishes the client side of the handshake before the server checks
# the client certificate, so CONNECTION ESTABLISHED does not mean it was
# accepted. Keep stdin open and require the server's alert.
bare="$({ printf 'GET / HTTP/1.0\r\n\r\n'; sleep 3; } |
  timeout 20 openssl s_client -brief -connect "127.0.0.1:${gw_port}" \
  -servername takserver-stream.uds.dev 2>&1 || true)"
if grep -Eiq 'certificate required|alert number 11[0-9]|bad certificate|handshake failure|unknown ca' <<< "${bare}"; then
  pass "8089 rejected TLS with no client certificate"
else
  fail "8089 did not reject TLS with no client certificate"
  printf '%s\n' "${bare}" | head -n 20 >&2 || true
fi

finish
