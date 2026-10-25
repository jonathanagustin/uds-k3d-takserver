// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type { Cluster, JsonOp } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import { INIT_NAME, type PodLike } from "./oidc-render.ts";
import { onDeployment, onIgnite, Workload } from "./workload-capability.ts";
import {
  deploymentOps,
  enqueueIgnite,
  issuerHost,
  preparePod,
  reconcileDeployment,
  reconcileIgnite,
  resetIgniteQueue,
  shapeDeployment,
  tuneIgniteXml,
  waitGone,
  waitMode,
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
  const current = deploy("takserver-api");
  const next = shaped("takserver-api");
  const ops = deploymentOps(current, next);
  assert.equal(ops.some(op => op.path === "/spec/progressDeadlineSeconds" && op.op === "add"), true);
  assert.equal(ops.some(op => op.path === "/spec/strategy" && op.op === "add"), true);
  const rolling: WorkloadDeploy = {
    ...current,
    spec: { ...current.spec, progressDeadlineSeconds: 600, strategy: { type: "RollingUpdate", rollingUpdate: { maxUnavailable: 1 } } },
  };
  const replaced = deploymentOps(rolling, next);
  assert.equal(replaced.find(op => op.path === "/spec/progressDeadlineSeconds")?.op, "replace");
  assert.equal(replaced.find(op => op.path === "/spec/strategy")?.op, "replace");
  assert.deepEqual(deploymentOps({}, {}), [] as JsonOp[]);
  const added = deploymentOps({ spec: { progressDeadlineSeconds: 1200, strategy: { type: "Recreate" } } }, next);
  assert.equal(added.find(op => op.path === "/spec/template")?.op, "add");
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

function igniteCluster(opts: {
  xml?: string;
  automount?: boolean;
  annotations?: Record<string, string>;
  sts?: boolean;
  listPods?: () => Promise<{ metadata?: { deletionTimestamp?: string }; status?: { phase?: string } }[]>;
}) {
  const calls: string[] = [];
  const ops: JsonOp[] = [];
  const cluster = {
    getConfigMap: async () => (opts.xml === undefined ? undefined : { data: { "ignite-config.xml": opts.xml } }),
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
  return { cluster: cluster as unknown as Cluster, calls, ops };
}

test("ignite reconcile is a no-op when the XML and automount are already set", async () => {
  const tuned = tuneIgniteXml(IGNITE_XML);
  const { cluster, calls } = igniteCluster({ xml: tuned, automount: true });
  await reconcileIgnite("ADDED", cluster);
  assert.deepEqual(calls, []);
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

test("an ignite change scales consumers down, patches, restarts, and scales back up", async () => {
  const { cluster, calls, ops } = igniteCluster({ xml: IGNITE_XML, automount: false, annotations: { kept: "yes" } });
  await reconcileIgnite("ADDED", cluster);
  assert.deepEqual(calls.slice(0, 4), [
    "scale takserver-plugins 0",
    "scale takserver-api 0",
    "scale takserver-messaging 0",
    "scale takserver-config 0",
  ]);
  assert.equal(calls.includes("patch-xml"), true);
  assert.equal(calls.includes("patch-sts"), true);
  assert.equal(ops[0]?.op, "replace");
  assert.equal(calls.includes("restart true"), true);
  assert.deepEqual(calls.slice(-4), [
    "scale takserver-config 1",
    "scale takserver-messaging 1",
    "scale takserver-api 1",
    "scale takserver-plugins 1",
  ]);
});

test("a new automount field is added, and a failure still scales the consumers back", async () => {
  const added = igniteCluster({ xml: tuneIgniteXml(IGNITE_XML) });
  await reconcileIgnite("ADDED", added.cluster);
  assert.equal(added.ops[0]?.op, "add");
  assert.equal(added.calls.includes("patch-xml"), false);
  const failing = igniteCluster({
    xml: IGNITE_XML,
    automount: true,
    listPods: async () => {
      throw new Error("list failed");
    },
  });
  await assert.rejects(reconcileIgnite("ADDED", failing.cluster), /list failed/);
  assert.equal(failing.calls.includes("scale takserver-config 1"), true);
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

test("the capability watches the four deployments, the ignite config, and the StatefulSet", async () => {
  const registered = Workload as unknown as {
    bindings: { filters: { name: string }; kind: { kind: string } }[];
  };
  assert.deepEqual(
    registered.bindings.map(binding => `${binding.kind.kind}/${binding.filters.name}`),
    [
      "Deployment/takserver-config",
      "Deployment/takserver-messaging",
      "Deployment/takserver-api",
      "Deployment/takserver-plugins",
      "ConfigMap/takserver-ignite-configmap",
      "StatefulSet/takserver-ignite",
    ],
  );
  delete process.env.RENDER_IMAGE;
  runtime.cluster = recordedCluster().cluster;
  await onDeployment(deploy("postgres"), "ADDED");
  runtime.cluster = igniteCluster({ xml: tuneIgniteXml(IGNITE_XML), automount: true }).cluster;
  await onIgnite({}, "ADDED");
});
