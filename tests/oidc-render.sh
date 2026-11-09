#!/usr/bin/env bash
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Checks the admission-time render of the OIDC client secret. The
# takserver-oidc module adds an init container to every TAK pod when the pod
# is created. Init containers cannot be added to a running pod, so a pod that
# has render-oidc has had it since its first start.
#
# Says whether the rendered secret matches the cluster secret. It does not
# print the value, its length, or a hash.
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

cluster_secret="$(kctl get secret takserver-sso -n "${ns}" -o jsonpath='{.data.TAK_OIDC_CLIENT_SECRET}' | base64 -d)"
if [[ -z "${cluster_secret}" ]]; then
  fail "cluster secret is absent"
else
  echo "cluster secret present"
fi

# The webhook has to fail closed and be limited to the TAK apps.
hook="$(kctl get mutatingwebhookconfiguration -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.webhooks[0].failurePolicy}{" "}{.webhooks[0].namespaceSelector.matchLabels}{"\n"}{end}' | grep -E '^pepr-[0-9a-f]{32} ' || true)"
if [[ -z "${hook}" ]]; then
  fail "the takserver-oidc webhook is not installed"
else
  grep -q ' Fail ' <<< "${hook}" || fail "the takserver-oidc webhook does not fail closed: ${hook}"
  grep -q 'takserver' <<< "${hook}" || fail "the takserver-oidc webhook is not scoped to the takserver namespace: ${hook}"
  # The upstream Deployments and Ignite objects carry no app label, so an
  # object selector on app would let only the pods through. The scope is a
  # matchConditions rule instead.
  name="${hook%% *}"
  scope="$(kctl get mutatingwebhookconfiguration "${name}" -o jsonpath='{.webhooks[0].matchConditions[*].name}|{.webhooks[0].objectSelector}')"
  # The API server stores an absent objectSelector as {}, which matches all.
  [[ "${scope}" == "takserver-objects|" || "${scope}" == "takserver-objects|{}" ]] \
    || fail "the takserver-oidc webhook scope is '${scope}', want matchConditions takserver-objects and an empty objectSelector"

  # Admission has to see the Deployments, the Ignite ConfigMap, and the Ignite
  # StatefulSet, not only the pods. Pod logs reset when a pod restarts, so this
  # is checked only while no admission pod has restarted.
  selector="app=${name},pepr.dev/controller=admission"
  restarts="$(kctl get pods -n pepr-system -l "${selector}" -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{"\n"}{end}' | sort -u)"
  if [[ "${restarts}" == "0" ]]; then
    seen="$(kctl logs -n pepr-system -l "${selector}" --tail=-1 --prefix=false \
      | grep '"msg":"Incoming request"' \
      | grep -o '"kind":"[A-Za-z]*"' | sort -u | tr '\n' ' ')"
    for kind in Pod Deployment ConfigMap StatefulSet; do
      grep -q "\"kind\":\"${kind}\"" <<< "${seen}" || fail "admission saw no ${kind} request; it saw: ${seen:-nothing}"
    done
    echo "admission requests by kind: ${seen}"
  else
    echo "skip admission request check: an admission pod restarted"
  fi
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

    # The Deployment still mounts ConfigMap cert-migration. Admission swaps
    # that volume for Secret takserver-certs before the pod is created.
    cert_secret="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{.spec.volumes[?(@.name=="config")].secret.secretName}')"
    cert_cm="$(kctl get pod "${pod}" -n "${ns}" -o jsonpath='{.spec.volumes[?(@.name=="config")].configMap.name}')"
    if [[ "${cert_secret}" != "takserver-certs" || -n "${cert_cm}" ]]; then
      fail "${pod}: cert volume is secret=${cert_secret:-<none>} configMap=${cert_cm:-<none>}"
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
    if [[ -n "${value}" && "${value}" == "${cluster_secret}" ]]; then
      echo "PASS ${pod} render-oidc completed, secret present"
    else
      fail "${pod}: rendered secret is absent or does not match the cluster secret"
    fi
  done
done

if [[ "${failures}" -ne 0 ]]; then
  echo "oidc-render: ${failures} failed" >&2
  exit 1
fi
echo "oidc-render: every TAK pod rendered the cluster secret"
