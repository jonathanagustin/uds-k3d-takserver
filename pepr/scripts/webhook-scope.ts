// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Edits to the MutatingWebhookConfiguration that `pepr build` writes.
//
// Scope. The generated webhook matches every namespace except kube-system and
// pepr-system, and fails closed. It is narrowed to namespace takserver and to
// the objects the capabilities act on. The upstream chart labels the pods
// (`app: takserver-api` and so on) but puts no labels on the Deployments or
// on the Ignite ConfigMap, and the Ignite StatefulSet has no `app` label. An
// object selector on `app` therefore let only the pods through. A
// matchConditions rule matches the pods by label and the other objects by
// name, so admission shapes them before they are stored.
//
// Literals. Pepr turns the webhook timeout and the failure policy into chart
// values by replacing every occurrence of their text in the generated YAML.
// That also rewrites the same text inside the webhook path and the CA bundle,
// for example a "10" in the path hash. Those values render back only while
// the chart values equal the build-time ones. This puts the literal back
// everywhere except the timeoutSeconds and failurePolicy fields.

import { NAMESPACE, TAK_APPS } from "../capabilities/oidc-render.ts";
import { IGNITE_CONFIGMAP, IGNITE_STATEFULSET, TAK_DEPLOYS } from "../capabilities/workload.ts";

export const TIMEOUT_VALUE = "{{ .Values.admission.webhookTimeout }}";
export const FAILURE_VALUE = "{{ .Values.admission.failurePolicy }}";
export const MATCH_CONDITION = "takserver-objects";

function celList(values: readonly string[]): string {
  return `[${values.map(v => `'${v}'`).join(", ")}]`;
}

// Pods are matched by the app label, because a new pod's name is generated.
// Every other kind in the webhook rules is matched by name.
export function matchExpression(): string {
  return [
    `request.kind.kind == 'Deployment' ? object.metadata.name in ${celList(TAK_DEPLOYS)} :`,
    `request.kind.kind == 'ConfigMap' ? object.metadata.name == '${IGNITE_CONFIGMAP}' :`,
    `request.kind.kind == 'StatefulSet' ? object.metadata.name == '${IGNITE_STATEFULSET}' :`,
    `has(object.metadata.labels) && 'app' in object.metadata.labels &&`,
    `object.metadata.labels['app'] in ${celList(TAK_APPS)}`,
  ].join(" ");
}

// Replaces the generated namespaceSelector (and anything else up to `rules:`)
// in each webhook entry. Throws when an anchor is missing, so a Pepr upgrade
// that changes the template fails the build instead of shipping a wider
// webhook.
export function scopeWebhook(text: string): string {
  const start = text.indexOf("    namespaceSelector:\n");
  const end = text.indexOf("    rules:\n");
  if (start < 0 || end < start) {
    throw new Error("mutation-webhook.yaml no longer has the namespaceSelector anchor");
  }
  const scope = [
    "    namespaceSelector:",
    "      matchLabels:",
    `        kubernetes.io/metadata.name: ${NAMESPACE}`,
    "    matchConditions:",
    `      - name: ${MATCH_CONDITION}`,
    "        expression: >-",
    `          ${matchExpression()}`,
    "",
  ].join("\n");
  return text.slice(0, start) + scope + text.slice(end);
}

export function failurePolicy(onError: string | undefined): string {
  return onError === "reject" ? "Fail" : "Ignore";
}

export function pinLiterals(text: string, timeout: number, policy: string): string {
  const pinned = text.replaceAll(TIMEOUT_VALUE, String(timeout)).replaceAll(FAILURE_VALUE, policy);
  const timeoutField = /^( +timeoutSeconds: )\S+$/gm;
  const policyField = /^( +failurePolicy: )\S+$/gm;
  if (pinned.match(timeoutField) === null || pinned.match(policyField) === null) {
    throw new Error("webhook YAML has no timeoutSeconds or failurePolicy field");
  }
  return pinned.replace(timeoutField, `$1${TIMEOUT_VALUE}`).replace(policyField, `$1${FAILURE_VALUE}`);
}

// Cuts the TakClient rule out of the TAK webhook entry and adds a second entry
// that matches only TakClients in namespace takclients (ADR 22). The second
// entry copies the first one's path, CA bundle, timeout, and failure policy,
// but not its matchConditions, which match only TAK objects. Run it after
// scopeWebhook.
export function splitTakClientWebhook(text: string): string {
  const ruleStart = text.indexOf("      - apiGroups:\n          - tak.jonathanagustin.github.io\n");
  const ruleEnd = text.indexOf("    sideEffects:", ruleStart);
  const entry = text.indexOf("  - admissionReviewVersions:");
  if (ruleStart < 0 || ruleEnd < 0 || entry < 0) {
    throw new Error("mutation-webhook.yaml no longer has the TakClient rule anchor");
  }
  const rule = text.slice(ruleStart, ruleEnd);
  const pods = text.slice(0, ruleStart) + text.slice(ruleEnd);
  const first = pods.slice(entry);
  const selectorStart = first.indexOf("    namespaceSelector:\n");
  const rulesStart = first.indexOf("    rules:\n");
  const tailStart = first.indexOf("    sideEffects:");
  const second = [
    first.slice(0, selectorStart).replace("name: {{ .Values.uuid }}.pepr.dev", "name: takclients.{{ .Values.uuid }}.pepr.dev"),
    "    namespaceSelector:\n      matchLabels:\n        kubernetes.io/metadata.name: takclients\n",
    "    rules:\n",
    rule,
    first.slice(tailStart),
  ].join("");
  return `${pods.replace(/\n*$/, "\n")}${second}`;
}
