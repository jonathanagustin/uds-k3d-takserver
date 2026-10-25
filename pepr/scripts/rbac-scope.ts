// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Pepr emits one ClusterRole. package.json cannot carry a namespaced Role,
// and watch bindings merge a cluster-wide `watch` rule that drops
// resourceNames. This rewrites the generated chart: the watched objects move
// to Roles, and the ClusterRole keeps what cannot be namespaced.
//
// What stays cluster-scoped:
// - Namespace get and create. Namespace is cluster-scoped. The chart schema
//   rejects `resourceNames` on `values.rbac` (Helm: additional properties
//   'resourceNames' not allowed), so this rule cannot name `cloudtak`.
//   The watcher still only reads that namespace.
// - `customresourcedefinitions` create/patch. Pepr registers its store CRD.
// - `peprstores`. Pepr's own Role sets resourceNames to an empty string, so
//   the grant that works is still this ClusterRole rule.
//
// What a Role still cannot pin to a name:
// - ConfigMap `create` in takserver (the startup marker). `create` ignores
//   resourceNames.
// - Secret `create` in cloudtak and istio-tenant-gateway, for the same reason.
//   get/patch/watch name the objects.
// - Pod `get`/`list` in takserver. The list is by label, so resourceNames
//   would deny it.

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseDocument, stringify } from "yaml";

export interface ChartRule {
  apiGroups?: string[];
  resources?: string[];
  resourceNames?: string[];
  verbs?: string[];
}

const MOVED = new Set([
  "configmaps",
  "pods",
  "secrets",
  "services",
  "deployments",
  "deployments/scale",
  "statefulsets",
  "destinationrules",
]);

const TAK = ["takserver-config", "takserver-messaging", "takserver-api", "takserver-plugins"];

const ROLE_RULES = [
  {
    namespace: "takserver",
    rules: [
      {
        apiGroups: [""],
        resources: ["configmaps"],
        resourceNames: ["core-config", "cert-migration", "takserver-ignite-configmap", "takserver-startup"],
        verbs: ["get", "patch", "watch"],
      },
      { apiGroups: [""], resources: ["configmaps"], verbs: ["create"] },
      { apiGroups: [""], resources: ["secrets"], resourceNames: ["takserver-keystore"], verbs: ["get", "watch"] },
      { apiGroups: [""], resources: ["pods"], verbs: ["get", "list"] },
      { apiGroups: ["apps"], resources: ["deployments"], resourceNames: TAK, verbs: ["get", "patch", "watch"] },
      { apiGroups: ["apps"], resources: ["deployments/scale"], resourceNames: TAK, verbs: ["get", "patch", "update"] },
      {
        apiGroups: ["apps"],
        resources: ["statefulsets"],
        resourceNames: ["takserver-ignite"],
        verbs: ["get", "patch", "watch"],
      },
      {
        apiGroups: ["networking.istio.io"],
        resources: ["destinationrules"],
        resourceNames: ["takserver-web"],
        verbs: ["get", "watch"],
      },
    ],
  },
  {
    namespace: "cloudtak",
    rules: [
      {
        apiGroups: [""],
        resources: ["secrets"],
        resourceNames: ["cloudtak-tak-admin"],
        verbs: ["get", "patch"],
      },
      { apiGroups: [""], resources: ["secrets"], verbs: ["create"] },
    ],
  },
  {
    namespace: "istio-tenant-gateway",
    rules: [
      {
        apiGroups: [""],
        resources: ["secrets"],
        resourceNames: ["takserver-web-ca"],
        verbs: ["get", "patch"],
      },
      { apiGroups: [""], resources: ["secrets"], verbs: ["create"] },
      {
        apiGroups: [""],
        resources: ["services"],
        resourceNames: ["tenant-ingressgateway"],
        verbs: ["get", "watch"],
      },
    ],
  },
  {
    namespace: "istio-passthrough-gateway",
    rules: [
      {
        apiGroups: [""],
        resources: ["services"],
        resourceNames: ["passthrough-ingressgateway"],
        verbs: ["get", "watch"],
      },
    ],
  },
  {
    namespace: "istio-admin-gateway",
    rules: [
      {
        apiGroups: [""],
        resources: ["services"],
        resourceNames: ["admin-ingressgateway"],
        verbs: ["get", "watch"],
      },
    ],
  },
  {
    namespace: "kube-system",
    rules: [
      {
        apiGroups: [""],
        resources: ["configmaps"],
        resourceNames: ["coredns-custom"],
        verbs: ["get", "patch", "watch"],
      },
      {
        apiGroups: ["apps"],
        resources: ["deployments"],
        resourceNames: ["coredns"],
        verbs: ["get", "patch", "watch"],
      },
    ],
  },
];

function roleDoc(namespace: string, rules: ChartRule[]) {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind: "Role",
    metadata: { name: "{{ .Values.uuid }}", namespace },
    rules,
  };
}

function bindingDoc(namespace: string) {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind: "RoleBinding",
    metadata: { name: "{{ .Values.uuid }}", namespace },
    roleRef: {
      apiGroup: "rbac.authorization.k8s.io",
      kind: "Role",
      name: "{{ .Values.uuid }}",
    },
    subjects: [{ kind: "ServiceAccount", name: "{{ .Values.uuid }}", namespace: "pepr-system" }],
  };
}

export function roleManifest(): string {
  const docs: object[] = [];
  for (const entry of ROLE_RULES) {
    docs.push(roleDoc(entry.namespace, entry.rules));
    docs.push(bindingDoc(entry.namespace));
  }
  return docs.map(doc => stringify(doc, { aliasDuplicateObjects: false })).join("---\n");
}

export function clusterRules(rules: ChartRule[]): ChartRule[] {
  if (!Array.isArray(rules) || rules.length === 0) {
    throw new Error("pepr rbac list is empty");
  }
  const namespaces = rules.filter(rule => (rule.resources ?? []).includes("namespaces"));
  if (namespaces.length !== 1) {
    throw new Error("pepr rbac no longer has one namespaces rule");
  }
  const moved = rules.some(rule => (rule.resources ?? []).some(resource => MOVED.has(resource)));
  if (!moved) {
    throw new Error("pepr rbac no longer includes the watched resources that move into Roles");
  }
  // values.rbac is checked by the chart schema, which has no resourceNames
  // property. Drop it here. The Role manifests below still name their objects.
  return rules
    .filter(rule => !(rule.resources ?? []).some(resource => MOVED.has(resource)))
    .map(rule => ({
      apiGroups: rule.apiGroups,
      resources: rule.resources,
      verbs: rule.verbs,
    }));
}

function rulesFrom(value: unknown): ChartRule[] {
  if (typeof value !== "object" || value === null || !("toJSON" in value)) {
    throw new Error("values.yaml has no rbac list");
  }
  const toJSON = value.toJSON;
  if (typeof toJSON !== "function") {
    throw new Error("values.yaml has no rbac list");
  }
  const current: unknown = toJSON.call(value);
  if (!Array.isArray(current)) {
    throw new Error("values.yaml has no rbac list");
  }
  return current as ChartRule[];
}

export function applyChartRbac(chartDir: string): void {
  const valuesPath = join(chartDir, "values.yaml");
  const doc = parseDocument(readFileSync(valuesPath, "utf8"));
  const current = rulesFrom(doc.get("rbac"));
  const next = clusterRules(current);
  for (const rule of next) {
    for (const resource of rule.resources ?? []) {
      if (MOVED.has(resource)) {
        throw new Error(`cluster rule for ${resource} survived`);
      }
    }
  }
  doc.set("rbac", next);
  writeFileSync(valuesPath, String(doc));
  writeFileSync(join(chartDir, "templates", "namespaced-roles.yaml"), roleManifest());
}
