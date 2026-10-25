#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Checks the admission-time render of the OIDC client secret. The
# takserver-oidc module adds an init container to every TAK pod when the pod
# is created. Init containers cannot be added to a running pod, so a pod that
# has render-oidc has had it since its first start.
#
# Prints lengths and short hashes. Never prints the secret.
set -euo pipefail

kctl() {
  if [[ -x ./zarf ]]; then
    ./zarf tools kubectl "$@"
  elif command -v uds >/dev/null 2>&1; then
    uds zarf tools kubectl "$@"
  else
    command kubectl "$@"
  fi
}

ns=takserver
apps=(takserver-config takserver-messaging takserver-api takserver-plugins)
failures=0

fail() {
  echo "FAIL $*" >&2
  failures=$((failures + 1))
}

fingerprint() {
  printf '%s' "$1" | sha256sum | cut -c1-8
}

cluster_secret="$(kctl get secret takserver-sso -n "${ns}" -o jsonpath='{.data.TAK_OIDC_CLIENT_SECRET}' | base64 -d)"
want="len=${#cluster_secret} sha=$(fingerprint "${cluster_secret}")"
echo "cluster secret ${want}"

# The webhook has to fail closed and be limited to the TAK apps.
hook="$(kctl get mutatingwebhookconfiguration -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.webhooks[0].failurePolicy}{" "}{.webhooks[0].namespaceSelector.matchLabels}{"\n"}{end}' | grep -E '^pepr-[0-9a-f]{32} ' || true)"
if [[ -z "${hook}" ]]; then
  fail "the takserver-oidc webhook is not installed"
else
  grep -q ' Fail ' <<< "${hook}" || fail "the takserver-oidc webhook does not fail closed: ${hook}"
  grep -q 'takserver' <<< "${hook}" || fail "the takserver-oidc webhook is not scoped to the takserver namespace: ${hook}"
fi

for app in "${apps[@]}"; do
  # Only admission can add it. The Deployment template stays without it.
  template_inits="$(kctl get deploy "${app}" -n "${ns}" -o jsonpath='{.spec.template.spec.initContainers[*].name}')"
  if grep -qw 'render-oidc' <<< "${template_inits}"; then
    fail "${app}: the Deployment template carries render-oidc, so it is not coming from admission"
  fi
  template_ports="$(kctl get deploy "${app}" -n "${ns}" -o jsonpath='{.spec.template.spec.containers[0].ports[*].name}')"
  if grep -qw 'metrics' <<< "${template_ports}"; then
    fail "${app}: the Deployment template carries the metrics port, so it is not coming from admission"
  fi

  pods="$(kctl get pods -n "${ns}" -l "app=${app}" -o jsonpath='{.items[*].metadata.name}')"
  if [[ -z "${pods}" ]]; then
    fail "${app}: no pods"
    continue
  fi
  for pod in ${pods}; do
    inits="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{.spec.initContainers[*].name}')"
    if ! grep -qw 'render-oidc' <<< "${inits}"; then
      fail "${pod}: no render-oidc init container"
      continue
    fi
    code="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{.status.initContainerStatuses[?(@.name=="render-oidc")].state.terminated.exitCode}')"
    [[ "${code}" = "0" ]] || fail "${pod}: render-oidc exit code '${code}'"

    metrics="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{range .spec.containers[0].ports[*]}{.name}={.containerPort}{" "}{end}')"
    if [[ "${app}" == "takserver-api" || "${app}" == "takserver-messaging" ]]; then
      if ! grep -qw 'metrics=9100' <<< "${metrics}"; then
        fail "${pod}: metrics port is '${metrics}'"
      fi
    elif grep -qw 'metrics=9100' <<< "${metrics}"; then
      fail "${pod}: unexpected metrics port '${metrics}'"
    fi

    # TAK rewrites /conf/CoreConfig.xml from its in-memory copy when it saves,
    # so this is the secret the process holds, not only what the init rendered.
    container="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{.spec.containers[0].name}')"
    value="$(kctl exec "${pod}" -n "${ns}" -c "${container}" -- cat /conf/CoreConfig.xml \
      | tr -d '\n' \
      | grep -o '<openIdDiscoveryConfiguration[^>]*' \
      | grep -o ' secret="[^"]*"' | head -1 \
      | sed -e 's/^ secret="//' -e 's/"$//' \
            -e 's/&quot;/"/g' -e "s/&apos;/'/g" -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&amp;/\&/g')"
    have="len=${#value} sha=$(fingerprint "${value}")"
    if [[ "${have}" = "${want}" ]]; then
      echo "PASS ${pod} render-oidc completed, rendered secret ${have}"
    else
      fail "${pod}: rendered secret ${have} does not match the cluster secret ${want}"
    fi
  done
done

if [[ "${failures}" -ne 0 ]]; then
  echo "oidc-render: ${failures} failed" >&2
  exit 1
fi
echo "oidc-render: every TAK pod rendered the cluster secret"
