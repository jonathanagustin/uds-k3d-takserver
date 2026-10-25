// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { CoreDns, onCoreDns } from "./coredns-rewrite-capability.ts";
import {
  coreDnsRules,
  OVERRIDE_KEY,
  readCoreDnsEnv,
  reconcileCoreDns,
  rolloutDone,
  sameOverride,
  waitRollout,
  type CoreDnsEnv,
} from "./coredns-rewrite.ts";

const DOMAIN = "uds.dev";
const HOSTS = "takserver-api takserver-stream";

function env(over: Partial<CoreDnsEnv> = {}): CoreDnsEnv {
  return { inClusterDns: "true", domain: DOMAIN, passthroughHosts: HOSTS, ...over };
}

function allGateways(): Set<string> {
  return new Set([
    "istio-passthrough-gateway/passthrough-ingressgateway",
    "istio-admin-gateway/admin-ingressgateway",
    "istio-tenant-gateway/tenant-ingressgateway",
  ]);
}

function rules(): string {
  return coreDnsRules(DOMAIN, HOSTS, allGateways());
}

interface Recorded {
  patched: { key: string; value: string; present: boolean }[];
  restarted: { name: string; hasAnnotations: boolean }[];
  deployments: number;
}

function cluster(opts: {
  configMap?: { data?: Record<string, string> } | undefined;
  services?: Set<string>;
  deployment?: { spec?: { template?: { metadata?: { annotations?: Record<string, string> } } } } | undefined;
}): { cluster: Cluster; recorded: Recorded } {
  const recorded: Recorded = { patched: [], restarted: [], deployments: 0 };
  const services = opts.services ?? allGateways();
  const fake = {
    getConfigMap: async () => opts.configMap,
    serviceExists: async (namespace: string, name: string) => services.has(`${namespace}/${name}`),
    patchConfigMapKey: async (_ns: string, _name: string, key: string, value: string, present: boolean) => {
      recorded.patched.push({ key, value, present });
    },
    getDeployment: async () => {
      recorded.deployments += 1;
      if (!opts.deployment) {
        return opts.deployment;
      }
      const spec = opts.deployment.spec ?? {};
      return {
        spec: { replicas: 1, ...spec },
        status: { updatedReplicas: 1, availableReplicas: 1 },
      };
    },
    restartDeployment: async (_ns: string, name: string, hasAnnotations: boolean) => {
      recorded.restarted.push({ name, hasAnnotations });
    },
    sleep: async () => undefined,
  };
  return { cluster: fake as unknown as Cluster, recorded };
}

test("the default uds.dev rules match the zarf shell action", () => {
  const text = rules();
  assert.equal(
    text,
    [
      "rewrite stop {",
      "  name regex ((takserver-api|takserver-stream)\\.uds\\.dev) passthrough-ingressgateway.istio-passthrough-gateway.svc.cluster.local answer auto",
      "}",
      "rewrite stop {",
      "  name regex (.*\\.admin\\.uds\\.dev) admin-ingressgateway.istio-admin-gateway.svc.cluster.local answer auto",
      "}",
      "rewrite stop {",
      "  name regex (.*\\.uds\\.dev) tenant-ingressgateway.istio-tenant-gateway.svc.cluster.local answer auto",
      "}",
      "",
    ].join("\n"),
  );
});

test("a host with a dot is escaped, and a missing gateway adds no rule", () => {
  const present = new Set([
    "istio-passthrough-gateway/passthrough-ingressgateway",
    "istio-tenant-gateway/tenant-ingressgateway",
  ]);
  const text = coreDnsRules("example.com", "tak.api", present);
  assert.equal(text.includes("(tak\\.api)\\.example\\.com"), true);
  assert.doesNotMatch(text, /admin-ingressgateway/);
  assert.equal(coreDnsRules(DOMAIN, "", allGateways()).includes("passthrough"), false);
  assert.equal(coreDnsRules(DOMAIN, "   ", allGateways()).includes("passthrough"), false);
});

test("unset DNS env uses the shell defaults", () => {
  assert.deepEqual(readCoreDnsEnv({}), { inClusterDns: "true", domain: "", passthroughHosts: "" });
  assert.equal(readCoreDnsEnv({ IN_CLUSTER_DNS: "false", DOMAIN: "uds.dev", PASSTHROUGH_HOSTS: "api" }).domain, "uds.dev");
});

test("trailing newlines do not count as a change", () => {
  assert.equal(sameOverride("rewrite\n", "rewrite"), true);
  assert.equal(sameOverride("rewrite\n\n", "rewrite\n"), true);
  assert.equal(sameOverride("rewrite", "rewrite stop"), false);
});

test("IN_CLUSTER_DNS other than true does nothing", async () => {
  const { cluster: fake, recorded } = cluster({ configMap: { data: {} } });
  await reconcileCoreDns(fake, env({ inClusterDns: "false" }));
  assert.equal(recorded.patched.length, 0);
});

test("a cluster without coredns-custom is left alone", async () => {
  const { cluster: fake, recorded } = cluster({ configMap: undefined });
  await reconcileCoreDns(fake, env());
  assert.equal(recorded.patched.length, 0);
});

test("DOMAIN is required when the ConfigMap exists", async () => {
  const { cluster: fake } = cluster({ configMap: { data: {} } });
  await assert.rejects(reconcileCoreDns(fake, env({ domain: "" })), /DOMAIN is not set/);
});

test("a ConfigMap with no data is an error", async () => {
  const { cluster: fake } = cluster({ configMap: {} });
  await assert.rejects(reconcileCoreDns(fake, env()), /has no data/);
});

test("an unchanged override does not restart CoreDNS", async () => {
  const text = rules();
  const { cluster: fake, recorded } = cluster({ configMap: { data: { [OVERRIDE_KEY]: `${text}\n` } } });
  await reconcileCoreDns(fake, env());
  assert.equal(recorded.patched.length, 0);
  assert.equal(recorded.restarted.length, 0);
});

test("a new override is added and CoreDNS restarts", async () => {
  const { cluster: fake, recorded } = cluster({
    configMap: { data: { "uds.override": "keep" } },
    deployment: {},
  });
  await reconcileCoreDns(fake, env());
  assert.equal(recorded.patched.length, 1);
  assert.equal(recorded.patched[0].key, OVERRIDE_KEY);
  assert.equal(recorded.patched[0].present, false);
  assert.equal(recorded.patched[0].value, rules());
  assert.deepEqual(recorded.restarted, [{ name: "coredns", hasAnnotations: false }]);
});

test("an existing key is replaced, and annotations are preserved", async () => {
  const { cluster: fake, recorded } = cluster({
    configMap: { data: { [OVERRIDE_KEY]: "old" } },
    deployment: { spec: { template: { metadata: { annotations: { kept: "yes" } } } } },
  });
  await reconcileCoreDns(fake, env());
  assert.equal(recorded.patched[0].present, true);
  assert.deepEqual(recorded.restarted, [{ name: "coredns", hasAnnotations: true }]);
});

test("a CoreDNS rollout is done only when the new pods are Available", () => {
  assert.equal(rolloutDone(undefined), false);
  assert.equal(rolloutDone({ status: { updatedReplicas: 1, availableReplicas: 1 } }), true);
  assert.equal(rolloutDone({ spec: { replicas: 2 }, status: { updatedReplicas: 1, availableReplicas: 1 } }), false);
  assert.equal(
    rolloutDone({ metadata: { generation: 3 }, spec: { replicas: 1 }, status: { observedGeneration: 2, updatedReplicas: 1, availableReplicas: 1 } }),
    false,
  );
  assert.equal(
    rolloutDone({ metadata: { generation: 3 }, spec: { replicas: 1 }, status: { observedGeneration: 3, updatedReplicas: 1, availableReplicas: 1 } }),
    true,
  );
  assert.equal(rolloutDone({ metadata: { generation: 3 }, status: { updatedReplicas: 1, availableReplicas: 1 } }), true);
});

test("waitRollout polls until the Deployment is Available", async () => {
  let reads = 0;
  let slept = false;
  const cluster = {
    getDeployment: async () => {
      reads += 1;
      if (reads === 1) {
        return { spec: { replicas: 1 }, status: { updatedReplicas: 0, availableReplicas: 0 } };
      }
      return { spec: { replicas: 1 }, status: { updatedReplicas: 1, availableReplicas: 1 } };
    },
    sleep: async () => {
      slept = true;
    },
  } as unknown as Cluster;
  await waitRollout(cluster, "kube-system", "coredns", 10_000);
  assert.equal(slept, true);
  await assert.rejects(
    waitRollout(
      {
        getDeployment: async () => ({ spec: { replicas: 1 } }),
        sleep: async () => undefined,
      } as unknown as Cluster,
      "kube-system",
      "coredns",
      0,
    ),
    /rollout did not finish/,
  );
});

test("a missing CoreDNS Deployment fails after the ConfigMap write", async () => {
  const { cluster: fake, recorded } = cluster({
    configMap: { data: {} },
    deployment: undefined,
  });
  await assert.rejects(reconcileCoreDns(fake, env()), /coredns Deployment is missing/);
  assert.equal(recorded.patched.length, 1);
  assert.equal(recorded.restarted.length, 0);
});

const savedCluster = runtime.cluster;
const savedEnv = {
  IN_CLUSTER_DNS: process.env.IN_CLUSTER_DNS,
  DOMAIN: process.env.DOMAIN,
  PASSTHROUGH_HOSTS: process.env.PASSTHROUGH_HOSTS,
};

afterEach(() => {
  runtime.cluster = savedCluster;
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
});

test("the capability reconciles the ConfigMap and the three gateway Services", () => {
  const registered = CoreDns as unknown as {
    bindings: {
      event: string;
      isWatch?: boolean;
      isQueue?: boolean;
      filters: { namespaces: string[]; name: string };
      kind: { kind: string };
    }[];
    namespaces: string[];
  };
  assert.deepEqual(registered.namespaces, [
    "kube-system",
    "istio-passthrough-gateway",
    "istio-admin-gateway",
    "istio-tenant-gateway",
  ]);
  assert.equal(registered.bindings.length, 4);
  assert.equal(registered.bindings[0].kind.kind, "ConfigMap");
  assert.equal(registered.bindings[0].filters.name, "coredns-custom");
  assert.deepEqual(registered.bindings[0].filters.namespaces, ["kube-system"]);
  assert.equal(registered.bindings[0].isWatch, true);
  assert.equal(registered.bindings[0].isQueue, true);
  assert.equal(registered.bindings[0].event, "CREATEORUPDATE");
  const services = registered.bindings.slice(1).map(binding => binding.filters.name);
  assert.deepEqual(services, [
    "passthrough-ingressgateway",
    "admin-ingressgateway",
    "tenant-ingressgateway",
  ]);
});

test("onCoreDns reads the process env and the live client slot", async () => {
  process.env.IN_CLUSTER_DNS = "false";
  let called = false;
  runtime.cluster = {
    getConfigMap: async () => {
      called = true;
      return undefined;
    },
  } as unknown as Cluster;
  await onCoreDns();
  assert.equal(called, false);
});
