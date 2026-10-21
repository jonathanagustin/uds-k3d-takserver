#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Record a web walkthrough in a real Chrome window, address bar and all,
# with demo/record-browser.sh.
#
# usage: demo/record-web.sh [NAME SPEC HOSTS]
#   default: 06-web tour.demo.ts "takserver.uds.dev sso.uds.dev", the TAK
#   web UI. demo/out/NAME.mp4 and demo/out/NAME-events.json.
#   The CloudTAK map: 07-map map.demo.ts "map.uds.dev sso.uds.dev"
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
name="${1:-06-web}"
spec="${2:-tour.demo.ts}"
hosts="${3:-takserver.uds.dev sso.uds.dev}"
mkdir -p demo/out

# The demo signs in as its own Keycloak user, takuser, with the same groups
# as the test user. The password is generated for this run and never shown:
# the login form masks it and GitHub Actions masks it in the log.
export DEMO_KEYCLOAK_USER="${DEMO_KEYCLOAK_USER:-takuser}"
if [ -z "${DEMO_KEYCLOAK_PASSWORD:-}" ]; then
  DEMO_KEYCLOAK_PASSWORD="Tk7!$(openssl rand -hex 5)@Qz#"
fi
export DEMO_KEYCLOAK_PASSWORD
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  echo "::add-mask::${DEMO_KEYCLOAK_PASSWORD}"
fi
python3 demo/keycloak-user.py

# Chrome trusts the deploy-time TAK CA through its NSS store, along with
# the self-signed root at the top of each tenant gateway certificate chain.
# The UDS Core dev certificate for *.uds.dev chains to a public root, so
# that one is already in Chrome's root store. A private gateway CA would
# not be, and is trusted the same way.
kubectl() { uds zarf tools kubectl "$@"; }
cas="demo/out/trust"
rm -rf "${cas}"
mkdir -p "${cas}"
kubectl get configmap cert-migration -n takserver -o jsonpath='{.binaryData.ca\.pem}' | base64 -d > "${cas}/tak-ca.pem"
for secret in $(kubectl get secret -n istio-tenant-gateway -o jsonpath='{range .items[?(@.type=="kubernetes.io/tls")]}{.metadata.name}{" "}{end}'); do
  kubectl get secret "${secret}" -n istio-tenant-gateway -o jsonpath='{.data.tls\.crt}' | base64 -d \
    | awk '/-----BEGIN CERTIFICATE-----/ { n++; cert = "" } { cert = cert $0 "\n" } /-----END CERTIFICATE-----/ { last = cert } END { printf "%s", last }' > "${cas}/top.pem"
  if [ "$(openssl x509 -in "${cas}/top.pem" -noout -subject -nameopt RFC2253 | cut -d= -f2-)" = "$(openssl x509 -in "${cas}/top.pem" -noout -issuer -nameopt RFC2253 | cut -d= -f2-)" ]; then
    mv "${cas}/top.pem" "${cas}/gateway-${secret}.pem"
  fi
  rm -f "${cas}/top.pem"
done
for file in "${cas}"/*.pem; do
  echo "${file}: $(openssl x509 -in "${file}" -noout -subject)"
done

TAK_SSO_URL="${TAK_SSO_URL:-https://takserver.uds.dev/}" \
  CLOUDTAK_URL="${CLOUDTAK_URL:-https://map.uds.dev/}" \
  KEYCLOAK_USER="${DEMO_KEYCLOAK_USER}" \
  KEYCLOAK_PASSWORD="${DEMO_KEYCLOAK_PASSWORD}" \
  DEMO_HOSTS="${hosts}" \
  DEMO_TRUST_CAS="$(echo "${cas}"/*.pem)" \
  demo/record-browser.sh "${name}" "${spec}"
