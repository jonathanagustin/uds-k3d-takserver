// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Live Kubernetes calls for the reconcile capabilities. The decision logic
// lives under capabilities/ and is unit-tested with a fake of this surface.
// This file is the thin client those tests do not load.

import { K8s, kind, RegisterKind } from "pepr";
import type { KubernetesObject } from "kubernetes-fluent-client";

export class DestinationRule implements KubernetesObject {
  apiVersion = "networking.istio.io/v1";
  kind = "DestinationRule";
}

RegisterKind(DestinationRule, {
  group: "networking.istio.io",
  version: "v1",
  kind: "DestinationRule",
});

export interface ConfigMapDoc {
  metadata?: { annotations?: Record<string, string> };
  data?: Record<string, string>;
  binaryData?: Record<string, string>;
}

export interface SecretDoc {
  data?: Record<string, string>;
}

export interface DestinationRuleDoc {
  spec?: {
    exportTo?: string[];
    trafficPolicy?: {
      portLevelSettings?: { tls?: { credentialName?: string } }[];
    };
  };
}

export interface PodDoc {
  metadata?: { name?: string; deletionTimestamp?: string };
  status?: { phase?: string };
}

export interface DeploymentDoc {
  metadata?: { name?: string; namespace?: string; generation?: number; annotations?: Record<string, string> };
  spec?: {
    replicas?: number;
    progressDeadlineSeconds?: number;
    strategy?: { type?: string; rollingUpdate?: unknown };
    template?: {
      metadata?: { labels?: Record<string, string>; annotations?: Record<string, string> };
      spec?: Record<string, unknown>;
    };
  };
  status?: {
    observedGeneration?: number;
    availableReplicas?: number;
    updatedReplicas?: number;
  };
}

export interface StatefulSetDoc {
  spec?: {
    template?: {
      metadata?: { annotations?: Record<string, string> };
      spec?: { automountServiceAccountToken?: boolean };
    };
  };
}

export interface JsonOp {
  op: "add" | "replace" | "remove";
  path: string;
  value?: unknown;
}

export interface Cluster {
  getConfigMap(namespace: string, name: string): Promise<ConfigMapDoc | undefined>;
  deleteConfigMap(namespace: string, name: string): Promise<void>;
  applyConfigMap(
    namespace: string,
    name: string,
    annotations: Record<string, string>,
    data: Record<string, string>,
  ): Promise<void>;
  patchConfigMapKey(namespace: string, name: string, key: string, value: string, present: boolean): Promise<void>;
  serviceExists(namespace: string, name: string): Promise<boolean>;
  restartDeployment(namespace: string, name: string, hasAnnotations: boolean): Promise<void>;
  getSecret(namespace: string, name: string): Promise<SecretDoc | undefined>;
  applySecret(namespace: string, name: string, labels: Record<string, string>, data: Record<string, string>): Promise<void>;
  getDestinationRule(namespace: string, name: string): Promise<DestinationRuleDoc | undefined>;
  ensureNamespace(name: string): Promise<void>;
  getDeployment(namespace: string, name: string): Promise<DeploymentDoc | undefined>;
  patchDeployment(namespace: string, name: string, ops: JsonOp[]): Promise<void>;
  scaleDeployment(namespace: string, name: string, replicas: number): Promise<void>;
  getStatefulSet(namespace: string, name: string): Promise<StatefulSetDoc | undefined>;
  patchStatefulSet(namespace: string, name: string, ops: JsonOp[]): Promise<void>;
  restartStatefulSet(namespace: string, name: string, hasAnnotations: boolean): Promise<void>;
  listPods(namespace: string, app: string): Promise<PodDoc[]>;
  sleep(ms: number): Promise<void>;
}

export function isNotFound(err: unknown): boolean {
  if (typeof err !== "object" || err === null) {
    return false;
  }
  const record = err as { status?: number; statusCode?: number; code?: number };
  const status = record.status ?? record.statusCode ?? record.code;
  return status === 404;
}

function pointer(key: string): string {
  return key.replaceAll("~", "~0").replaceAll("/", "~1");
}

async function read<T>(get: () => Promise<T>): Promise<T | undefined> {
  try {
    return await get();
  } catch (err) {
    if (isNotFound(err)) {
      return undefined;
    }
    throw err;
  }
}

const RESTART = "kubectl.kubernetes.io/restartedAt";

function restartOps(hasAnnotations: boolean): JsonOp[] {
  const value = new Date().toISOString();
  if (!hasAnnotations) {
    return [{ op: "add", path: "/spec/template/metadata/annotations", value: { [RESTART]: value } }];
  }
  return [{ op: "add", path: `/spec/template/metadata/annotations/${pointer(RESTART)}`, value }];
}

const live: Cluster = {
  getConfigMap: (namespace, name) => read(() => K8s(kind.ConfigMap).InNamespace(namespace).Get(name)),
  deleteConfigMap: async (namespace, name) => {
    try {
      await K8s(kind.ConfigMap).InNamespace(namespace).Delete(name);
    } catch (err) {
      if (isNotFound(err)) {
        return;
      }
      throw err;
    }
  },
  applyConfigMap: async (namespace, name, annotations, data) => {
    await K8s(kind.ConfigMap).Apply({
      apiVersion: "v1",
      kind: "ConfigMap",
      metadata: { name, namespace, annotations },
      data,
    });
  },
  patchConfigMapKey: async (namespace, name, key, value, present) => {
    const op = present ? "replace" : "add";
    await K8s(kind.ConfigMap, { namespace, name }).Patch([{ op, path: `/data/${pointer(key)}`, value }]);
  },
  serviceExists: async (namespace, name) => {
    const found = await read(() => K8s(kind.Service).InNamespace(namespace).Get(name));
    return found !== undefined;
  },
  restartDeployment: async (namespace, name, hasAnnotations) => {
    await K8s(kind.Deployment, { namespace, name }).Patch(restartOps(hasAnnotations) as []);
  },
  getSecret: (namespace, name) => read(() => K8s(kind.Secret).InNamespace(namespace).Get(name)),
  applySecret: async (namespace, name, labels, data) => {
    await K8s(kind.Secret).Apply({
      apiVersion: "v1",
      kind: "Secret",
      metadata: { name, namespace, labels },
      type: "Opaque",
      data,
    });
  },
  getDestinationRule: (namespace, name) =>
    read(() => K8s(DestinationRule).InNamespace(namespace).Get(name) as Promise<DestinationRuleDoc>),
  ensureNamespace: async name => {
    const found = await read(() => K8s(kind.Namespace).Get(name));
    if (found) {
      return;
    }
    await K8s(kind.Namespace).Create({
      apiVersion: "v1",
      kind: "Namespace",
      metadata: { name },
    });
  },
  getDeployment: (namespace, name) =>
    read(() => K8s(kind.Deployment).InNamespace(namespace).Get(name)) as Promise<DeploymentDoc | undefined>,
  patchDeployment: async (namespace, name, ops) => {
    await K8s(kind.Deployment, { namespace, name }).Patch(ops as []);
  },
  scaleDeployment: async (namespace, name, replicas) => {
    await K8s(kind.Deployment).InNamespace(namespace).Scale(replicas, name);
  },
  getStatefulSet: (namespace, name) => read(() => K8s(kind.StatefulSet).InNamespace(namespace).Get(name)),
  patchStatefulSet: async (namespace, name, ops) => {
    await K8s(kind.StatefulSet, { namespace, name }).Patch(ops as []);
  },
  restartStatefulSet: async (namespace, name, hasAnnotations) => {
    await K8s(kind.StatefulSet, { namespace, name }).Patch(restartOps(hasAnnotations) as []);
  },
  listPods: async (namespace, app) => {
    const list = await K8s(kind.Pod).InNamespace(namespace).WithLabel("app", app).Get();
    return (list.items ?? []) as PodDoc[];
  },
  sleep: ms => new Promise(resolve => setTimeout(resolve, ms)),
};

export const runtime: { cluster: Cluster } = { cluster: live };
