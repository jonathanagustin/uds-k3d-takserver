// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster, JsonOp } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { INIT_NAME, type PodLike } from "./oidc-render.ts";
import {
  onDeployment,
  onDeploymentMutate,
  onIgnite,
  onIgniteConfigMutate,
  onIgniteSetMutate,
  Workload,
} from "./workload-capability.ts";
import {
  deploymentOps,
  desiredReplicas,
  enqueueIgnite,
  issuerHost,
  prepareDeployment,
  prepareIgniteConfigMap,
  prepareIgniteStatefulSet,
  preparePod,
  reconcileDeployment,
  reconcileIgnite,
  resetIgniteQueue,
  shapeDeployment,
  STARTUP_ANNOTATION,
  tuneIgniteXml,
  waitGone,
  waitMode,
  waitReady,
  type WorkloadDeploy,
  type WorkloadPodSpec,
} from "./workload.ts";

const IMAGE = "registry.example/takserver-config:1";
const CORE = 'configurationUri="https://sso.uds.dev/realms/uds/.well-known/openid-configuration"';
const SPI = '<property name="discoverySpi"><bean class="org.apache.ignite.spi.discovery.tcp.TcpDiscoverySpi"></bean></property>';

function deploy(name: string, spec: WorkloadPodSpec = { containers: [{ name }] }): WorkloadDeploy {
  return { metadata: { name, namespace: "takserver" }, spec: { template: { spec } } };
}

function shaped(name: string, issuer = "sso.uds.dev"): WorkloadDeploy {
  return shapeDeployment(deploy(name), { image: IMAGE, issuerHost: issuer }).next;
}

test("wait modes match the script", () => {
  assert.equal(waitMode("takserver-config"), "ignite");
  assert.equal(waitMode("takserver-messaging"), "config");
  assert.equal(waitMode("takserver-api"), "config");
  assert.equal(waitMode("takserver-plugins"), "services");
});

test("the issuer host is the configurationUri host", () => {
  assert.equal(issuerHost(CORE), "sso.uds.dev");
  assert.throws(() => issuerHost("<config/>"), /configurationUri/);
});

test("ignite XML gains the two SPI timeouts and keeps localAddress unset", () => {
  const once = tuneIgniteXml(SPI);
  assert.match(once, /networkTimeout" value="15000"/);
  assert.match(once, /failureDetectionTimeout" value="30000"/);
  assert.equal(tuneIgniteXml(once), once);
  assert.throws(() => tuneIgniteXml("<property name=\"discoverySpi\"></property>"), /TcpDiscoverySpi/);
  assert.throws(() => tuneIgniteXml(SPI.replace("discoverySpi", "other")), /discoverySpi/);
  assert.throws(() => tuneIgniteXml(`${once}<property name="localAddress" value="0.0.0.0"/>`), /2\.17/);
  assert.throws(() => tuneIgniteXml(`${once}<property name="enabled" value="false"/>`), /2\.17/);
});

test("each TAK deployment gets the script's startup shape, and a second pass is a no-op", () => {
  for (const name of ["takserver-config", "takserver-messaging", "takserver-api", "takserver-plugins"] as const) {
    const first = shapeDeployment(deploy(name, { containers: [{ name }], hostAliases: [{ ip: "1.1.1.1" }] }), {
      image: IMAGE,
      issuerHost: "sso.uds.dev",
    });
    assert.equal(first.changed, true, name);
    const spec = first.next.spec!;
    assert.equal(spec.progressDeadlineSeconds, 1200);
    assert.deepEqual(spec.strategy, { type: "Recreate" });
    assert.equal(spec.template?.metadata?.labels?.["uds.dev/oidc-reload"], "takserver");
    assert.equal(spec.template?.spec?.automountServiceAccountToken, true);
    const inits = spec.template?.spec?.initContainers ?? [];
    assert.equal(inits[0]?.name, "wait-deps");
    assert.equal(inits[0]?.image, IMAGE);
    assert.deepEqual(inits[0]?.command, ["bash", "/scripts/wait-deps.sh", waitMode(name)]);
    const second = shapeDeployment(first.next, { image: IMAGE, issuerHost: "sso.uds.dev" });
    assert.equal(second.changed, false, name);
  }
});

test("messaging and the API import the issuer trust store", () => {
  for (const name of ["takserver-messaging", "takserver-api"] as const) {
    const spec = shaped(name).spec?.template?.spec;
    const inits = spec?.initContainers ?? [];
    assert.deepEqual(
      inits.map(init => init.name),
      ["wait-deps", "import-trust"],
    );
    assert.equal(inits[1]?.env?.[0]?.value, "sso.uds.dev");
    const main = spec?.containers?.[0];
    assert.match(String(main?.env?.[0]?.value), /trustStore=\/trust\/cacerts/);
    assert.equal(main?.volumeMounts?.[0]?.mountPath, "/trust");
    assert.equal(spec?.volumes?.some(volume => volume.name === "uds-trust"), true);
  }
  const api = shaped("takserver-api").spec?.template?.spec?.containers?.[0];
  const startup = api?.startupProbe as { tcpSocket: { port: number }; failureThreshold: number };
  assert.equal(startup.tcpSocket.port, 8443);
  assert.equal(startup.failureThreshold, 80);
  const messaging = shaped("takserver-messaging").spec?.template?.spec?.containers?.[0];
  const live = messaging?.livenessProbe as { tcpSocket: { port: number } };
  assert.equal(live.tcpSocket.port, 8089);
  const ready = api?.readinessProbe as { timeoutSeconds: number };
  assert.ok(ready.timeoutSeconds > 3);
});

test("the API hostAlias is removed and a messaging alias is not", () => {
  const api = shapeDeployment(deploy("takserver-api", { containers: [{ name: "api" }], hostAliases: [{ ip: "10.0.0.1" }] }), {
    image: IMAGE,
    issuerHost: "sso.uds.dev",
  });
  assert.equal(api.next.spec?.template?.spec?.hostAliases, undefined);
  const messaging = shapeDeployment(
    deploy("takserver-messaging", { containers: [{ name: "messaging" }], hostAliases: [{ ip: "10.0.0.2" }] }),
    { image: IMAGE, issuerHost: "sso.uds.dev" },
  );
  assert.deepEqual(messaging.next.spec?.template?.spec?.hostAliases, [{ ip: "10.0.0.2" }]);
});

test("config probes exec the readiness script and plugins get a 384Mi limit", () => {
  const config = shaped("takserver-config").spec?.template?.spec?.containers?.[0];
  const startup = config?.startupProbe as { exec: { command: string[] } };
  assert.deepEqual(startup.exec.command, ["/config-readiness.sh"]);
  assert.equal(config?.livenessProbe, undefined);
  const plugins = shaped("takserver-plugins").spec?.template?.spec?.containers?.[0];
  assert.equal(plugins?.resources?.requests?.memory, "128Mi");
  assert.equal(plugins?.resources?.limits?.memory, "384Mi");
  const again = shapeDeployment(shaped("takserver-plugins"), { image: IMAGE });
  assert.equal(again.changed, false);
});

test("a wrong trust env, mount, and volume are corrected", () => {
  const current = deploy("takserver-api", {
    containers: [
      {
        name: "api",
        env: [{ name: "JAVA_TOOL_OPTIONS", value: "old" }],
        volumeMounts: [{ name: "jvm-trust", mountPath: "/wrong" }],
      },
    ],
    volumes: [{ name: "oidc-script", configMap: { name: "other" } }, { name: "kept", emptyDir: {} }],
  });
  const next = shapeDeployment(current, { image: IMAGE, issuerHost: "sso.uds.dev" });
  const spec = next.next.spec?.template?.spec;
  assert.equal(spec?.containers?.[0]?.env?.[0]?.value?.includes("trustStore"), true);
  assert.equal(spec?.containers?.[0]?.volumeMounts?.[0]?.mountPath, "/trust");
  const script = spec?.volumes?.find(volume => volume.name === "oidc-script");
  assert.equal((script?.configMap as { name: string }).name, "takserver-oidc-render");
  assert.equal(spec?.volumes?.some(volume => volume.name === "kept"), true);
});

test("wait-deps is moved in front of any other init container", () => {
  const current = deploy("takserver-config", {
    initContainers: [{ name: "other" }, { name: "wait-deps", image: "old" }],
    containers: [{ name: "config" }],
  });
  const next = shapeDeployment(current, { image: IMAGE });
  assert.deepEqual(
    next.next.spec?.template?.spec?.initContainers?.map(init => init.name),
    ["wait-deps", "other"],
  );
  assert.equal(next.next.spec?.template?.spec?.initContainers?.[0]?.image, IMAGE);
});

test("a deployment without a container is an error", () => {
  assert.throws(() => shapeDeployment(deploy("takserver-config", {}), { image: IMAGE }), /no container/);
  assert.throws(() => shapeDeployment(deploy("takserver-api"), { image: IMAGE }), /configurationUri/);
});

test("an empty image is an error, and other deployments are ignored", () => {
  assert.throws(() => shapeDeployment(deploy("takserver-config"), { image: "" }), /RENDER_IMAGE/);
  const other = shapeDeployment(deploy("takserver-postgresql"), { image: IMAGE });
  assert.equal(other.changed, false);
});

test("deployment patch ops add missing fields and replace a rolling update", () => {
  const current = deploy("takserver-api", {
    containers: [{ name: "api", image: "helm.example/api:1", env: [{ name: "KEEP", value: "yes" }] }],
    hostAliases: [{ ip: "10.0.0.1" }],
    volumes: [{ name: "kept", emptyDir: {} }, { name: "oidc-script", configMap: { name: "other" } }],
    initContainers: [{ name: "other" }, { name: "wait-deps", image: "old" }],
    automountServiceAccountToken: false,
  });
  current.spec!.template!.metadata = { labels: { app: "takserver-api", "uds.dev/oidc-reload": "stale" } };
  const next = shaped("takserver-api");
  const ops = deploymentOps(current, next);
  assert.equal(ops.some(op => op.path === "/spec/template"), false);
  assert.equal(ops.some(op => op.path === "/spec/progressDeadlineSeconds" && op.op === "add"), true);
  assert.equal(ops.some(op => op.path === "/spec/strategy" && op.op === "add"), true);
  assert.equal(ops.some(op => op.path.endsWith("/uds.dev~1oidc-reload") && op.op === "replace" && op.value === "takserver"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/automountServiceAccountToken" && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/hostAliases" && op.op === "remove"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/volumes/-"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/volumes/1" && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/initContainers" && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path === "/spec/template/spec/containers/0/env/-"), true);
  assert.equal(JSON.stringify(ops).includes("helm.example/api"), false);
  assert.equal(JSON.stringify(ops).includes("\"KEEP\""), false);
  const rolling: WorkloadDeploy = {
    ...current,
    spec: { ...current.spec, progressDeadlineSeconds: 600, strategy: { type: "RollingUpdate", rollingUpdate: { maxUnavailable: 1 } } },
  };
  const replaced = deploymentOps(rolling, next);
  assert.equal(replaced.find(op => op.path === "/spec/progressDeadlineSeconds")?.op, "replace");
  assert.equal(replaced.find(op => op.path === "/spec/strategy")?.op, "replace");
  assert.equal(replaced.some(op => op.path === "/spec/template"), false);
  assert.deepEqual(deploymentOps({}, {}), [] as JsonOp[]);
  const added = deploymentOps({ spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" } } }, next);
  assert.equal(added.find(op => op.path === "/spec/template")?.op, "add");
  const keyed = deploy("takserver-config");
  keyed.spec!.template!.metadata = { labels: { app: "takserver-config" } };
  const keyAdd = deploymentOps(keyed, shaped("takserver-config"));
  assert.equal(keyAdd.some(op => op.path.endsWith("/uds.dev~1oidc-reload") && op.op === "add"), true);
  const labeled = deploy("takserver-config");
  labeled.spec!.template!.metadata = { annotations: { kept: "yes" } };
  const labelAdd = deploymentOps(labeled, shaped("takserver-config"));
  assert.equal(labelAdd.some(op => op.path === "/spec/template/metadata/labels" && op.op === "add"), true);
  const bareMeta = deploy("takserver-config");
  delete bareMeta.spec!.template!.metadata;
  const metaAdd = deploymentOps(bareMeta, shaped("takserver-config"));
  assert.equal(metaAdd.some(op => op.path === "/spec/template/metadata" && op.op === "add"), true);
  const held = shaped("takserver-api");
  held.spec!.template!.spec!.containers![0]!.startupProbe = { tcpSocket: { port: 1 } };
  const probe = deploymentOps(held, shaped("takserver-api"));
  assert.equal(probe.some(op => op.path.endsWith("/startupProbe") && op.op === "replace"), true);
  assert.equal(probe.some(op => op.path.includes("oidc-reload")), false);
  const plugins = deploy("takserver-plugins", {
    containers: [{ name: "plugins", resources: { requests: { cpu: "10m" }, limits: { cpu: "20m" } } }],
  });
  const memory = deploymentOps(plugins, shaped("takserver-plugins"));
  assert.equal(memory.some(op => op.path.endsWith("/requests/memory") && op.op === "add"), true);
  assert.equal(memory.some(op => op.path.endsWith("/limits/memory") && op.op === "add"), true);
  assert.equal(JSON.stringify(memory).includes("10m"), false);
  const noSpec = deploy("takserver-config");
  delete noSpec.spec!.template!.spec;
  const specAdd = deploymentOps(noSpec, shaped("takserver-config"));
  assert.equal(specAdd.some(op => op.path === "/spec/template/spec" && op.op === "add"), true);
  const idle = deploymentOps(
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: { spec: { containers: [{ name: "x" }] } } } },
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: { spec: { containers: [{ name: "x" }] } } } },
  );
  assert.deepEqual(idle, [] as JsonOp[]);
  const noTemplate = deploymentOps(
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" } } },
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" } } },
  );
  assert.deepEqual(noTemplate, [] as JsonOp[]);
});

function recordedCluster(over: Partial<Cluster> = {}): { cluster: Cluster; calls: string[] } {
  const calls: string[] = [];
  const cluster = {
    getConfigMap: async () => {
      calls.push("getConfigMap");
      return { data: { "CoreConfig.xml": CORE } };
    },
    patchDeployment: async () => {
      calls.push("patchDeployment");
    },
    getStatefulSet: async () => undefined,
    listPods: async () => [],
    scaleDeployment: async (_ns: string, name: string, replicas: number) => {
      calls.push(`scale ${name} ${replicas}`);
    },
    sleep: async () => undefined,
    ...over,
  };
  return { cluster: cluster as unknown as Cluster, calls };
}

test("reconcile patches an API deployment from CoreConfig and skips a finished one", async () => {
  const { cluster, calls } = recordedCluster();
  await reconcileDeployment(deploy("takserver-api"), "ADDED", cluster, { RENDER_IMAGE: IMAGE });
  assert.equal(calls.includes("patchDeployment"), true);
  calls.length = 0;
  const done = shaped("takserver-api");
  await reconcileDeployment(done, "MODIFIED", cluster, { RENDER_IMAGE: IMAGE });
  assert.equal(calls.includes("patchDeployment"), false);
});

test("a missing image and a missing namespace still reconcile", async () => {
  const { cluster, calls } = recordedCluster();
  await assert.rejects(reconcileDeployment(deploy("takserver-plugins"), "ADDED", cluster, {}), /RENDER_IMAGE/);
  const unnamed = deploy("takserver-config");
  delete unnamed.metadata?.namespace;
  await reconcileDeployment(unnamed, "ADDED", cluster, { RENDER_IMAGE: IMAGE });
  assert.equal(calls.includes("patchDeployment"), true);
});

test("config does not read CoreConfig, and a delete is ignored", async () => {
  const { cluster, calls } = recordedCluster({
    getConfigMap: async () => {
      throw new Error("should not read");
    },
  });
  await reconcileDeployment(deploy("takserver-config"), "ADDED", cluster, { RENDER_IMAGE: IMAGE });
  assert.equal(calls.includes("patchDeployment"), true);
  calls.length = 0;
  await reconcileDeployment(deploy("takserver-config"), "DELETED", cluster, { RENDER_IMAGE: IMAGE });
  await reconcileDeployment(deploy("postgres"), "ADDED", cluster, { RENDER_IMAGE: IMAGE });
  assert.equal(calls.length, 0);
});

test("a missing issuer fails the API reconcile before a patch", async () => {
  const { cluster, calls } = recordedCluster({
    getConfigMap: async () => ({}),
  });
  await assert.rejects(
    reconcileDeployment(deploy("takserver-api"), "ADDED", cluster, { RENDER_IMAGE: IMAGE }),
    /configurationUri/,
  );
  assert.equal(calls.includes("patchDeployment"), false);
});

test("preparePod leaves config and plugins to wait without reading CoreConfig", async () => {
  const { cluster } = recordedCluster({
    getConfigMap: async () => {
      throw new Error("should not read");
    },
  });
  for (const app of ["takserver-config", "takserver-plugins"]) {
    const pod: PodLike = { metadata: { labels: { app } }, spec: { containers: [{ name: app }] } };
    await preparePod(pod, { RENDER_IMAGE: IMAGE }, cluster);
    assert.equal(pod.spec?.initContainers?.[0]?.name, "wait-deps");
  }
});

test("preparePod orders wait-deps, import-trust, then the OIDC render", async () => {
  const { cluster } = recordedCluster();
  const pod: PodLike = { metadata: { labels: { app: "takserver-api" } }, spec: { containers: [{ name: "api" }] } };
  await preparePod(pod, { RENDER_IMAGE: IMAGE }, cluster);
  assert.deepEqual(
    pod.spec?.initContainers?.map(init => init.name),
    ["wait-deps", "import-trust", INIT_NAME],
  );
});

test("owned fields patch in place when the prefix is already there", () => {
  const current = shaped("takserver-api");
  const spec = current.spec!.template!.spec!;
  spec.initContainers![0]!.image = "old";
  spec.containers![0]!.env![0]!.value = "old";
  spec.containers![0]!.volumeMounts![0]!.mountPath = "/wrong";
  spec.volumes = [
    { name: "oidc-script", configMap: { name: "takserver-oidc-render" }, extra: true },
    { name: "jvm-trust", emptyDir: {} },
    { name: "uds-trust", configMap: { name: "uds-trust-bundle", optional: true } },
  ];
  const ops = deploymentOps(current, shaped("takserver-api"));
  assert.equal(ops.some(op => op.path === "/spec/template/spec/initContainers/0" && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path.endsWith("/env/0/value") && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path.endsWith("/volumeMounts/0") && op.op === "replace"), true);
  assert.equal(ops.some(op => op.path.includes("/volumes")), false);
  const mountless = shaped("takserver-api");
  delete mountless.spec!.template!.spec!.containers![0]!.volumeMounts;
  const addedMount = deploymentOps(mountless, shaped("takserver-api"));
  assert.equal(addedMount.some(op => op.path.endsWith("/volumeMounts") && op.op === "add"), true);
  const withMount = shaped("takserver-api");
  withMount.spec!.template!.spec!.containers![0]!.volumeMounts = [{ name: "other", mountPath: "/other" }];
  const appended = deploymentOps(withMount, shaped("takserver-api"));
  assert.equal(appended.some(op => op.path.endsWith("/volumeMounts/-")), true);
  const plugins = deploy("takserver-plugins", { containers: [{ name: "plugins" }] });
  plugins.spec!.template!.spec!.containers![0]!.resources = { limits: { cpu: "20m" } };
  const limits = deploymentOps(plugins, {
    spec: {
      progressDeadlineSeconds: 1200,
      strategy: { type: "Recreate" },
      template: { spec: { containers: [{ name: "plugins", resources: { limits: { memory: "384Mi" } } }] } },
    },
  });
  assert.equal(limits.some(op => op.path.endsWith("/limits/memory") && op.op === "add"), true);
  const requestsOnly = deploy("takserver-plugins", { containers: [{ name: "plugins", resources: { requests: { memory: "64Mi" } } }] });
  const requests = deploymentOps(requestsOnly, {
    spec: {
      progressDeadlineSeconds: 1200,
      strategy: { type: "Recreate" },
      template: { spec: { containers: [{ name: "plugins", resources: { requests: { memory: "128Mi" } } }] } },
    },
  });
  assert.equal(requests.some(op => op.path.endsWith("/requests/memory") && op.op === "replace"), true);
  const emptyContainers = deploy("takserver-config");
  emptyContainers.spec!.template!.spec!.containers = [];
  const containerAdd = deploymentOps(emptyContainers, shaped("takserver-config"));
  assert.equal(containerAdd.some(op => op.path === "/spec/template/spec/containers" && op.op === "add"), true);
  const barePlugins = deploymentOps(deploy("takserver-plugins"), shaped("takserver-plugins"));
  assert.equal(barePlugins.some(op => op.path.endsWith("/resources") && op.op === "add"), true);
  const noRequests = deploy("takserver-plugins", { containers: [{ name: "plugins", resources: { limits: { memory: "384Mi" } } }] });
  const addedRequests = deploymentOps(noRequests, shaped("takserver-plugins"));
  assert.equal(addedRequests.some(op => op.path.endsWith("/resources/requests") && op.op === "add"), true);
  const noLimits = deploy("takserver-plugins", { containers: [{ name: "plugins", resources: { requests: { memory: "128Mi" } } }] });
  const addedLimits = deploymentOps(noLimits, shaped("takserver-plugins"));
  assert.equal(addedLimits.some(op => op.path.endsWith("/resources/limits") && op.op === "add"), true);
  const wrongLimits = deploy("takserver-plugins", {
    containers: [{ name: "plugins", resources: { requests: { memory: "128Mi" }, limits: { memory: "64Mi" } } }],
  });
  const replacedLimits = deploymentOps(wrongLimits, shaped("takserver-plugins"));
  assert.equal(replacedLimits.some(op => op.path.endsWith("/limits/memory") && op.op === "replace"), true);
  const emptySpec = deploymentOps(
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: { spec: { containers: [{ name: "x" }] } } } },
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: {} } },
  );
  assert.deepEqual(emptySpec, [] as JsonOp[]);
  const noContainers = deploymentOps(
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: { spec: { containers: [{ name: "x" }] } } } },
    { spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" }, template: { spec: {} } } },
  );
  assert.deepEqual(noContainers, [] as JsonOp[]);
});

test("preparePod retries a transient CoreConfig read and still rejects a missing issuer", async () => {
  let reads = 0;
  let sleeps = 0;
  const flaky = recordedCluster({
    getConfigMap: async () => {
      reads += 1;
      if (reads < 3) {
        throw new Error("busy");
      }
      return { data: { "CoreConfig.xml": CORE } };
    },
    sleep: async () => {
      sleeps += 1;
    },
  });
  const pod: PodLike = { metadata: { labels: { app: "takserver-api" } }, spec: { containers: [{ name: "api" }] } };
  await preparePod(pod, { RENDER_IMAGE: IMAGE }, flaky.cluster);
  assert.equal(pod.spec?.initContainers?.[1]?.name, "import-trust");
  assert.equal(sleeps, 2);
  const down = recordedCluster({
    getConfigMap: async () => {
      throw new Error("still busy");
    },
    sleep: async () => undefined,
  });
  await assert.rejects(preparePod(pod, { RENDER_IMAGE: IMAGE }, down.cluster), /still busy/);
  const broken = recordedCluster({
    getConfigMap: async () => {
      throw "busy";
    },
  });
  await assert.rejects(preparePod(pod, { RENDER_IMAGE: IMAGE }, broken.cluster), /CoreConfig read failed/);
  let missed = 0;
  const missing = recordedCluster({
    getConfigMap: async () => ({}),
    sleep: async () => {
      missed += 1;
    },
  });
  await assert.rejects(preparePod(pod, { RENDER_IMAGE: IMAGE }, missing.cluster), /configurationUri/);
  assert.equal(missed, 0);
});

test("preparePod rejects a missing image and ignores pods that do not read CoreConfig", async () => {
  const pod: PodLike = { metadata: { labels: { app: "takserver-ignite" } }, spec: { containers: [{ name: "ignite" }] } };
  const before = structuredClone(pod);
  await assert.rejects(preparePod(pod, {}, recordedCluster().cluster), /RENDER_IMAGE/);
  assert.deepEqual(pod, before);
  await preparePod(pod, { RENDER_IMAGE: IMAGE }, recordedCluster({
    getConfigMap: async () => {
      throw new Error("should not read");
    },
  }).cluster);
  assert.equal(pod.spec?.initContainers, undefined);
});

test("waitGone returns when the pods are gone and fails when they are not", async () => {
  await waitGone(recordedCluster().cluster, "takserver-api", 1_000);
  let reads = 0;
  let slept = false;
  const cluster = {
    listPods: async () => {
      reads += 1;
      if (reads === 1) {
        return [{ metadata: { name: "still" }, status: { phase: "Running" } }];
      }
      return [{ metadata: { deletionTimestamp: "now" } }, { status: { phase: "Succeeded" } }];
    },
    sleep: async () => {
      slept = true;
    },
  } as unknown as Cluster;
  await waitGone(cluster, "takserver-api", 10_000);
  assert.equal(slept, true);
  await assert.rejects(
    waitGone(
      { listPods: async () => [{ metadata: { name: "stuck" } }], sleep: async () => undefined } as unknown as Cluster,
      "takserver-api",
      0,
    ),
    /did not terminate/,
  );
});

const IGNITE_XML = `<property name="discoverySpi">\n    <bean class="org.apache.ignite.spi.discovery.tcp.TcpDiscoverySpi">\n    </bean>\n</property>`;

const TAK_NAMES = ["takserver-plugins", "takserver-api", "takserver-messaging", "takserver-config"] as const;

function igniteCluster(opts: {
  xml?: string;
  automount?: boolean;
  annotations?: Record<string, string>;
  sts?: boolean;
  replicas?: number;
  deployAnnotations?: Record<string, string>;
  missingDeployment?: boolean;
  omitReplicas?: boolean;
  startup?: { metadata?: { annotations?: Record<string, string> } };
  ready?: boolean;
  listPods?: () => Promise<{ metadata?: { deletionTimestamp?: string }; status?: { phase?: string } }[]>;
}) {
  const calls: string[] = [];
  const ops: JsonOp[] = [];
  const replicaOps: JsonOp[] = [];
  const counts = new Map<string, number>();
  const notes = new Map<string, Record<string, string>>();
  for (const name of TAK_NAMES) {
    if (!opts.omitReplicas) {
      counts.set(name, opts.replicas ?? 1);
    }
    if (opts.deployAnnotations) {
      notes.set(name, { ...opts.deployAnnotations });
    }
  }
  const cluster = {
    getConfigMap: async (_ns: string, name: string) => {
      if (name === "takserver-startup") {
        return opts.startup;
      }
      if (opts.xml === undefined) {
        return undefined;
      }
      return { data: { "ignite-config.xml": opts.xml } };
    },
    deleteConfigMap: async () => {
      calls.push("delete-startup");
    },
    applyConfigMap: async () => {
      calls.push("stamp");
    },
    getDeployment: async (_ns: string, name: string) => {
      if (opts.missingDeployment) {
        return undefined;
      }
      if (!counts.has(name)) {
        return { metadata: { name, annotations: notes.get(name) }, spec: {}, status: { availableReplicas: 1, updatedReplicas: 1 } };
      }
      const replicas = counts.get(name) ?? 0;
      const ready = opts.ready !== false;
      return {
        metadata: { name, annotations: notes.get(name) },
        spec: { replicas },
        status: {
          availableReplicas: ready ? replicas : 0,
          updatedReplicas: ready ? replicas : 0,
        },
      };
    },
    patchDeployment: async (_ns: string, name: string, patch: JsonOp[]) => {
      replicaOps.push(...patch);
      calls.push(`annotate ${name}`);
      const current = { ...(notes.get(name) ?? {}) };
      for (const op of patch) {
        if (op.path === "/metadata/annotations" && typeof op.value === "object" && op.value) {
          Object.assign(current, op.value as Record<string, string>);
        } else if (typeof op.value === "string") {
          current["uds.dev/tak-replicas"] = op.value;
        }
      }
      notes.set(name, current);
    },
    getStatefulSet: async () => {
      if (opts.sts === false) {
        return undefined;
      }
      return {
        spec: {
          template: {
            metadata: opts.annotations ? { annotations: opts.annotations } : {},
            spec: opts.automount === undefined ? {} : { automountServiceAccountToken: opts.automount },
          },
        },
      };
    },
    scaleDeployment: async (_ns: string, name: string, replicas: number) => {
      calls.push(`scale ${name} ${replicas}`);
      counts.set(name, replicas);
    },
    listPods: opts.listPods ?? (async () => []),
    patchConfigMapKey: async () => {
      calls.push("patch-xml");
    },
    patchStatefulSet: async (_ns: string, _name: string, patch: JsonOp[]) => {
      ops.push(...patch);
      calls.push("patch-sts");
    },
    restartStatefulSet: async (_ns: string, _name: string, hasAnnotations: boolean) => {
      calls.push(`restart ${hasAnnotations}`);
    },
    sleep: async () => undefined,
  };
  return { cluster: cluster as unknown as Cluster, calls, ops, replicaOps };
}

test("an already tuned ignite config stamps startup once the deployments are Available", async () => {
  const tuned = tuneIgniteXml(IGNITE_XML);
  const { cluster, calls } = igniteCluster({ xml: tuned, automount: true });
  await reconcileIgnite("ADDED", cluster);
  assert.deepEqual(calls, ["stamp"]);
  const again = igniteCluster({
    xml: tuned,
    automount: true,
    startup: { metadata: { annotations: { [STARTUP_ANNOTATION]: "complete" } } },
  });
  await reconcileIgnite("ADDED", again.cluster);
  assert.deepEqual(again.calls, []);
});

test("desired replica counts prefer the live spec, then the annotation", () => {
  assert.equal(desiredReplicas({}), 1);
  assert.equal(desiredReplicas({ spec: { replicas: 2 } }), 2);
  assert.equal(desiredReplicas({ spec: { replicas: 0 }, metadata: { annotations: { "uds.dev/tak-replicas": "3" } } }), 3);
  assert.equal(desiredReplicas({ spec: { replicas: 0 }, metadata: { annotations: { "uds.dev/tak-replicas": "nope" } } }), 0);
  assert.equal(desiredReplicas({ spec: { replicas: 0 } }), 0);
});

test("waitReady returns when the four deployments are Available", async () => {
  const names = ["takserver-config", "takserver-messaging", "takserver-api", "takserver-plugins"];
  let round = 0;
  let slept = false;
  const cluster = {
    getDeployment: async (_ns: string, name: string) => {
      if (round === 0 && name === "takserver-api") {
        return { spec: { replicas: 1 }, status: { availableReplicas: 0, updatedReplicas: 1 } };
      }
      if (round === 1 && name === "takserver-api") {
        return { spec: { replicas: 1 }, status: { availableReplicas: 1, updatedReplicas: 0 } };
      }
      return { spec: { replicas: 1 }, status: { availableReplicas: 1, updatedReplicas: 1 } };
    },
    sleep: async () => {
      slept = true;
      round += 1;
    },
  } as unknown as Cluster;
  await waitReady(cluster, 10_000);
  assert.equal(slept, true);
  await assert.rejects(waitReady({ getDeployment: async () => undefined, sleep: async () => undefined } as unknown as Cluster, 0), /not Available/);
  assert.deepEqual(names.length, 4);
});

test("a missing config or StatefulSet waits", async () => {
  const missingXml = igniteCluster({ sts: true });
  await reconcileIgnite("ADDED", missingXml.cluster);
  assert.deepEqual(missingXml.calls, []);
  const missingSts = igniteCluster({ xml: IGNITE_XML, sts: false });
  await reconcileIgnite("ADDED", missingSts.cluster);
  assert.deepEqual(missingSts.calls, []);
  const { cluster, calls } = igniteCluster({ xml: IGNITE_XML, automount: true });
  await reconcileIgnite("DELETED", cluster);
  assert.deepEqual(calls, []);
});

test("an ignite change scales consumers down, patches, restarts, and restores their replica count", async () => {
  const { cluster, calls, ops, replicaOps } = igniteCluster({
    xml: IGNITE_XML,
    automount: false,
    annotations: { kept: "yes" },
    replicas: 2,
  });
  await reconcileIgnite("ADDED", cluster);
  assert.equal(calls[0], "delete-startup");
  assert.deepEqual(
    calls.filter(call => call.startsWith("scale")),
    [
      "scale takserver-plugins 0",
      "scale takserver-api 0",
      "scale takserver-messaging 0",
      "scale takserver-config 0",
      "scale takserver-config 2",
      "scale takserver-messaging 2",
      "scale takserver-api 2",
      "scale takserver-plugins 2",
    ],
  );
  assert.equal(calls.includes("patch-xml"), true);
  assert.equal(calls.includes("patch-sts"), true);
  assert.equal(ops[0]?.op, "replace");
  assert.equal(replicaOps[0]?.op, "add");
  assert.equal(calls.includes("restart true"), true);
  assert.equal(calls.at(-1), "stamp");
});

test("a new automount field is added, and a failed stop does not scale the consumers back", async () => {
  const added = igniteCluster({ xml: tuneIgniteXml(IGNITE_XML) });
  await reconcileIgnite("ADDED", added.cluster);
  assert.equal(added.ops[0]?.op, "add");
  assert.equal(added.calls.includes("patch-xml"), false);
  assert.equal(added.calls.includes("restart false"), true);
  assert.equal(added.calls.at(-1), "stamp");
  const failing = igniteCluster({
    xml: IGNITE_XML,
    automount: true,
    listPods: async () => {
      throw new Error("list failed");
    },
  });
  await assert.rejects(reconcileIgnite("ADDED", failing.cluster), /list failed/);
  assert.deepEqual(
    failing.calls.filter(call => call.startsWith("scale")),
    ["scale takserver-plugins 0"],
  );
  assert.equal(failing.calls.includes("stamp"), false);
  const remembered = igniteCluster({
    xml: IGNITE_XML,
    automount: true,
    replicas: 2,
    deployAnnotations: { "uds.dev/tak-replicas": "2" },
  });
  await reconcileIgnite("ADDED", remembered.cluster);
  assert.equal(remembered.calls.some(call => call.startsWith("annotate")), false);
  const replaced = igniteCluster({
    xml: IGNITE_XML,
    automount: true,
    replicas: 2,
    deployAnnotations: { kept: "yes", "uds.dev/tak-replicas": "1" },
  });
  await reconcileIgnite("ADDED", replaced.cluster);
  assert.equal(replaced.replicaOps.some(op => op.op === "replace"), true);
  const stopped = igniteCluster({
    xml: tuneIgniteXml(IGNITE_XML),
    automount: true,
    replicas: 0,
    deployAnnotations: { "uds.dev/tak-replicas": "2" },
  });
  await reconcileIgnite("ADDED", stopped.cluster);
  assert.deepEqual(stopped.calls.filter(call => call.startsWith("scale")), [
    "scale takserver-config 2",
    "scale takserver-messaging 2",
    "scale takserver-api 2",
    "scale takserver-plugins 2",
  ]);
  const extra = igniteCluster({
    xml: IGNITE_XML,
    automount: true,
    deployAnnotations: { kept: "yes" },
  });
  await reconcileIgnite("ADDED", extra.cluster);
  assert.equal(extra.replicaOps.some(op => op.op === "add" && op.path.includes("~1")), true);
  const unset = igniteCluster({ xml: tuneIgniteXml(IGNITE_XML), automount: true, omitReplicas: true });
  await reconcileIgnite("ADDED", unset.cluster);
  assert.equal(unset.calls.some(call => call.startsWith("scale")), false);
  const implied = igniteCluster({ xml: IGNITE_XML, automount: true, omitReplicas: true });
  await reconcileIgnite("ADDED", implied.cluster);
  assert.equal(implied.calls.includes("scale takserver-plugins 0"), true);
  assert.equal(implied.calls.includes("scale takserver-config 1"), true);
  const zero = igniteCluster({ xml: IGNITE_XML, automount: true, replicas: 0 });
  await reconcileIgnite("ADDED", zero.cluster);
  assert.equal(zero.calls.some(call => call.startsWith("scale")), false);
  assert.equal(zero.calls.at(-1), "stamp");
  const absent = igniteCluster({ xml: IGNITE_XML, automount: true, missingDeployment: true });
  await assert.rejects(reconcileIgnite("ADDED", absent.cluster, 0), /not Available/);
  assert.equal(absent.calls.includes("stamp"), false);
  assert.equal(absent.calls.some(call => call.startsWith("scale")), false);
});

test("bad ignite XML does not scale anything", async () => {
  const { cluster, calls } = igniteCluster({ xml: "<ignite></ignite>", automount: true });
  await assert.rejects(reconcileIgnite("ADDED", cluster), /TcpDiscoverySpi/);
  assert.deepEqual(calls, []);
});

test("a failed ignite pass does not block the next one", async () => {
  resetIgniteQueue();
  let ran = 0;
  const first = enqueueIgnite(async () => {
    ran += 1;
    throw new Error("nope");
  });
  const second = enqueueIgnite(async () => {
    ran += 1;
  });
  await assert.rejects(first, /nope/);
  await second;
  assert.equal(ran, 2);
});

const savedCluster = runtime.cluster;
const savedImage = process.env.RENDER_IMAGE;
afterEach(() => {
  runtime.cluster = savedCluster;
  if (savedImage === undefined) {
    delete process.env.RENDER_IMAGE;
  } else {
    process.env.RENDER_IMAGE = savedImage;
  }
  resetIgniteQueue();
});

test("admission writes the startup shape before the objects are stored", async () => {
  const config = deploy("takserver-config");
  await prepareDeployment(config, { RENDER_IMAGE: IMAGE }, recordedCluster().cluster);
  assert.equal(config.spec?.template?.spec?.initContainers?.[0]?.name, "wait-deps");
  assert.equal(config.spec?.strategy?.type, "Recreate");
  const again = structuredClone(config);
  await prepareDeployment(again, { RENDER_IMAGE: IMAGE }, recordedCluster().cluster);
  assert.deepEqual(again, config);
  await assert.rejects(prepareDeployment(deploy("takserver-config"), {}, recordedCluster().cluster), /RENDER_IMAGE/);
  const messaging = deploy("takserver-messaging");
  await prepareDeployment(messaging, { RENDER_IMAGE: IMAGE }, recordedCluster().cluster);
  assert.equal(messaging.spec?.template?.spec?.initContainers?.[1]?.name, "import-trust");
  const plugins = deploy("takserver-plugins");
  await prepareDeployment(plugins, { RENDER_IMAGE: IMAGE }, recordedCluster().cluster);
  assert.equal(plugins.spec?.template?.spec?.initContainers?.[0]?.name, "wait-deps");
  assert.equal(plugins.spec?.template?.spec?.initContainers?.some(item => item.name === "import-trust"), false);
  const other = deploy("postgres");
  await prepareDeployment(other, { RENDER_IMAGE: IMAGE }, recordedCluster().cluster);
  assert.equal(other.spec?.template?.spec?.initContainers, undefined);
  const xml = `<property name="discoverySpi">\n    <bean class="org.apache.ignite.spi.discovery.tcp.TcpDiscoverySpi">\n    </bean>\n</property>`;
  const configMap: { data?: Record<string, string> } = { data: { "ignite-config.xml": xml } };
  prepareIgniteConfigMap(configMap);
  assert.equal(configMap.data?.["ignite-config.xml"]?.includes('name="networkTimeout"'), true);
  const tuned = configMap.data?.["ignite-config.xml"] ?? "";
  prepareIgniteConfigMap(configMap);
  assert.equal(configMap.data?.["ignite-config.xml"], tuned);
  prepareIgniteConfigMap({});
  prepareIgniteConfigMap({ data: { other: "kept" } });
  assert.throws(() => prepareIgniteConfigMap({ data: { "ignite-config.xml": "<ignite></ignite>" } }), /TcpDiscoverySpi/);
  const sts: { spec?: { template?: { spec?: { automountServiceAccountToken?: boolean } } } } = {};
  prepareIgniteStatefulSet(sts);
  assert.equal(sts.spec?.template?.spec?.automountServiceAccountToken, true);
  prepareIgniteStatefulSet(sts);
  assert.equal(sts.spec?.template?.spec?.automountServiceAccountToken, true);
});

test("the capability admits and reconciles the four deployments, the ignite config, and the StatefulSet", async () => {
  const registered = Workload as unknown as {
    bindings: { isMutate?: boolean; filters: { name: string }; kind: { kind: string } }[];
  };
  assert.deepEqual(
    registered.bindings.map(binding => `${binding.isMutate ? "mutate" : "reconcile"}/${binding.kind.kind}/${binding.filters.name}`),
    [
      "mutate/Deployment/takserver-config",
      "reconcile/Deployment/takserver-config",
      "mutate/Deployment/takserver-messaging",
      "reconcile/Deployment/takserver-messaging",
      "mutate/Deployment/takserver-api",
      "reconcile/Deployment/takserver-api",
      "mutate/Deployment/takserver-plugins",
      "reconcile/Deployment/takserver-plugins",
      "mutate/ConfigMap/takserver-ignite-configmap",
      "reconcile/ConfigMap/takserver-ignite-configmap",
      "mutate/StatefulSet/takserver-ignite",
      "reconcile/StatefulSet/takserver-ignite",
    ],
  );
  delete process.env.RENDER_IMAGE;
  runtime.cluster = recordedCluster().cluster;
  await onDeployment(deploy("postgres"), "ADDED");
  process.env.RENDER_IMAGE = IMAGE;
  await onDeploymentMutate(deploy("takserver-config"));
  const admitted = { data: { "ignite-config.xml": IGNITE_XML } };
  onIgniteConfigMutate(admitted);
  assert.equal(admitted.data["ignite-config.xml"].includes('name="networkTimeout"'), true);
  const igniteSet: { spec?: { template?: { spec?: { automountServiceAccountToken?: boolean } } } } = {};
  onIgniteSetMutate(igniteSet);
  assert.equal(igniteSet.spec?.template?.spec?.automountServiceAccountToken, true);
  const callbacks = Workload as unknown as {
    bindings: { isMutate?: boolean; kind: { kind: string }; mutateCallback: (request: { Raw: object }) => unknown }[];
  };
  const seen = new Set<string>();
  for (const binding of callbacks.bindings) {
    if (!binding.isMutate || seen.has(binding.kind.kind)) {
      continue;
    }
    seen.add(binding.kind.kind);
    if (binding.kind.kind === "Deployment") {
      await binding.mutateCallback({ Raw: deploy("takserver-config") });
    } else if (binding.kind.kind === "ConfigMap") {
      const raw = { data: { "ignite-config.xml": IGNITE_XML } };
      binding.mutateCallback({ Raw: raw });
      assert.equal(raw.data["ignite-config.xml"].includes('name="failureDetectionTimeout"'), true);
    } else if (binding.kind.kind === "StatefulSet") {
      const raw: { spec?: { template?: { spec?: { automountServiceAccountToken?: boolean } } } } = {};
      binding.mutateCallback({ Raw: raw });
      assert.equal(raw.spec?.template?.spec?.automountServiceAccountToken, true);
    }
  }
  assert.deepEqual([...seen].sort(), ["ConfigMap", "Deployment", "StatefulSet"]);
  runtime.cluster = igniteCluster({ xml: tuneIgniteXml(IGNITE_XML), automount: true }).cluster;
  await onIgnite({}, "ADDED");
});
