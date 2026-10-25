// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Builds the CoreDNS key the takserver component used to write from zarf.yaml.
// CoreDNS imports *.override in name order, and the first matching
// `rewrite stop` wins, so 00-takserver.override runs before uds.override.

import type { Cluster } from "../cluster.ts";

export const OVERRIDE_KEY = "00-takserver.override";
export const COREDNS_NAMESPACE = "kube-system";
export const COREDNS_CONFIGMAP = "coredns-custom";
export const COREDNS_DEPLOYMENT = "coredns";

export const GATEWAYS = [
  ["istio-passthrough-gateway", "passthrough-ingressgateway"],
  ["istio-admin-gateway", "admin-ingressgateway"],
  ["istio-tenant-gateway", "tenant-ingressgateway"],
] as const;

export interface CoreDnsEnv {
  inClusterDns: string;
  domain: string;
  passthroughHosts: string;
}

export function readCoreDnsEnv(env: NodeJS.ProcessEnv = process.env): CoreDnsEnv {
  return {
    inClusterDns: env.IN_CLUSTER_DNS ?? "true",
    domain: env.DOMAIN ?? "",
    passthroughHosts: env.PASSTHROUGH_HOSTS ?? "",
  };
}

export function escapeDots(value: string): string {
  return value.replaceAll(".", "\\.");
}

function rule(pattern: string, namespace: string, service: string): string {
  return `rewrite stop {\n  name regex (${pattern}) ${service}.${namespace}.svc.cluster.local answer auto\n}\n`;
}

// present keys are `${namespace}/${service}`. A missing Service contributes
// no rule, matching the shell action.
export function coreDnsRules(domain: string, passthroughHosts: string, present: ReadonlySet<string>): string {
  const re = escapeDots(domain);
  let rules = "";
  const add = (pattern: string, namespace: string, service: string): void => {
    if (!present.has(`${namespace}/${service}`)) {
      return;
    }
    rules += rule(pattern, namespace, service);
  };
  const hosts = passthroughHosts.split(/\s+/).filter(host => host.length > 0).map(escapeDots);
  if (hosts.length > 0) {
    add(`(${hosts.join("|")})\\.${re}`, GATEWAYS[0][0], GATEWAYS[0][1]);
  }
  add(`.*\\.admin\\.${re}`, GATEWAYS[1][0], GATEWAYS[1][1]);
  add(`.*\\.${re}`, GATEWAYS[2][0], GATEWAYS[2][1]);
  return rules;
}

export function sameOverride(current: string, rules: string): boolean {
  return current.replace(/\n+$/, "") === rules.replace(/\n+$/, "");
}

async function gatewaySet(cluster: Cluster): Promise<Set<string>> {
  const present = new Set<string>();
  for (const [namespace, service] of GATEWAYS) {
    if (await cluster.serviceExists(namespace, service)) {
      present.add(`${namespace}/${service}`);
    }
  }
  return present;
}

export async function reconcileCoreDns(cluster: Cluster, env: CoreDnsEnv): Promise<void> {
  if (env.inClusterDns !== "true") {
    return;
  }
  const configMap = await cluster.getConfigMap(COREDNS_NAMESPACE, COREDNS_CONFIGMAP);
  if (!configMap) {
    return;
  }
  if (!env.domain) {
    throw new Error("DOMAIN is not set");
  }
  if (!configMap.data) {
    throw new Error("kube-system/coredns-custom has no data");
  }
  const rules = coreDnsRules(env.domain, env.passthroughHosts, await gatewaySet(cluster));
  const current = configMap.data[OVERRIDE_KEY] ?? "";
  if (sameOverride(current, rules)) {
    return;
  }
  await cluster.patchConfigMapKey(
    COREDNS_NAMESPACE,
    COREDNS_CONFIGMAP,
    OVERRIDE_KEY,
    rules,
    Object.prototype.hasOwnProperty.call(configMap.data, OVERRIDE_KEY),
  );
  const deployment = await cluster.getDeployment(COREDNS_NAMESPACE, COREDNS_DEPLOYMENT);
  if (!deployment) {
    throw new Error("kube-system/coredns Deployment is missing");
  }
  const hasAnnotations = deployment.spec?.template?.metadata?.annotations !== undefined;
  await cluster.restartDeployment(COREDNS_NAMESPACE, COREDNS_DEPLOYMENT, hasAnnotations);
}
