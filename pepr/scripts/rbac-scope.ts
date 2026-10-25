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
//   get/list/patch/watch on the Role name the objects. list sits beside watch
//   because a namespaced list with `?fieldSelector=metadata.name=` needs it.
// - Pod `get`/`list` in takserver. The list is by label, so resourceNames
//   would deny it.
//
// The watcher itself does not use that namespaced URL. Pepr 2.0.5 spreads the
// binding filters into the client, and those filters carry `namespaces` (the
// capability filter) rather than `namespace` (what the client puts on the
// path). The list and the watch are therefore cluster-scoped, with
// `?fieldSelector=metadata.name=`. A Role never matches a cluster-scoped
// request. After the watched resources left the chart ClusterRole, both calls
// were forbidden, the client gave up after five tries (about 30s), and the
// process exited before it could create `takserver-startup`. The same names
// are granted `list` and `watch` on a second ClusterRole. A field selector
// for a different name stays forbidden, and an unfiltered list stays
// forbidden. The chart schema still rejects `resourceNames` on `values.rbac`,
// so this ClusterRole is its own manifest.

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
        verbs: ["get", "list", "patch", "watch"],
      },
      { apiGroups: [""], resources: ["configmaps"], verbs: ["create"] },
      { apiGroups: [""], resources: ["secrets"], resourceNames: ["takserver-keystore"], verbs: ["get", "list", "watch"] },
      { apiGroups: [""], resources: ["pods"], verbs: ["get", "list"] },
      { apiGroups: ["apps"], resources: ["deployments"], resourceNames: TAK, verbs: ["get", "list", "patch", "watch"] },
      { apiGroups: ["apps"], resources: ["deployments/scale"], resourceNames: TAK, verbs: ["get", "patch", "update"] },
      {
        apiGroups: ["apps"],
        resources: ["statefulsets"],
        resourceNames: ["takserver-ignite"],
        verbs: ["get", "list", "patch", "watch"],
      },
      {
        apiGroups: ["networking.istio.io"],
        resources: ["destinationrules"],
        resourceNames: ["takserver-web"],
        verbs: ["get", "list", "watch"],
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
        verbs: ["get", "list", "watch"],
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
        verbs: ["get", "list", "watch"],
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
        verbs: ["get", "list", "watch"],
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
        verbs: ["get", "list", "patch", "watch"],
      },
      {
        apiGroups: ["apps"],
        resources: ["deployments"],
        resourceNames: ["coredns"],
        verbs: ["get", "list", "patch", "watch"],
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

// One rule per resource. Every name the Roles grant `watch` is listed here,
// because the watcher asks for each of those names at cluster scope.
function watchClusterRules(): ChartRule[] {
  const grouped = new Map<string, ChartRule>();
  for (const entry of ROLE_RULES) {
    for (const rule of entry.rules) {
      if (!(rule.verbs ?? []).includes("watch")) {
        continue;
      }
      if (!rule.resourceNames || rule.resourceNames.length === 0) {
        throw new Error(`watch rule for ${(rule.resources ?? []).join(",")} has no resourceNames`);
      }
      const key = `${(rule.apiGroups ?? []).join(",")}|${(rule.resources ?? []).join(",")}`;
      const found = grouped.get(key);
      if (!found) {
        grouped.set(key, {
          apiGroups: rule.apiGroups,
          resources: rule.resources,
          resourceNames: [...(rule.resourceNames ?? [])],
          verbs: ["list", "watch"],
        });
        continue;
      }
      const names = found.resourceNames ?? [];
      for (const name of rule.resourceNames ?? []) {
        if (!names.includes(name)) {
          names.push(name);
        }
      }
      found.resourceNames = names;
    }
  }
  return [...grouped.values()];
}

function clusterWatchDoc(rules: ChartRule[]) {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind: "ClusterRole",
    metadata: { name: "{{ .Values.uuid }}-watch" },
    rules,
  };
}

function clusterWatchBindingDoc() {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind: "ClusterRoleBinding",
    metadata: { name: "{{ .Values.uuid }}-watch" },
    roleRef: {
      apiGroup: "rbac.authorization.k8s.io",
      kind: "ClusterRole",
      name: "{{ .Values.uuid }}-watch",
    },
    subjects: [{ kind: "ServiceAccount", name: "{{ .Values.uuid }}", namespace: "pepr-system" }],
  };
}

export function roleManifest(): string {
  const docs: object[] = [clusterWatchDoc(watchClusterRules()), clusterWatchBindingDoc()];
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
