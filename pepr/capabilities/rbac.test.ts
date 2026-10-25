// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// The chart's ClusterRole is what `pepr build` emits from the capability
// bindings plus package.json `pepr.rbac`. Watch bindings only grant `watch`.
// This locks the merged list: a new verb or resource fails the test.
// `npm test` sets PEPR_MODE=build, which is what registers the watches.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

interface Rule {
  apiGroups: string[];
  resources: string[];
  verbs: string[];
}

const EXPECTED: Rule[] = [
  { apiGroups: [""], resources: ["configmaps"], verbs: ["get", "patch", "watch"] },
  { apiGroups: [""], resources: ["namespaces"], verbs: ["create", "get"] },
  { apiGroups: [""], resources: ["pods"], verbs: ["get", "list"] },
  { apiGroups: [""], resources: ["secrets"], verbs: ["create", "get", "patch", "watch"] },
  { apiGroups: [""], resources: ["services"], verbs: ["get", "watch"] },
  { apiGroups: ["apiextensions.k8s.io"], resources: ["customresourcedefinitions"], verbs: ["create", "patch"] },
  { apiGroups: ["apps"], resources: ["deployments"], verbs: ["get", "patch", "watch"] },
  { apiGroups: ["apps"], resources: ["deployments/scale"], verbs: ["get", "patch", "update"] },
  { apiGroups: ["apps"], resources: ["statefulsets"], verbs: ["get", "patch", "watch"] },
  { apiGroups: ["networking.istio.io"], resources: ["destinationrules"], verbs: ["get", "watch"] },
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
