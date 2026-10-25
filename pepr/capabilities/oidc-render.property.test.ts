// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Property-based tests for addRender. fast-check generates pod shapes the
// example tests do not cover: missing spec, containers or labels, extra
// labels, and init containers, volumes or mounts that already use the names
// addRender adds. A failing case is shrunk to the smallest pod that breaks.
// addRender mutates its argument, so each property works on a copy and the
// generated value stays intact for shrinking.

import assert from "node:assert/strict";
import { test } from "node:test";
import fc from "fast-check";
import {
  addRender,
  CONFIG_MOUNT,
  INIT_NAME,
  isTakPod,
  RELOAD_LABEL,
  RELOAD_VALUE,
  TAK_APPS,
  type PodLike,
} from "./oidc-render.ts";

const IMAGE = "registry.example/takserver-config:1";
const RENDER_VOLUMES = [CONFIG_MOUNT, "oidc-script", "oidc-template", "oidc-secret", "keystore-secret"];
const NON_TAK_APPS = ["takserver-ignite", "takserver-nats", "takserver-postgresql"];

// Names that may collide with the ones addRender adds, plus arbitrary ones.
const name = fc.oneof(
  fc.constantFrom(...RENDER_VOLUMES, INIT_NAME, "wait-deps", "main"),
  fc.string({ minLength: 1, maxLength: 12 }),
);
const app = fc.oneof(
  fc.constantFrom(...TAK_APPS, ...NON_TAK_APPS),
  fc.string({ maxLength: 20 }),
);
const labels = fc.option(
  fc.record(
    {
      app,
      [RELOAD_LABEL]: fc.oneof(fc.constant(RELOAD_VALUE), fc.string({ maxLength: 10 })),
      other: fc.string({ maxLength: 10 }),
    },
    { requiredKeys: [], noNullPrototype: true },
  ),
  { nil: undefined },
);
const container = fc.record(
  {
    name,
    volumeMounts: fc.array(fc.record({ name, mountPath: fc.constantFrom("/conf", "/data") }, { noNullPrototype: true }), {
      maxLength: 3,
    }),
  },
  { requiredKeys: ["name"], noNullPrototype: true },
);
const spec = fc.option(
  fc.record(
    {
      containers: fc.array(container, { maxLength: 2 }),
      initContainers: fc.array(container, { maxLength: 3 }),
      volumes: fc.array(fc.record({ name }, { noNullPrototype: true }), { maxLength: 5 }),
    },
    { requiredKeys: [], noNullPrototype: true },
  ),
  { nil: undefined },
);
const pod: fc.Arbitrary<PodLike> = fc.record(
  {
    metadata: fc.option(fc.record({ labels }, { requiredKeys: [], noNullPrototype: true }), { nil: undefined }),
    spec,
  },
  { requiredKeys: [], noNullPrototype: true },
);

const count = (names: string[], wanted: string) => names.filter(n => n === wanted).length;

test("a second call never changes the pod", () => {
  fc.assert(
    fc.property(pod, generated => {
      const p = structuredClone(generated);
      addRender(p, IMAGE);
      const once = structuredClone(p);
      assert.equal(addRender(p, IMAGE), false);
      assert.deepEqual(p, once);
    }),
  );
});

test("pods that are not TAK pods are never changed", () => {
  fc.assert(
    fc.property(
      pod.filter(p => !isTakPod(p)),
      generated => {
        const p = structuredClone(generated);
        const before = structuredClone(p);
        assert.equal(addRender(p, IMAGE), false);
        assert.deepEqual(p, before);
      },
    ),
  );
});

test("TAK pods keep what they had and get each addition exactly once", () => {
  fc.assert(
    fc.property(
      pod,
      fc.constantFrom(...TAK_APPS),
      (generated, takApp) => {
        const p = structuredClone(generated);
        p.metadata = { ...p.metadata, labels: { ...p.metadata?.labels, app: takApp } };
        const before = structuredClone(p);
        addRender(p, IMAGE);

        // Existing init containers stay first and in order. render-oidc is
        // appended only when no init container already has that name.
        const initsBefore = (before.spec?.initContainers ?? []).map(c => c.name);
        const initsAfter = (p.spec?.initContainers ?? []).map(c => c.name);
        assert.deepEqual(initsAfter.slice(0, initsBefore.length), initsBefore);
        assert.equal(count(initsAfter, INIT_NAME), Math.max(1, count(initsBefore, INIT_NAME)));

        // Existing volumes are kept. Each render volume is present and never
        // added on top of one with the same name.
        const volsBefore = (before.spec?.volumes ?? []).map(v => v.name);
        const volsAfter = (p.spec?.volumes ?? []).map(v => v.name);
        assert.deepEqual(volsAfter.slice(0, volsBefore.length), volsBefore);
        for (const v of RENDER_VOLUMES) {
          assert.equal(count(volsAfter, v), Math.max(1, count(volsBefore, v)), v);
        }

        // Only the first container gets the mount, and only once.
        const containersBefore = before.spec?.containers ?? [];
        const containersAfter = p.spec?.containers ?? [];
        assert.equal(containersAfter.length, containersBefore.length);
        containersAfter.forEach((c, i) => {
          const mountsBefore = (containersBefore[i].volumeMounts ?? []).map(m => m.name);
          const mountsAfter = (c.volumeMounts ?? []).map(m => m.name);
          const want =
            i === 0 ? Math.max(1, count(mountsBefore, CONFIG_MOUNT)) : count(mountsBefore, CONFIG_MOUNT);
          assert.equal(count(mountsAfter, CONFIG_MOUNT), want);
        });

        // The reload label is set and no other label changes.
        const labelsAfter = p.metadata?.labels ?? {};
        assert.equal(labelsAfter[RELOAD_LABEL], RELOAD_VALUE);
        for (const [k, v] of Object.entries(before.metadata?.labels ?? {})) {
          if (k !== RELOAD_LABEL) {
            assert.equal(labelsAfter[k], v, k);
          }
        }
      },
    ),
  );
});
