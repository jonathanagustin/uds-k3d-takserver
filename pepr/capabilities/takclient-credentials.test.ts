// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Cluster, SecretDoc } from "../cluster.ts";
import { ENROLLMENT_SECRET, readCredential, rememberCredential, forgetCredential } from "./takclient-credentials.ts";

function storage(initial?: SecretDoc) {
  let secret = initial;
  const writes: string[] = [];
  const cluster = {
    getSecret: async (namespace: string, name: string) => {
      assert.equal(namespace, "takserver");
      assert.equal(name, ENROLLMENT_SECRET);
      return secret;
    },
    applySecret: async (namespace: string, name: string, _labels: Record<string, string>, data: Record<string, string>) => {
      writes.push(`${namespace}/${name}`);
      secret = { data };
    },
  } as unknown as Cluster;
  return { cluster, writes, value: () => secret };
}

test("enrollment credentials live only in the fixed watcher-private Secret", async () => {
  const { cluster, writes, value } = storage();
  const password = await rememberCredential(cluster, "client-a");
  assert.match(password, /^[A-Za-z0-9_-]+Aa1!$/);
  assert.equal(await rememberCredential(cluster, "client-a"), password);
  assert.equal(await readCredential(cluster, "client-a"), password);
  assert.deepEqual(writes, [`takserver/${ENROLLMENT_SECRET}`]);
  assert.deepEqual(Object.keys(value()!.data!), ["client-a"]);
  assert.equal(value()!.metadata, undefined); // No cross-namespace owner reference.
});

test("simultaneous creates and cleanup preserve other clients' private entries", async () => {
  const { cluster, value } = storage();
  const [first, second] = await Promise.all([rememberCredential(cluster, "first"), rememberCredential(cluster, "second")]);
  assert.notEqual(first, second);
  assert.deepEqual(Object.keys(value()!.data!).sort(), ["first", "second"]);
  await forgetCredential(cluster, "first");
  assert.equal(await readCredential(cluster, "first"), undefined);
  assert.equal(await readCredential(cluster, "second"), second);
  await forgetCredential(cluster, "second");
  assert.deepEqual(value()!.data, {});
});

test("missing, partial and empty private values are never usable credentials", async () => {
  const cases: (SecretDoc | undefined)[] = [undefined, {}, { data: {} }, { data: { client: "" } }, { data: { client: "$$" } }];
  for (const initial of cases) {
    const { cluster, writes } = storage(initial);
    assert.equal(await readCredential(cluster, "client"), undefined);
    await forgetCredential(cluster, "absent");
    assert.equal(writes.length, 0);
    assert.ok(await rememberCredential(cluster, "client"));
  }
});

test("a failed write does not poison the shared credential lock", async () => {
  const { cluster } = storage();
  const write = cluster.applySecret;
  cluster.applySecret = async () => { throw new Error("conflict"); };
  await assert.rejects(rememberCredential(cluster, "first"), /conflict/);
  cluster.applySecret = write;
  assert.ok(await rememberCredential(cluster, "second"));
});
