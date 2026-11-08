// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Live Kubernetes calls for the reconcile capabilities. The decision logic
// lives under capabilities/ and is unit-tested with a fake of this surface.
// This file is the thin client those tests do not load.

import { K8s, kind, RegisterKind } from "pepr";
import type { KubernetesObject } from "kubernetes-fluent-client";
import { request as httpsRequest } from "node:https";
import type { Condition, TakApi, TakClientCluster, TakClientDoc } from "./capabilities/takclient.ts";

export class DestinationRule implements KubernetesObject {
  apiVersion = "networking.istio.io/v1";
  kind = "DestinationRule";
}

RegisterKind(DestinationRule, {
  group: "networking.istio.io",
  version: "v1",
  kind: "DestinationRule",
});

// TakClient custom resource. The CRD is crds/takclient.yaml, generated from
// api/v1alpha1/takclient_types.ts. See ADR 22.
export class TakClient implements KubernetesObject {
  apiVersion = "tak.jonathanagustin.github.io/v1alpha1";
  kind = "TakClient";
  spec?: TakClientDoc["spec"];
  status?: TakClientDoc["status"];
}

RegisterKind(TakClient, {
  group: "tak.jonathanagustin.github.io",
  version: "v1alpha1",
  kind: "TakClient",
  plural: "takclients",
});

export interface ConfigMapDoc {
  metadata?: { annotations?: Record<string, string> };
  data?: Record<string, string>;
  binaryData?: Record<string, string>;
}

export interface SecretDoc {
  metadata?: { annotations?: Record<string, string>; labels?: Record<string, string> };
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
  metadata?: { name?: string; deletionTimestamp?: string; creationTimestamp?: string };
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

export interface JobDoc {
  status?: { succeeded?: number; completionTime?: string };
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
  podLogs(namespace: string, name: string): Promise<string[]>;
  getJob(namespace: string, name: string): Promise<JobDoc | undefined>;
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

const live: TakClientCluster = {
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
  podLogs: (namespace, name) => K8s(kind.Pod).InNamespace(namespace).Logs(name),
  getJob: (namespace, name) => read(() => K8s(kind.Job).InNamespace(namespace).Get(name)) as Promise<JobDoc | undefined>,
  sleep: ms => new Promise(resolve => setTimeout(resolve, ms)),
  patchTakClientStatus: async (namespace, name, conditions: Condition[]) => {
    await K8s(TakClient).PatchStatus({ metadata: { name, namespace }, status: { conditions } } as unknown as TakClient);
  },
  annotateTakClient: async (namespace, name, annotations) => {
    // Server-side apply of the annotations only. The spec stays the user's.
    await K8s(TakClient).Apply(
      {
        apiVersion: "tak.jonathanagustin.github.io/v1alpha1",
        kind: "TakClient",
        metadata: { name, namespace, annotations },
      } as TakClient,
      { force: true },
    );
  },
  listTakClients: async namespace => {
    const list = await K8s(TakClient).InNamespace(namespace).Get();
    return (list.items ?? []) as TakClientDoc[];
  },
  deleteSecret: async (namespace, name) => {
    try {
      await K8s(kind.Secret).InNamespace(namespace).Delete(name);
    } catch (err) {
      if (isNotFound(err)) {
        return;
      }
      throw err;
    }
  },
  applySecretWithAnnotations: async (namespace, name, labels, annotations, data) => {
    await K8s(kind.Secret).Apply({
      apiVersion: "v1",
      kind: "Secret",
      metadata: { name, namespace, labels, annotations },
      type: "Opaque",
      data,
    });
  },
};

// TAK's admin API on takserver-api-service:8443, with the admin certificate.
// The chain is checked against the TAK CA. The host name is not, because
// TAK's server certificate is issued for its public names, not the Service.
export const TAK_API_HOST = "takserver-api-service.takserver.svc";

const tak: TakApi = {
  request: (tls, method, path, body, options) =>
    new Promise((resolve, reject) => {
      const payload = body === undefined ? undefined : options ? String(body) : JSON.stringify(body);
      const req = httpsRequest(
        {
          host: TAK_API_HOST,
          port: options?.port ?? 8443,
          auth: options?.auth,
          method,
          path,
          ca: tls.ca,
          // Enrollment uses the file user's Basic identity, never the
          // admin certificate's identity. Admin calls keep mutual TLS.
          cert: options ? undefined : tls.cert,
          key: options ? undefined : tls.key,
          passphrase: options ? undefined : tls.passphrase,
          checkServerIdentity: () => undefined,
          timeout: 20000,
          headers: payload
            ? { "content-type": options?.contentType ?? "application/json", "accept": "application/json", "content-length": Buffer.byteLength(payload) }
            : {},
        },
        res => {
          const chunks: Buffer[] = [];
          res.on("data", chunk => chunks.push(chunk));
          res.on("end", () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks).toString("utf8") }));
        },
      );
      req.on("timeout", () => req.destroy(new Error(`TAK ${method} ${path} timed out`)));
      req.on("error", reject);
      if (payload) {
        req.write(payload);
      }
      req.end();
    }),
};

export const runtime: { cluster: Cluster; takCluster: TakClientCluster; tak: TakApi } = {
  cluster: live,
  takCluster: live,
  tak,
};
