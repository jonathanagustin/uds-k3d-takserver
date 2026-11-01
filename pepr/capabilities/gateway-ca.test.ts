// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster, DestinationRuleDoc } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { GatewayCa, onGatewayCa } from "./gateway-ca-capability.ts";
import { gatewaySecret, reconcileGatewayCa } from "./gateway-ca.ts";

const RULE: DestinationRuleDoc = {
  spec: {
    exportTo: ["istio-tenant-gateway"],
    trafficPolicy: { portLevelSettings: [{ tls: { credentialName: "takserver-web-ca" } }] },
  },
};

function fake(opts: {
  rule?: DestinationRuleDoc;
  ca?: string;
  secret?: { data?: Record<string, string> };
}) {
  const applied: { namespace: string; name: string; labels: Record<string, string>; data: Record<string, string> }[] = [];
  const cluster = {
    getDestinationRule: async () => opts.rule,
    getConfigMap: async () => (opts.ca === undefined ? undefined : { binaryData: { "ca.pem": opts.ca, "ca-do-not-share.key": "nope" } }),
    getSecret: async () => opts.secret,
    applySecret: async (namespace: string, name: string, labels: Record<string, string>, data: Record<string, string>) => {
      applied.push({ namespace, name, labels, data });
    },
  };
  return { cluster: cluster as unknown as Cluster, applied };
}

test("the gateway secret carries the CA certificate and nothing else", () => {
  const secret = gatewaySecret(RULE, "Y2E=");
  assert.deepEqual(secret, {
    namespace: "istio-tenant-gateway",
    name: "takserver-web-ca",
    data: { cacert: "Y2E=" },
  });
  assert.deepEqual(Object.keys(secret.data), ["cacert"]);
});

test("a DestinationRule without a credential name is an error", () => {
  assert.throws(() => gatewaySecret({ spec: { exportTo: ["ns"] } }, "Y2E="), /Missing gateway namespace/);
  assert.throws(() => gatewaySecret({ spec: {} }, "Y2E="), /Missing gateway namespace/);
  assert.throws(() => gatewaySecret({}, "Y2E="), /Missing gateway namespace/);
  assert.throws(() => gatewaySecret(RULE, ""), /Missing gateway namespace/);
});

test("backend TLS off skips the copy", async () => {
  const { cluster, applied } = fake({ rule: undefined, ca: "Y2E=" });
  await reconcileGatewayCa("ADDED", cluster);
  assert.equal(applied.length, 0);
});

test("a missing CA waits instead of writing an empty secret", async () => {
  const { cluster, applied } = fake({ rule: RULE });
  await reconcileGatewayCa("ADDED", cluster);
  assert.equal(applied.length, 0);
});

test("rotation replaces the gateway secret and leaves the key behind", async () => {
  const { cluster, applied } = fake({ rule: RULE, ca: "bmV3" });
  await reconcileGatewayCa("MODIFIED", cluster);
  assert.equal(applied.length, 1);
  assert.equal(applied[0].namespace, "istio-tenant-gateway");
  assert.equal(applied[0].name, "takserver-web-ca");
  assert.deepEqual(applied[0].data, { cacert: "bmV3" });
  assert.equal(applied[0].labels["app.kubernetes.io/part-of"], "takserver");
  assert.equal("ca-do-not-share.key" in applied[0].data, false);
});

test("an already-copied secret is not written again", async () => {
  const { cluster, applied } = fake({
    rule: RULE,
    ca: "bmV3",
    secret: { data: { cacert: "bmV3" } },
  });
  await reconcileGatewayCa("ADDED", cluster);
  assert.equal(applied.length, 0);
});

test("an extra key in the gateway secret is replaced", async () => {
  const { cluster, applied } = fake({
    rule: RULE,
    ca: "bmV3",
    secret: { data: { cacert: "bmV3", extra: "x" } },
  });
  await reconcileGatewayCa("ADDED", cluster);
  assert.equal(applied.length, 1);
});

test("deletion does not remove the copied secret", async () => {
  const { cluster, applied } = fake({ rule: RULE, ca: "bmV3" });
  await reconcileGatewayCa("DELETED", cluster);
  assert.equal(applied.length, 0);
});

const saved = runtime.cluster;
afterEach(() => {
  runtime.cluster = saved;
});

test("the capability watches cert-migration and the DestinationRule", async () => {
  const registered = GatewayCa as unknown as {
    bindings: { filters: { name: string }; kind: { kind: string }; isQueue?: boolean }[];
  };
  assert.equal(registered.bindings.length, 2);
  assert.deepEqual(
    registered.bindings.map(binding => `${binding.kind.kind}/${binding.filters.name}`),
    ["ConfigMap/cert-migration", "DestinationRule/takserver-web"],
  );
  assert.equal(registered.bindings[0].isQueue, true);
  runtime.cluster = fake({ rule: undefined }).cluster;
  await onGatewayCa({}, "DELETED");
});
