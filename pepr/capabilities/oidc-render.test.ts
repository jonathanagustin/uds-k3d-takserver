// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addRender,
  CONFIG_MOUNT,
  INIT_NAME,
  isTakPod,
  RELOAD_LABEL,
  TAK_APPS,
  type PodLike,
} from "./oidc-render.ts";

const IMAGE = "registry.example/takserver-config:1";

function pod(app: string): PodLike {
  return {
    metadata: { labels: { app } },
    spec: {
      initContainers: [{ name: "wait-deps" }],
      containers: [{ name: "main" }],
    },
  };
}

test("every TAK app gets the init container, the volumes and the mount", () => {
  for (const app of TAK_APPS) {
    const p = pod(app);
    assert.equal(addRender(p, IMAGE), true, app);
    const inits = p.spec?.initContainers ?? [];
    assert.deepEqual(
      inits.map(c => c.name),
      ["wait-deps", INIT_NAME],
      `${app}: wait-deps stays first`,
    );
    assert.equal(inits[1].image, IMAGE);
    const names = (p.spec?.volumes ?? []).map(v => v.name);
    for (const name of [CONFIG_MOUNT, "oidc-script", "oidc-template", "oidc-secret", "keystore-secret"]) {
      assert.ok(names.includes(name), `${app}: volume ${name}`);
    }
    const mounts = p.spec?.containers?.[0].volumeMounts ?? [];
    assert.ok(mounts.some(m => m.name === CONFIG_MOUNT && m.mountPath === "/conf"));
    assert.equal(p.metadata?.labels?.[RELOAD_LABEL], "takserver");
  }
});

test("plugins is covered, since it also reads CoreConfig.xml", () => {
  assert.ok(isTakPod(pod("takserver-plugins")));
});

test("pods that do not read CoreConfig.xml are left alone", () => {
  for (const app of ["takserver-ignite", "takserver-nats", "takserver-postgresql"]) {
    const p = pod(app);
    assert.equal(addRender(p, IMAGE), false, app);
    assert.deepEqual(p, pod(app), app);
  }
  assert.equal(addRender({}, IMAGE), false);
});

test("a second call changes nothing", () => {
  const p = pod("takserver-api");
  addRender(p, IMAGE);
  const once = structuredClone(p);
  assert.equal(addRender(p, IMAGE), false);
  assert.deepEqual(p, once);
});

test("an existing oidc-script volume is not duplicated", () => {
  const p = pod("takserver-plugins");
  p.spec!.volumes = [{ name: "oidc-script", configMap: { name: "takserver-oidc-render" } }];
  addRender(p, IMAGE);
  const count = (p.spec?.volumes ?? []).filter(v => v.name === "oidc-script").length;
  assert.equal(count, 1);
});
