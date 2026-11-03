// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Checks the Pepr binding itself: what it watches and what its mutate
// callback does with and without RENDER_IMAGE. The pod logic is covered in
// oidc-render.test.ts.

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { OidcRender } from "./oidc-render-capability.ts";
import { INIT_NAME, NAMESPACE, type PodLike } from "./oidc-render.ts";

interface Binding {
  event: string;
  kind: { kind: string; version: string; group: string };
  filters: { namespaces: string[] };
  isMutate?: boolean;
  mutateCallback: (request: { Raw: PodLike }) => unknown;
}

const IMAGE = "registry.example/takserver-config:1";
const saved = process.env.RENDER_IMAGE;
const savedCluster = runtime.cluster;

afterEach(() => {
  runtime.cluster = savedCluster;
  if (saved === undefined) {
    delete process.env.RENDER_IMAGE;
  } else {
    process.env.RENDER_IMAGE = saved;
  }
});

function stubCluster(): void {
  runtime.cluster = {
    getConfigMap: async () => ({
      data: {
        "CoreConfig.xml":
          'configurationUri="https://sso.uds.dev/realms/uds/.well-known/openid-configuration"',
      },
    }),
  } as unknown as Cluster;
}

function binding(): Binding {
  const bindings = (OidcRender as unknown as { bindings: Binding[] }).bindings;
  assert.equal(bindings.length, 1);
  return bindings[0];
}

function takPod(): PodLike {
  return {
    metadata: { labels: { app: "takserver-api" } },
    spec: { initContainers: [{ name: "wait-deps" }], containers: [{ name: "main" }] },
  };
}

test("the capability mutates Pod creation in the TAK namespace only", () => {
  assert.equal(OidcRender.name, "takserver-oidc-render");
  assert.deepEqual(OidcRender.namespaces, [NAMESPACE]);
  const b = binding();
  assert.equal(b.event, "CREATE");
  assert.deepEqual(b.kind, { kind: "Pod", version: "v1", group: "" });
  assert.deepEqual(b.filters.namespaces, [NAMESPACE]);
  assert.equal(b.isMutate, true);
});

test("the mutate callback adds the render init container with RENDER_IMAGE", async () => {
  process.env.RENDER_IMAGE = IMAGE;
  stubCluster();
  const pod = takPod();
  await binding().mutateCallback({ Raw: pod });
  const init = pod.spec?.initContainers?.find(c => c.name === INIT_NAME);
  assert.equal(init?.image, IMAGE);
  assert.deepEqual(
    pod.spec?.initContainers?.map(container => container.name),
    ["wait-deps", "import-trust", INIT_NAME],
  );
});

test("a missing RENDER_IMAGE rejects the pod instead of skipping it", async () => {
  delete process.env.RENDER_IMAGE;
  const pod = takPod();
  await assert.rejects(
    async () => binding().mutateCallback({ Raw: pod }),
    /RENDER_IMAGE is not set/,
  );
  assert.deepEqual(pod, takPod());
});
