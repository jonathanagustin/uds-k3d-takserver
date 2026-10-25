// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// The chart's ClusterRole is what `pepr build` emits from the capability
// bindings plus package.json `pepr.rbac`. Watch bindings only grant `watch`.
// finalize-chart.mjs then moves those watches into namespaced Roles and adds
// a name-scoped ClusterRole, because the watcher lists at cluster scope.
// `npm test` sets PEPR_MODE=build, which is what registers the watches.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import { applyChartRbac, clusterRules, roleManifest } from "../scripts/rbac-scope.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

interface Rule {
  apiGroups: string[];
  resources: string[];
  verbs: string[];
}

interface ManifestRule {
  resources?: string[];
  verbs?: string[];
  resourceNames?: string[];
}

interface ManifestDoc {
  kind: string;
  metadata: { namespace?: string };
  rules?: ManifestRule[];
}

const EXPECTED: Rule[] = [
  { apiGroups: [""], resources: ["configmaps"], verbs: ["watch"] },
  { apiGroups: [""], resources: ["namespaces"], verbs: ["create", "get"] },
  { apiGroups: [""], resources: ["secrets"], verbs: ["watch"] },
  { apiGroups: [""], resources: ["services"], verbs: ["watch"] },
  { apiGroups: ["apiextensions.k8s.io"], resources: ["customresourcedefinitions"], verbs: ["create", "patch"] },
  { apiGroups: ["apps"], resources: ["deployments"], verbs: ["watch"] },
  { apiGroups: ["apps"], resources: ["statefulsets"], verbs: ["watch"] },
  { apiGroups: ["networking.istio.io"], resources: ["destinationrules"], verbs: ["watch"] },
  { apiGroups: ["pepr.dev"], resources: ["peprstores"], verbs: ["create", "get", "patch", "watch"] },
];

function generatedRules(): Rule[] {
  const source = `
import { clusterRole } from "pepr/src/lib/assets/rbac.ts";
import cfg from "./package.json" with { type: "json" };
import { CloudtakAdmin } from "./capabilities/cloudtak-admin-capability.ts";
import { CoreDns } from "./capabilities/coredns-rewrite-capability.ts";
import { GatewayCa } from "./capabilities/gateway-ca-capability.ts";
import { OidcRender } from "./capabilities/oidc-render-capability.ts";
import { Workload } from "./capabilities/workload-capability.ts";

const role = clusterRole(
  "takserver-oidc",
  [OidcRender, CoreDns, GatewayCa, CloudtakAdmin, Workload],
  cfg.pepr.rbacMode,
  cfg.pepr.rbac,
);
const rules = (role.rules ?? []).map(rule => ({
  apiGroups: [...(rule.apiGroups ?? [])].sort(),
  resources: [...(rule.resources ?? [])].sort(),
  verbs: [...(rule.verbs ?? [])].sort(),
}));
rules.sort((a, b) => (a.apiGroups + "/" + a.resources).localeCompare(b.apiGroups + "/" + b.resources));
process.stdout.write(JSON.stringify(rules));
`;
  // Node's test runner adds NODE_V8_COVERAGE back onto a child process.
  // Point that directory somewhere the runner does not read, or this import
  // overwrites the reconcile tests' coverage.
  const env = { ...process.env, PEPR_MODE: "build", LOG_LEVEL: "silent", NODE_V8_COVERAGE: "/tmp/pepr-rbac-nocov" };
  const result = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e", source], {
    cwd: root,
    env,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout) as Rule[];
}

test("the generated ClusterRole matches the scoped allow list", () => {
  const rules = generatedRules();
  for (const rule of rules) {
    for (const values of [rule.apiGroups, rule.resources, rule.verbs]) {
      assert.equal(values.includes("*"), false);
    }
  }
  assert.deepEqual(rules, EXPECTED);
});

test("the chart moves watched objects into namespaced Roles", () => {
  const scoped = clusterRules(EXPECTED);
  const resources = scoped.flatMap(rule => rule.resources);
  for (const moved of ["configmaps", "pods", "secrets", "services", "deployments", "deployments/scale", "statefulsets", "destinationrules"]) {
    assert.equal(resources.includes(moved), false, moved);
  }
  const namespaceRule = scoped.find(rule => rule.resources?.[0] === "namespaces");
  assert.deepEqual(namespaceRule?.verbs, ["create", "get"]);
  assert.equal(scoped.every(rule => rule.resourceNames === undefined), true);
  assert.equal(scoped.some(rule => rule.resources?.[0] === "peprstores"), true);
  const text = roleManifest();
  for (const name of [
    "core-config",
    "cert-migration",
    "takserver-ignite-configmap",
    "takserver-startup",
    "takserver-keystore",
    "cloudtak-tak-admin",
    "takserver-web-ca",
    "coredns-custom",
    "coredns",
    "takserver-web",
    "takserver-config",
    "takserver-messaging",
    "takserver-api",
    "takserver-plugins",
    "takserver-ignite",
    "tenant-ingressgateway",
    "passthrough-ingressgateway",
    "admin-ingressgateway",
    "istio-tenant-gateway",
    "istio-passthrough-gateway",
    "istio-admin-gateway",
    "kube-system",
    "cloudtak",
  ]) {
    assert.equal(text.includes(name), true, name);
  }
  const roles = text
    .split(/^---\n/m)
    .map(part => part.trim())
    .filter(part => part.startsWith("apiVersion"))
    .map(part => parse(part) as ManifestDoc);
  for (const role of roles) {
    if (role.kind !== "Role") {
      continue;
    }
    for (const rule of role.rules ?? []) {
      if ((rule.verbs ?? []).includes("watch")) {
        assert.equal(
          (rule.verbs ?? []).includes("list"),
          true,
          `${role.metadata.namespace ?? ""} ${(rule.resources ?? []).join(",")} watch without list`,
        );
      }
    }
  }
  const takserver = roles.find(role => role.kind === "Role" && role.metadata.namespace === "takserver");
  assert.ok(takserver);
  const startupDelete = (takserver.rules ?? []).find(
    (rule: ManifestRule) =>
      (rule.resources ?? []).join(",") === "configmaps" && (rule.verbs ?? []).includes("delete"),
  );
  assert.deepEqual(startupDelete?.resourceNames, ["takserver-startup"]);
  assert.deepEqual(startupDelete?.verbs, ["delete"]);
  const clusterWatch = roles.find(role => role.kind === "ClusterRole");
  assert.ok(clusterWatch);
  assert.equal(
    roles.some(role => role.kind === "ClusterRoleBinding"),
    true,
  );
  for (const rule of clusterWatch.rules ?? []) {
    assert.deepEqual(rule.verbs, ["list", "watch"]);
    assert.equal((rule.resources ?? []).includes("pods"), false);
    assert.ok((rule.resourceNames ?? []).length > 0);
  }
  const watched = new Map<string, string[]>();
  for (const role of roles) {
    if (role.kind !== "Role") {
      continue;
    }
    for (const rule of role.rules ?? []) {
      if (!(rule.verbs ?? []).includes("watch")) {
        continue;
      }
      const key = (rule.resources ?? []).join(",");
      const names = watched.get(key) ?? [];
      for (const name of rule.resourceNames ?? []) {
        if (!names.includes(name)) {
          names.push(name);
        }
      }
      watched.set(key, names);
    }
  }
  for (const [resource, names] of watched) {
    const match: ManifestRule | undefined = (clusterWatch.rules ?? []).find(
      (item: ManifestRule) => (item.resources ?? []).join(",") === resource,
    );
    assert.ok(match, resource);
    for (const name of names) {
      assert.equal((match.resourceNames ?? []).includes(name), true, `${resource} ${name}`);
    }
  }
  assert.equal(text.includes("*"), false);
  const dir = mkdtempSync(join(tmpdir(), "pepr-rbac-"));
  mkdirSync(join(dir, "templates"));
  writeFileSync(
    join(dir, "values.yaml"),
    "image: example\nrbac:\n  - apiGroups: [\"\"]\n    resources: [\"namespaces\"]\n    verbs: [\"get\", \"create\"]\n  - apiGroups: [\"\"]\n    resources: [\"secrets\"]\n    verbs: [\"watch\"]\n",
  );
  applyChartRbac(dir);
  const values = parse(readFileSync(join(dir, "values.yaml"), "utf8")) as { image: string; rbac: Rule[] };
  assert.equal(values.image, "example");
  assert.equal(values.rbac.some(rule => rule.resources.includes("secrets")), false);
  assert.equal(readFileSync(join(dir, "templates", "namespaced-roles.yaml"), "utf8").includes("takserver-keystore"), true);
  assert.throws(() => clusterRules([]), /empty/);
  assert.throws(() => clusterRules([{ apiGroups: [""], resources: ["namespaces"], verbs: ["get"] }]), /watched resources/);
});
