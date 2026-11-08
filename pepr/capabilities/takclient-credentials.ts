// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Enrollment passwords must never reach the device-delivered Secret. The
// fixed name allows watcher-only get/patch RBAC without granting access to
// arbitrary Secrets in takserver. No cross-namespace owner references.
import { randomBytes } from "node:crypto";
import type { Cluster } from "../cluster.ts";

export const ENROLLMENT_SECRET = "takclient-enrollment";
let lock: Promise<unknown> = Promise.resolve();

async function exclusive<T>(run: () => Promise<T>): Promise<T> {
  const next = lock.then(run, run);
  lock = next.catch(() => undefined);
  return next;
}

export async function readCredential(cluster: Cluster, name: string): Promise<string | undefined> {
  const secret = await cluster.getSecret("takserver", ENROLLMENT_SECRET);
  const value = secret?.data?.[name];
  return value ? Buffer.from(value, "base64").toString("utf8") || undefined : undefined;
}

export async function rememberCredential(cluster: Cluster, name: string): Promise<string> {
  return exclusive(async () => {
    const current = await readCredential(cluster, name);
    if (current) return current;
    const secret = await cluster.getSecret("takserver", ENROLLMENT_SECRET);
    const password = `${randomBytes(18).toString("base64url")}Aa1!`;
    await cluster.applySecret("takserver", ENROLLMENT_SECRET,
      { "app.kubernetes.io/managed-by": "takserver-oidc" },
      { ...secret?.data, [name]: Buffer.from(password).toString("base64") });
    return password;
  });
}

export async function forgetCredential(cluster: Cluster, name: string): Promise<void> {
  return exclusive(async () => {
    const secret = await cluster.getSecret("takserver", ENROLLMENT_SECRET);
    if (!secret?.data || !(name in secret.data)) return;
    const data = { ...secret.data };
    delete data[name];
    await cluster.applySecret("takserver", ENROLLMENT_SECRET,
      { "app.kubernetes.io/managed-by": "takserver-oidc" }, data);
  });
}
