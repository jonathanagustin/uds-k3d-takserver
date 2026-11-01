// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Copies the deploy-time CA certificate, never the key, into the Secret the
// tenant gateway reads. Names come from DestinationRule takserver-web.

import type { Cluster, DestinationRuleDoc, SecretDoc } from "../cluster.ts";

export const TAK_NAMESPACE = "takserver";
export const CERT_CONFIGMAP = "cert-migration";
export const GATEWAY_DESTINATION_RULE = "takserver-web";
export const CA_KEY = "ca.pem";

export interface GatewaySecret {
  namespace: string;
  name: string;
  data: { cacert: string };
}

export function gatewaySecret(rule: DestinationRuleDoc, caPem: string): GatewaySecret {
  const namespace = rule.spec?.exportTo?.[0] ?? "";
  const name = rule.spec?.trafficPolicy?.portLevelSettings?.[0]?.tls?.credentialName ?? "";
  if (!namespace || !name || !caPem) {
    throw new Error("Missing gateway namespace, Secret name, or ca.pem");
  }
  return { namespace, name, data: { cacert: caPem } };
}

function alreadyCopied(secret: SecretDoc | undefined, caPem: string): boolean {
  const data = secret?.data;
  if (!data) {
    return false;
  }
  const keys = Object.keys(data);
  return keys.length === 1 && keys[0] === "cacert" && data.cacert === caPem;
}

export async function reconcileGatewayCa(phase: string, cluster: Cluster): Promise<void> {
  if (phase === "DELETED") {
    return;
  }
  const rule = await cluster.getDestinationRule(TAK_NAMESPACE, GATEWAY_DESTINATION_RULE);
  if (!rule) {
    return;
  }
  const configMap = await cluster.getConfigMap(TAK_NAMESPACE, CERT_CONFIGMAP);
  const caPem = configMap?.binaryData?.[CA_KEY];
  if (!caPem) {
    return;
  }
  const secret = gatewaySecret(rule, caPem);
  const current = await cluster.getSecret(secret.namespace, secret.name);
  if (alreadyCopied(current, caPem)) {
    return;
  }
  await cluster.applySecret(
    secret.namespace,
    secret.name,
    { "app.kubernetes.io/part-of": "takserver" },
    secret.data,
  );
}
