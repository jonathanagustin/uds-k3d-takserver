// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// The startup shape that patch-oidc-pods.py used to strategic-merge onto the
// TAK Deployments after Helm. The upstream chart has no values for these
// init containers, probes, or the Ignite SPI timeouts. Admission applies the
// same pod shape, so a pod created before the Deployment reconcile still waits.

import type { Cluster, JsonOp, StatefulSetDoc } from "../cluster.ts";
import { addRender, RELOAD_LABEL, RELOAD_VALUE, type PodLike } from "./oidc-render.ts";

export const TAK_DEPLOYS = [
  "takserver-config",
  "takserver-messaging",
  "takserver-api",
  "takserver-plugins",
] as const;

export type TakDeploy = (typeof TAK_DEPLOYS)[number];

const STOP_ORDER = ["takserver-plugins", "takserver-api", "takserver-messaging", "takserver-config"] as const;
const START_ORDER = ["takserver-config", "takserver-messaging", "takserver-api", "takserver-plugins"] as const;

const IGNITE_CONFIGMAP = "takserver-ignite-configmap";
const IGNITE_STATEFULSET = "takserver-ignite";
const IGNITE_XML = "ignite-config.xml";
const SPI = '<bean class="org.apache.ignite.spi.discovery.tcp.TcpDiscoverySpi">';
const DISCOVERY = '<property name="discoverySpi">';
const TRUST_OPTS = "-Djavax.net.ssl.trustStore=/trust/cacerts -Djavax.net.ssl.trustStorePassword=changeit";

export interface ContainerDoc {
  name?: string;
  image?: string;
  imagePullPolicy?: string;
  command?: string[];
  env?: { name: string; value?: string }[];
  volumeMounts?: { name: string; mountPath: string; readOnly?: boolean }[];
  resources?: { requests?: { cpu?: string; memory?: string }; limits?: { cpu?: string; memory?: string } };
  startupProbe?: unknown;
  livenessProbe?: unknown;
  readinessProbe?: unknown;
}

export interface VolumeDoc {
  name: string;
  [key: string]: unknown;
}

export interface WorkloadPodSpec {
  automountServiceAccountToken?: boolean;
  hostAliases?: unknown;
  initContainers?: ContainerDoc[];
  containers?: ContainerDoc[];
  volumes?: VolumeDoc[];
}

export interface WorkloadDeploy {
  metadata?: { name?: string; namespace?: string; labels?: Record<string, string> };
  spec?: {
    progressDeadlineSeconds?: number;
    strategy?: { type?: string; rollingUpdate?: unknown };
    template?: {
      metadata?: { labels?: Record<string, string>; annotations?: Record<string, string> };
      spec?: WorkloadPodSpec;
    };
  };
}

export function isTakDeploy(name: string | undefined): name is TakDeploy {
  return name !== undefined && (TAK_DEPLOYS as readonly string[]).includes(name);
}

const WAIT_MODE: Record<TakDeploy, string> = {
  "takserver-config": "ignite",
  "takserver-messaging": "config",
  "takserver-api": "config",
  "takserver-plugins": "services",
};

export function waitMode(app: TakDeploy): string {
  return WAIT_MODE[app];
}

export function issuerHost(xml: string): string {
  const match = xml.match(/configurationUri="https:\/\/([^"/]+)/);
  if (match === null) {
    throw new Error("CoreConfig has no openId configurationUri");
  }
  return match[1];
}

export function tuneIgniteXml(xml: string): string {
  let next = xml;
  if (!next.includes('name="networkTimeout"')) {
    if (!next.includes(SPI)) {
      throw new Error("Ignite server config has no TcpDiscoverySpi");
    }
    next = next.replace(SPI, `${SPI}\n                    <property name="networkTimeout" value="15000"/>`);
  }
  if (!next.includes('name="failureDetectionTimeout"')) {
    if (!next.includes(DISCOVERY)) {
      throw new Error("Ignite server config has no discoverySpi");
    }
    next = next.replace(
      DISCOVERY,
      `<property name="failureDetectionTimeout" value="30000"/>\n            ${DISCOVERY}`,
    );
  }
  if (next.includes('name="localAddress"') || next.includes('name="enabled"')) {
    throw new Error("Ignite server config has a property the 2.17 classes do not use");
  }
  return next;
}

function covers(current: unknown, desired: unknown): boolean {
  if (typeof desired !== "object" || desired === null) {
    return current === desired;
  }
  if (typeof current !== "object" || current === null) {
    return false;
  }
  const got = current as Record<string, unknown>;
  for (const [key, value] of Object.entries(desired as Record<string, unknown>)) {
    if (!covers(got[key], value)) {
      return false;
    }
  }
  return true;
}

function resources(cpu: string, memory: string): ContainerDoc["resources"] {
  return { requests: { cpu, memory }, limits: { cpu, memory } };
}

function waitInit(image: string, mode: string): ContainerDoc {
  return {
    name: "wait-deps",
    image,
    imagePullPolicy: "IfNotPresent",
    command: ["bash", "/scripts/wait-deps.sh", mode],
    volumeMounts: [{ name: "oidc-script", mountPath: "/scripts", readOnly: true }],
    resources: resources("20m", "64Mi"),
  };
}

function importInit(image: string, host: string): ContainerDoc {
  return {
    name: "import-trust",
    image,
    imagePullPolicy: "IfNotPresent",
    command: ["bash", "/scripts/import-trust.sh"],
    env: [{ name: "ISSUER_HOST", value: host }],
    volumeMounts: [
      { name: "oidc-script", mountPath: "/scripts", readOnly: true },
      { name: "uds-trust", mountPath: "/bundle", readOnly: true },
      { name: "jvm-trust", mountPath: "/trust" },
    ],
    resources: {
      requests: { cpu: "20m", memory: "64Mi" },
      limits: { cpu: "200m", memory: "256Mi" },
    },
  };
}

function startupTcp(port: number): Record<string, unknown> {
  return { tcpSocket: { port }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 80, successThreshold: 1 };
}

function livenessTcp(port: number): Record<string, unknown> {
  return { tcpSocket: { port }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 6, successThreshold: 1 };
}

function execProbe(script: string, failureThreshold: number): Record<string, unknown> {
  return {
    exec: { command: [script] },
    periodSeconds: 10,
    timeoutSeconds: 10,
    failureThreshold,
    successThreshold: 1,
  };
}

function readinessExec(script: string): Record<string, unknown> {
  return { exec: { command: [script] }, timeoutSeconds: 10, periodSeconds: 10, successThreshold: 1 };
}

function scriptVolume(): VolumeDoc {
  return { name: "oidc-script", configMap: { name: "takserver-oidc-render" } };
}

function trustVolumes(): VolumeDoc[] {
  return [
    { name: "jvm-trust", emptyDir: {} },
    { name: "uds-trust", configMap: { name: "uds-trust-bundle", optional: true } },
  ];
}

function ensureVolume(volumes: VolumeDoc[], desired: VolumeDoc): boolean {
  const found = volumes.find(volume => volume.name === desired.name);
  if (!found) {
    volumes.push(desired);
    return true;
  }
  if (!covers(found, desired)) {
    Object.assign(found, desired);
    return true;
  }
  return false;
}

function ensureMount(container: ContainerDoc, mount: { name: string; mountPath: string; readOnly?: boolean }): boolean {
  const mounts = (container.volumeMounts ??= []);
  const found = mounts.find(item => item.name === mount.name);
  if (!found) {
    mounts.push(mount);
    return true;
  }
  if (!covers(found, mount)) {
    Object.assign(found, mount);
    return true;
  }
  return false;
}

function ensureEnv(container: ContainerDoc, name: string, value: string): boolean {
  const env = (container.env ??= []);
  const found = env.find(item => item.name === name);
  if (!found) {
    env.push({ name, value });
    return true;
  }
  if (found.value !== value) {
    found.value = value;
    return true;
  }
  return false;
}

function setProbe(container: ContainerDoc, field: "startupProbe" | "livenessProbe" | "readinessProbe", probe: unknown): boolean {
  if (covers(container[field], probe)) {
    return false;
  }
  container[field] = probe;
  return true;
}

export interface StartupContext {
  image: string;
  issuerHost?: string;
}

function desiredInits(app: TakDeploy, ctx: StartupContext): ContainerDoc[] {
  const inits = [waitInit(ctx.image, waitMode(app))];
  if (app === "takserver-api" || app === "takserver-messaging") {
    if (!ctx.issuerHost) {
      throw new Error("CoreConfig has no openId configurationUri");
    }
    inits.push(importInit(ctx.image, ctx.issuerHost));
  }
  return inits;
}

function placeInits(current: ContainerDoc[], desired: ContainerDoc[]): { inits: ContainerDoc[]; changed: boolean } {
  const owned = new Set(desired.map(init => init.name));
  const extras = current.filter(init => !owned.has(init.name));
  let changed = false;
  const kept = desired.map(want => {
    const have = current.find(init => init.name === want.name);
    if (have && covers(have, want)) {
      return have;
    }
    changed = true;
    return want;
  });
  const next = [...kept, ...extras];
  if (current.length !== next.length || current.some((init, index) => init.name !== next[index]?.name)) {
    changed = true;
  }
  return { inits: changed ? next : current, changed };
}

// Mutates spec. Returns true when a field the script owned was wrong.
export function shapePodSpec(spec: WorkloadPodSpec, app: TakDeploy, ctx: StartupContext): boolean {
  let changed = false;
  if (spec.automountServiceAccountToken !== true) {
    spec.automountServiceAccountToken = true;
    changed = true;
  }
  if (app === "takserver-api" && spec.hostAliases !== undefined) {
    delete spec.hostAliases;
    changed = true;
  }
  const volumes = (spec.volumes ??= []);
  if (ensureVolume(volumes, scriptVolume())) {
    changed = true;
  }
  const needsTrust = app === "takserver-api" || app === "takserver-messaging";
  if (needsTrust) {
    for (const volume of trustVolumes()) {
      if (ensureVolume(volumes, volume)) {
        changed = true;
      }
    }
  }
  const placed = placeInits(spec.initContainers ?? [], desiredInits(app, ctx));
  if (placed.changed) {
    spec.initContainers = placed.inits;
    changed = true;
  }
  const main = spec.containers?.[0];
  if (!main) {
    throw new Error(`${app} has no container`);
  }
  if (needsTrust) {
    if (ensureEnv(main, "JAVA_TOOL_OPTIONS", TRUST_OPTS)) {
      changed = true;
    }
    if (ensureMount(main, { name: "jvm-trust", mountPath: "/trust" })) {
      changed = true;
    }
  }
  if (app === "takserver-config") {
    if (setProbe(main, "startupProbe", execProbe("/config-readiness.sh", 80))) {
      changed = true;
    }
    if (setProbe(main, "readinessProbe", readinessExec("/config-readiness.sh"))) {
      changed = true;
    }
  } else if (app === "takserver-messaging") {
    if (setProbe(main, "startupProbe", startupTcp(8089))) {
      changed = true;
    }
    if (setProbe(main, "livenessProbe", livenessTcp(8089))) {
      changed = true;
    }
    if (setProbe(main, "readinessProbe", readinessExec("/messaging-readiness.sh"))) {
      changed = true;
    }
  } else if (app === "takserver-api") {
    if (setProbe(main, "startupProbe", startupTcp(8443))) {
      changed = true;
    }
    if (setProbe(main, "livenessProbe", livenessTcp(8443))) {
      changed = true;
    }
    if (setProbe(main, "readinessProbe", readinessExec("/api-readiness.sh"))) {
      changed = true;
    }
  } else if (app === "takserver-plugins") {
    const resources = (main.resources ??= {});
    const requests = (resources.requests ??= {});
    const limits = (resources.limits ??= {});
    if (requests.memory !== "128Mi") {
      requests.memory = "128Mi";
      changed = true;
    }
    if (limits.memory !== "384Mi") {
      limits.memory = "384Mi";
      changed = true;
    }
  }
  return changed;
}

function strategyReady(strategy: { type?: string; rollingUpdate?: unknown } | undefined): boolean {
  return strategy?.type === "Recreate" && strategy.rollingUpdate == null;
}

export function shapeDeployment(deploy: WorkloadDeploy, ctx: StartupContext): { next: WorkloadDeploy; changed: boolean } {
  const app = deploy.metadata?.name;
  if (!isTakDeploy(app)) {
    return { next: deploy, changed: false };
  }
  if (!ctx.image) {
    throw new Error("RENDER_IMAGE is not set on the takserver-oidc module");
  }
  const next = structuredClone(deploy);
  let changed = false;
  const spec = (next.spec ??= {});
  if (spec.progressDeadlineSeconds !== 1200) {
    spec.progressDeadlineSeconds = 1200;
    changed = true;
  }
  if (!strategyReady(spec.strategy)) {
    spec.strategy = { type: "Recreate" };
    changed = true;
  }
  const template = (spec.template ??= {});
  const labels = ((template.metadata ??= {}).labels ??= {});
  if (labels[RELOAD_LABEL] !== RELOAD_VALUE) {
    labels[RELOAD_LABEL] = RELOAD_VALUE;
    changed = true;
  }
  const pod = (template.spec ??= {});
  if (shapePodSpec(pod, app, ctx)) {
    changed = true;
  }
  return { next, changed };
}

export function deploymentOps(current: WorkloadDeploy, next: WorkloadDeploy): JsonOp[] {
  const ops: JsonOp[] = [];
  const before = current.spec;
  const after = next.spec;
  if (!after) {
    return ops;
  }
  const progress = "/spec/progressDeadlineSeconds";
  if (before?.progressDeadlineSeconds !== after.progressDeadlineSeconds) {
    ops.push({
      op: before?.progressDeadlineSeconds === undefined ? "add" : "replace",
      path: progress,
      value: after.progressDeadlineSeconds,
    });
  }
  if (!strategyReady(before?.strategy)) {
    ops.push({
      op: before?.strategy === undefined ? "add" : "replace",
      path: "/spec/strategy",
      value: { type: "Recreate" },
    });
  }
  if (JSON.stringify(before?.template) !== JSON.stringify(after.template)) {
    ops.push({
      op: before?.template === undefined ? "add" : "replace",
      path: "/spec/template",
      value: after.template,
    });
  }
  return ops;
}

async function readIssuer(cluster: Cluster): Promise<string> {
  const configMap = await cluster.getConfigMap("takserver", "core-config");
  const xml = configMap?.data?.["CoreConfig.xml"];
  if (!xml) {
    throw new Error("CoreConfig has no openId configurationUri");
  }
  return issuerHost(xml);
}

export async function reconcileDeployment(
  deploy: WorkloadDeploy,
  phase: string,
  cluster: Cluster,
  env: NodeJS.ProcessEnv,
): Promise<void> {
  if (phase === "DELETED") {
    return;
  }
  const name = deploy.metadata?.name;
  if (!isTakDeploy(name)) {
    return;
  }
  const image = env.RENDER_IMAGE ?? "";
  const issuer = name === "takserver-config" || name === "takserver-plugins" ? undefined : await readIssuer(cluster);
  const { next, changed } = shapeDeployment(deploy, { image, issuerHost: issuer });
  if (!changed) {
    return;
  }
  const namespace = deploy.metadata?.namespace ?? "takserver";
  await cluster.patchDeployment(namespace, name, deploymentOps(deploy, next));
}

export async function preparePod(pod: PodLike, env: NodeJS.ProcessEnv, cluster: Cluster): Promise<void> {
  const image = env.RENDER_IMAGE;
  if (!image) {
    throw new Error("RENDER_IMAGE is not set on the takserver-oidc module");
  }
  const app = pod.metadata?.labels?.app;
  if (!isTakDeploy(app)) {
    addRender(pod, image);
    return;
  }
  const issuer = app === "takserver-config" || app === "takserver-plugins" ? undefined : await readIssuer(cluster);
  const spec = (pod.spec ??= {}) as WorkloadPodSpec;
  shapePodSpec(spec, app, { image, issuerHost: issuer });
  addRender(pod, image);
}

export async function waitGone(cluster: Cluster, app: string, timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const pods = (await cluster.listPods("takserver", app)).filter(
      item => !item.metadata?.deletionTimestamp && item.status?.phase !== "Succeeded",
    );
    if (pods.length === 0) {
      return;
    }
    if (Date.now() >= deadline) {
      throw new Error(`${app} pods did not terminate within ${timeoutMs / 1000}s`);
    }
    await cluster.sleep(3_000);
  }
}

function automountOps(sts: StatefulSetDoc): JsonOp[] {
  const current = sts.spec?.template?.spec?.automountServiceAccountToken;
  return [
    {
      op: current === undefined ? "add" : "replace",
      path: "/spec/template/spec/automountServiceAccountToken",
      value: true,
    },
  ];
}

export async function reconcileIgnite(phase: string, cluster: Cluster): Promise<void> {
  if (phase === "DELETED") {
    return;
  }
  const configMap = await cluster.getConfigMap("takserver", IGNITE_CONFIGMAP);
  const xml = configMap?.data?.[IGNITE_XML];
  if (!xml) {
    return;
  }
  const tuned = tuneIgniteXml(xml);
  const sts = await cluster.getStatefulSet("takserver", IGNITE_STATEFULSET);
  if (!sts) {
    return;
  }
  const automount = sts.spec?.template?.spec?.automountServiceAccountToken === true;
  if (tuned === xml && automount) {
    return;
  }
  try {
    for (const name of STOP_ORDER) {
      await cluster.scaleDeployment("takserver", name, 0);
      await waitGone(cluster, name);
    }
    if (tuned !== xml) {
      await cluster.patchConfigMapKey("takserver", IGNITE_CONFIGMAP, IGNITE_XML, tuned, true);
    }
    if (!automount) {
      await cluster.patchStatefulSet("takserver", IGNITE_STATEFULSET, automountOps(sts));
    }
    const hasAnnotations = sts.spec?.template?.metadata?.annotations !== undefined;
    await cluster.restartStatefulSet("takserver", IGNITE_STATEFULSET, hasAnnotations);
  } finally {
    for (const name of START_ORDER) {
      await cluster.scaleDeployment("takserver", name, 1);
    }
  }
}

let igniteTail: Promise<void> = Promise.resolve();

export function enqueueIgnite(work: () => Promise<void>): Promise<void> {
  const run = igniteTail.then(work, work);
  igniteTail = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

export function resetIgniteQueue(): void {
  igniteTail = Promise.resolve();
}
