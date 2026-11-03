// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { test } from "node:test";
import { parse } from "yaml";
import {
  FAILURE_VALUE,
  failurePolicy,
  MATCH_CONDITION,
  matchExpression,
  pinLiterals,
  scopeWebhook,
  splitTakClientWebhook,
  TIMEOUT_VALUE,
} from "../scripts/webhook-scope.ts";
import { TAK_APPS } from "./oidc-render.ts";
import { IGNITE_CONFIGMAP, IGNITE_STATEFULSET, TAK_DEPLOYS } from "./workload.ts";

// The shape `pepr build` writes, after its own value replacements. The path
// hash and the CA bundle contain the replaced text on purpose.
const generated = `apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: {{ .Values.uuid }}
webhooks:
  - admissionReviewVersions:
      - v1
    clientConfig:
      caBundle: >-
        LS0t${FAILURE_VALUE}LS0t
      service:
        name: {{ .Values.uuid }}
        namespace: pepr-system
        path: >-
          /mutate/3e34bf${TIMEOUT_VALUE}d2259
    failurePolicy: ${FAILURE_VALUE}
    matchPolicy: Equivalent
    name: {{ .Values.uuid }}.pepr.dev
    namespaceSelector:
      matchExpressions:
        - key: kubernetes.io/metadata.name
          operator: In
          values:
            - kube-system
            - pepr-system
    objectSelector:
      matchExpressions:
        - key: pepr.dev
          operator: In
          values:
            - ignore
    rules:
      - apiGroups:
          - ''
        apiVersions:
          - v1
        operations:
          - CREATE
        resources:
          - pods
    sideEffects: None
    timeoutSeconds: ${TIMEOUT_VALUE}
`;

// Helm placeholders are not YAML. Swap them for plain words before parsing.
function render(text: string) {
  return parse(
    text.replaceAll("{{ .Values.uuid }}", "uuid").replaceAll(TIMEOUT_VALUE, "TIMEOUT").replaceAll(FAILURE_VALUE, "FAILURE"),
  );
}

test("the match expression names every object the capabilities mutate", () => {
  const expression = matchExpression();
  for (const name of [...TAK_DEPLOYS, ...TAK_APPS, IGNITE_CONFIGMAP, IGNITE_STATEFULSET]) {
    assert.ok(expression.includes(`'${name}'`), name);
  }
  assert.ok(expression.includes("request.kind.kind == 'Deployment'"));
  assert.ok(expression.includes("request.kind.kind == 'ConfigMap'"));
  assert.ok(expression.includes("request.kind.kind == 'StatefulSet'"));
  assert.ok(expression.includes("has(object.metadata.labels)"));
  assert.ok(!expression.includes('"'), "the expression must not need YAML escaping");
});

test("scopeWebhook keeps one namespace, matches by name and label, and drops the object selector", () => {
  const doc = render(scopeWebhook(generated));
  const hook = doc.webhooks[0];
  assert.deepEqual(hook.namespaceSelector, { matchLabels: { "kubernetes.io/metadata.name": "takserver" } });
  assert.equal(hook.objectSelector, undefined);
  assert.deepEqual(hook.matchConditions, [{ name: MATCH_CONDITION, expression: matchExpression() }]);
  assert.deepEqual(hook.rules[0].resources, ["pods"]);
  assert.equal(hook.sideEffects, "None");
});

test("scopeWebhook throws when the generated template changes", () => {
  assert.throws(() => scopeWebhook(generated.replace("    namespaceSelector:\n", "")), /namespaceSelector anchor/);
  assert.throws(() => scopeWebhook(generated.replace("    rules:\n", "")), /namespaceSelector anchor/);
});

test("pinLiterals keeps the chart values out of the path and the CA bundle", () => {
  const pinned = pinLiterals(generated, 10, "Fail");
  const hook = render(pinned).webhooks[0];
  assert.equal(hook.clientConfig.service.path, "/mutate/3e34bf10d2259");
  assert.equal(hook.clientConfig.caBundle, "LS0tFailLS0t");
  assert.equal(hook.timeoutSeconds, "TIMEOUT");
  assert.equal(hook.failurePolicy, "FAILURE");
  assert.equal(pinned.split(TIMEOUT_VALUE).length, 2);
  assert.equal(pinned.split(FAILURE_VALUE).length, 2);
});

test("pinLiterals throws when the webhook has no timeout or failure policy field", () => {
  assert.throws(() => pinLiterals(generated.replace(/^ +timeoutSeconds: .*$/m, ""), 10, "Fail"), /no timeoutSeconds/);
  assert.throws(() => pinLiterals(generated.replace(/^ +failurePolicy: .*$/m, ""), 10, "Fail"), /no timeoutSeconds/);
});

test("failurePolicy follows Pepr's onError mapping", () => {
  assert.equal(failurePolicy("reject"), "Fail");
  assert.equal(failurePolicy("ignore"), "Ignore");
  assert.equal(failurePolicy(undefined), "Ignore");
});

// The generated webhook with the TakClient rule Pepr adds for ADR 22.
const withTakClients = generated.replace(
  "    sideEffects: None",
  [
    "      - apiGroups:",
    "          - tak.jonathanagustin.github.io",
    "        apiVersions:",
    "          - v1alpha1",
    "        operations:",
    "          - CREATE",
    "          - UPDATE",
    "        resources:",
    "          - takclients",
    "    sideEffects: None",
  ].join("\n"),
);

test("splitTakClientWebhook moves TakClients to their own entry without the TAK match conditions", () => {
  const split = splitTakClientWebhook(scopeWebhook(pinLiterals(withTakClients, 10, "Fail")));
  const [tak, clients, extra] = render(split).webhooks;
  assert.equal(extra, undefined);
  assert.deepEqual(
    tak.rules.map((rule: { resources: string[] }) => rule.resources),
    [["pods"]],
  );
  assert.equal(tak.matchConditions[0].name, MATCH_CONDITION);
  assert.equal(clients.name, "takclients.uuid.pepr.dev");
  assert.deepEqual(clients.namespaceSelector, { matchLabels: { "kubernetes.io/metadata.name": "takclients" } });
  assert.equal(clients.matchConditions, undefined);
  assert.equal(clients.objectSelector, undefined);
  assert.deepEqual(clients.rules[0].resources, ["takclients"]);
  assert.deepEqual(clients.clientConfig, tak.clientConfig);
  assert.equal(clients.clientConfig.service.path, "/mutate/3e34bf10d2259");
  assert.equal(clients.timeoutSeconds, "TIMEOUT");
  assert.equal(clients.failurePolicy, "FAILURE");
  assert.equal(clients.sideEffects, "None");
});

test("splitTakClientWebhook throws when the TakClient rule is missing", () => {
  assert.throws(() => splitTakClientWebhook(scopeWebhook(generated)), /TakClient rule anchor/);
});
