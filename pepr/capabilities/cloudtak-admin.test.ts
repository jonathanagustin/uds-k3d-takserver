// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster, ConfigMapDoc, SecretDoc } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { CloudtakAdmin, onCloudtak } from "./cloudtak-admin-capability.ts";
import { cloudtakData, reconcileCloudtak } from "./cloudtak-admin.ts";

const MATERIAL: ConfigMapDoc = {
  binaryData: {
    "ca.pem": "Y2E=",
    "admin.pem": "Y2VydA==",
    "admin.key": "a2V5",
    "ca-do-not-share.key": "c2VjcmV0",
  },
};

function fake(opts: { configMap?: ConfigMapDoc; keystore?: SecretDoc; current?: SecretDoc }) {
  const calls: { ensure: number; applied: Record<string, string>[] } = { ensure: 0, applied: [] };
  const cluster = {
    getConfigMap: async () => opts.configMap,
    getSecret: async (_namespace: string, name: string) => (name === "takserver-keystore" ? opts.keystore : opts.current),
    ensureNamespace: async () => {
      calls.ensure += 1;
    },
    applySecret: async (_ns: string, _name: string, _labels: Record<string, string>, data: Record<string, string>) => {
      calls.applied.push(data);
    },
  };
  return { cluster: cluster as unknown as Cluster, calls };
}

test("the CloudTAK secret is the CA, the admin certificate, its key, and CAPASS", () => {
  const data = cloudtakData(MATERIAL, { data: { CAPASS: "cGFzcw==" } });
  assert.deepEqual(data, {
    "ca.pem": "Y2E=",
    "admin.pem": "Y2VydA==",
    "admin.key": "a2V5",
    CAPASS: "cGFzcw==",
  });
  assert.equal(data && "ca-do-not-share.key" in data, false);
});

test("missing material waits", () => {
  assert.equal(cloudtakData(MATERIAL, undefined), undefined);
  assert.equal(cloudtakData(undefined, { data: { CAPASS: "cGFzcw==" } }), undefined);
  assert.equal(cloudtakData({ binaryData: { "ca.pem": "Y2E=" } }, { data: { CAPASS: "cGFzcw==" } }), undefined);
});

test("the secret is created in cloudtak", async () => {
  const { cluster, calls } = fake({ configMap: MATERIAL, keystore: { data: { CAPASS: "cGFzcw==" } } });
  await reconcileCloudtak("ADDED", cluster);
  assert.equal(calls.ensure, 1);
  assert.equal(calls.applied.length, 1);
  assert.equal(calls.applied[0].CAPASS, "cGFzcw==");
});

test("incomplete material does not create the namespace", async () => {
  const { cluster, calls } = fake({ configMap: MATERIAL });
  await reconcileCloudtak("ADDED", cluster);
  assert.equal(calls.ensure, 0);
});

test("an up to date secret is left alone", async () => {
  const data = cloudtakData(MATERIAL, { data: { CAPASS: "cGFzcw==" } });
  const { cluster, calls } = fake({
    configMap: MATERIAL,
    keystore: { data: { CAPASS: "cGFzcw==" } },
    current: { data },
  });
  await reconcileCloudtak("ADDED", cluster);
  assert.equal(calls.ensure, 0);
  assert.equal(calls.applied.length, 0);
});

test("an extra key is replaced", async () => {
  const data = cloudtakData(MATERIAL, { data: { CAPASS: "cGFzcw==" } }) ?? {};
  const { cluster, calls } = fake({
    configMap: MATERIAL,
    keystore: { data: { CAPASS: "cGFzcw==" } },
    current: { data: { ...data, extra: "x" } },
  });
  await reconcileCloudtak("ADDED", cluster);
  assert.equal(calls.applied.length, 1);
});

test("rotating the CA writes the secret again", async () => {
  const rotated: ConfigMapDoc = {
    binaryData: { ...MATERIAL.binaryData, "ca.pem": "cm90YXRlZA==" },
  };
  const { cluster, calls } = fake({
    configMap: rotated,
    keystore: { data: { CAPASS: "cGFzcw==" } },
    current: { data: cloudtakData(MATERIAL, { data: { CAPASS: "cGFzcw==" } }) },
  });
  await reconcileCloudtak("MODIFIED", cluster);
  assert.equal(calls.applied.length, 1);
  assert.equal(calls.applied[0]["ca.pem"], "cm90YXRlZA==");
});

test("deletion does not remove the CloudTAK secret", async () => {
  const { cluster, calls } = fake({ configMap: MATERIAL, keystore: { data: { CAPASS: "cGFzcw==" } } });
  await reconcileCloudtak("DELETED", cluster);
  assert.equal(calls.applied.length, 0);
});

const saved = runtime.cluster;
afterEach(() => {
  runtime.cluster = saved;
});

test("the capability watches cert-migration and the keystore secret", async () => {
  const registered = CloudtakAdmin as unknown as {
    bindings: { filters: { name: string }; kind: { kind: string } }[];
  };
  assert.deepEqual(
    registered.bindings.map(binding => `${binding.kind.kind}/${binding.filters.name}`),
    ["ConfigMap/cert-migration", "Secret/takserver-keystore"],
  );
  runtime.cluster = fake({}).cluster;
  await onCloudtak({}, "DELETED");
});
