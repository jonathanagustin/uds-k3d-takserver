// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Copies the TAK CA, the admin certificate, and its key into the Secret
// CloudTAK reads. The certificates are in ConfigMap cert-migration. The cert
// Job moves private keys into Secret takserver-certs. A ConfigMap supplied
// before that split still has the key, and a Secret may hold the
// certificates, so each falls back to the other. The CA key stays in
// takserver.

import type { Cluster, ConfigMapDoc, SecretDoc } from "../cluster.ts";

export const CLOUDTAK_NAMESPACE = "cloudtak";
export const CLOUDTAK_SECRET = "cloudtak-tak-admin";
export const KEYSTORE_SECRET = "takserver-keystore";
export const CERTS_SECRET = "takserver-certs";

export function cloudtakData(
  configMap: ConfigMapDoc | undefined,
  keystore: SecretDoc | undefined,
  certs?: SecretDoc,
): Record<string, string> | undefined {
  const binary = configMap?.binaryData;
  const secret = certs?.data;
  const ca = binary?.["ca.pem"] || secret?.["ca.pem"];
  const cert = binary?.["admin.pem"] || secret?.["admin.pem"];
  const key = secret?.["admin.key"] || binary?.["admin.key"];
  const pass = keystore?.data?.CAPASS;
  if (!ca || !cert || !key || !pass) {
    return undefined;
  }
  return { "ca.pem": ca, "admin.pem": cert, "admin.key": key, CAPASS: pass };
}

function sameSecret(current: SecretDoc | undefined, data: Record<string, string>): boolean {
  const got = current?.data;
  if (!got) {
    return false;
  }
  const keys = Object.keys(data);
  if (Object.keys(got).length !== keys.length) {
    return false;
  }
  return keys.every(key => got[key] === data[key]);
}

export async function reconcileCloudtak(phase: string, cluster: Cluster): Promise<void> {
  if (phase === "DELETED") {
    return;
  }
  const configMap = await cluster.getConfigMap("takserver", "cert-migration");
  const keystore = await cluster.getSecret("takserver", KEYSTORE_SECRET);
  const certs = await cluster.getSecret("takserver", CERTS_SECRET);
  const data = cloudtakData(configMap, keystore, certs);
  if (!data) {
    return;
  }
  const current = await cluster.getSecret(CLOUDTAK_NAMESPACE, CLOUDTAK_SECRET);
  if (sameSecret(current, data)) {
    return;
  }
  await cluster.ensureNamespace(CLOUDTAK_NAMESPACE);
  await cluster.applySecret(
    CLOUDTAK_NAMESPACE,
    CLOUDTAK_SECRET,
    { "app.kubernetes.io/part-of": "cloudtak" },
    data,
  );
}
