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
// ConfigMap `delete` of `takserver-startup` is named. The Ignite reconcile
// removes that marker before a restart. The API authorizes delete before it
// looks the object up, so a missing marker is still forbidden without the
// verb and the reconcile never reaches the create.
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
//
// Two ServiceAccounts (ADR 22). The admission pods keep `pepr-<uuid>`. The
// watcher runs as `pepr-<uuid>-watcher`. Every Secret rule and every TakClient
// rule goes into Roles and a ClusterRole bound only to the watcher account.
// The admission pods read the core-config ConfigMap and nothing else, so they
// cannot read any Secret, including `takserver-ca-key`. The other rules are
// bound to both accounts.

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
  "takclients",
]);

const TAKCLIENT_GROUP = "tak.jonathanagustin.github.io";

export const ADMISSION_SA = "{{ .Values.uuid }}";
export const WATCHER_SA = "{{ .Values.uuid }}-watcher";

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
      {
        apiGroups: [""],
        resources: ["configmaps"],
        resourceNames: ["takserver-startup"],
        verbs: ["delete"],
      },
      {
        apiGroups: [""],
        resources: ["secrets"],
        resourceNames: ["takserver-keystore", "takserver-certs", "takserver-ca-key"],
        verbs: ["get", "list", "watch"],
      },
      // The CRL the TakClient capability writes (ADR 22). Secret create
      // cannot be pinned to a name.
      { apiGroups: [""], resources: ["secrets"], resourceNames: ["takserver-crl"], verbs: ["get", "patch"] },
      { apiGroups: [""], resources: ["secrets"], verbs: ["create"] },
      { apiGroups: [""], resources: ["pods"], verbs: ["get", "list"] },
      // The Ignite reconcile reads the server's topology lines before it
      // starts TAK again (#296).
      { apiGroups: [""], resources: ["pods/log"], resourceNames: ["takserver-ignite-0"], verbs: ["get"] },
      { apiGroups: ["apps"], resources: ["deployments"], resourceNames: TAK, verbs: ["get", "list", "patch", "watch"] },
      { apiGroups: ["apps"], resources: ["deployments/scale"], resourceNames: TAK, verbs: ["get", "patch", "update"] },
      {
        apiGroups: ["apps"],
        resources: ["statefulsets"],
        resourceNames: ["takserver-ignite"],
        verbs: ["get", "list", "patch", "watch"],
      },
      {
        apiGroups: ["apps"],
        resources: ["statefulsets"],
        resourceNames: ["takserver-postgresql"],
        verbs: ["get"],
      },
      // The Ignite reconcile waits for SchemaManager before it starts TAK.
      { apiGroups: ["batch"], resources: ["jobs"], resourceNames: ["takserver-db-setup"], verbs: ["get"] },
      {
        apiGroups: ["networking.istio.io"],
        resources: ["destinationrules"],
        resourceNames: ["takserver-web"],
        verbs: ["get", "list", "watch"],
      },
    ],
  },
  // TakClients and their Secrets (ADR 22). Only those Secrets live in this
  // namespace, so the Secret verbs are not pinned to names.
  {
    namespace: "takclients",
    rules: [
      { apiGroups: [TAKCLIENT_GROUP], resources: ["takclients"], verbs: ["get", "patch"] },
      { apiGroups: [TAKCLIENT_GROUP], resources: ["takclients/status"], verbs: ["get", "patch"] },
      { apiGroups: [""], resources: ["secrets"], verbs: ["get", "create", "patch", "delete"] },
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

// Secrets and TakClients are for the watcher only.
export function watcherOnly(rule: ChartRule): boolean {
  // An exact match on each API group, not a substring check.
  return (rule.resources ?? []).includes("secrets") || (rule.apiGroups ?? []).some(group => group === TAKCLIENT_GROUP);
}

function roleDoc(kind: "Role" | "ClusterRole", name: string, namespace: string | undefined, rules: ChartRule[]) {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind,
    metadata: namespace ? { name, namespace } : { name },
    rules,
  };
}

function bindingDoc(kind: "Role" | "ClusterRole", name: string, namespace: string | undefined, accounts: string[]) {
  return {
    apiVersion: "rbac.authorization.k8s.io/v1",
    kind: kind === "Role" ? "RoleBinding" : "ClusterRoleBinding",
    metadata: namespace ? { name, namespace } : { name },
    roleRef: { apiGroup: "rbac.authorization.k8s.io", kind, name },
    subjects: accounts.map(account => ({ kind: "ServiceAccount", name: account, namespace: "pepr-system" })),
  };
}

// One rule per resource. Every name the Roles grant `watch` is listed here,
// because the watcher asks for each of those names at cluster scope.
export function watchClusterRules(): ChartRule[] {
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
  // The TakClient watch has no name filter, so it is cluster-wide. TakClients
  // outside namespace takclients are ignored by the capability.
  return [
    ...grouped.values(),
    { apiGroups: [TAKCLIENT_GROUP], resources: ["takclients"], verbs: ["list", "watch"] },
  ];
}

export function watcherServiceAccount(): string {
  return stringify({
    apiVersion: "v1",
    kind: "ServiceAccount",
    metadata: { name: WATCHER_SA, namespace: "pepr-system" },
  });
}

export function roleManifest(): string {
  const watch = watchClusterRules();
  const sharedWatch = watch.filter(rule => !watcherOnly(rule));
  const watcherWatch = watch.filter(rule => watcherOnly(rule));
  const both = [ADMISSION_SA, WATCHER_SA];
  const docs: object[] = [
    roleDoc("ClusterRole", `${ADMISSION_SA}-watch`, undefined, sharedWatch),
    bindingDoc("ClusterRole", `${ADMISSION_SA}-watch`, undefined, both),
    roleDoc("ClusterRole", `${WATCHER_SA}-watch`, undefined, watcherWatch),
    bindingDoc("ClusterRole", `${WATCHER_SA}-watch`, undefined, [WATCHER_SA]),
  ];
  for (const entry of ROLE_RULES) {
    const shared = entry.rules.filter(rule => !watcherOnly(rule));
    const watcher = entry.rules.filter(rule => watcherOnly(rule));
    if (shared.length > 0) {
      docs.push(roleDoc("Role", ADMISSION_SA, entry.namespace, shared));
      docs.push(bindingDoc("Role", ADMISSION_SA, entry.namespace, both));
    }
    if (watcher.length > 0) {
      docs.push(roleDoc("Role", WATCHER_SA, entry.namespace, watcher));
      docs.push(bindingDoc("Role", WATCHER_SA, entry.namespace, [WATCHER_SA]));
    }
  }
  return docs.map(doc => stringify(doc, { aliasDuplicateObjects: false })).join("---\n");
}

// The generated ClusterRoleBinding names only the admission account. The
// watcher needs the same cluster rules (namespaces, the store CRD,
// peprstores), so it is added as a second subject.
export function bindWatcher(text: string): string {
  const subject = /^  - kind: ServiceAccount\n    name: \S+\n    namespace: pepr-system$/gm;
  const found = text.match(subject);
  if (found?.length !== 1) {
    throw new Error("cluster-role-binding.yaml no longer has one ServiceAccount subject");
  }
  return text.replace(
    found[0],
    `${found[0]}\n  - kind: ServiceAccount\n    name: "${WATCHER_SA}"\n    namespace: pepr-system`,
  );
}

// Points the watcher Deployment at its own ServiceAccount.
export function useWatcherAccount(text: string): string {
  const line = "      serviceAccountName: {{ .Values.uuid }}\n";
  if (text.split(line).length !== 2) {
    throw new Error("watcher-deployment.yaml no longer has one serviceAccountName line");
  }
  return text.replace(line, `      serviceAccountName: ${WATCHER_SA}\n`);
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
  const templates = join(chartDir, "templates");
  writeFileSync(join(templates, "namespaced-roles.yaml"), roleManifest());
  writeFileSync(join(templates, "watcher-service-account.yaml"), watcherServiceAccount());
  for (const [file, edit] of [
    ["cluster-role-binding.yaml", bindWatcher],
    ["watcher-deployment.yaml", useWatcherAccount],
  ] as const) {
    const path = join(templates, file);
    writeFileSync(path, edit(readFileSync(path, "utf8")));
  }
}
