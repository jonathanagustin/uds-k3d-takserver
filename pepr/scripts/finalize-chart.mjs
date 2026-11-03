// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Adjusts the chart that `pepr build` writes. Two things in it do not fit a
// module that lives in the namespace UDS Core already owns.
//
// 1. The generated webhook matches pods in every namespace except
//    kube-system and pepr-system, and fails closed. An outage of this module
//    would then block every pod in the cluster, including the Istio CNI pods
//    the module itself needs after a node restart. It is narrowed to the TAK
//    pods, Deployments, and Ignite objects in takserver, so an outage only
//    holds those back. Pepr's chart values for the timeout and the failure
//    policy are kept out of the webhook path and CA bundle. See
//    webhook-scope.ts.
// 2. The chart creates the pepr-system Namespace. UDS Core owns it, and Helm
//    refuses to adopt an object that another release owns.
//
// Each edit throws when its anchor is missing, so a Pepr upgrade that changes
// the template fails the build instead of shipping a wider webhook.

import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { applyChartRbac } from "./rbac-scope.ts";
import { failurePolicy, pinLiterals, scopeWebhook } from "./webhook-scope.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const chart = join(root, "dist", `${pkg.pepr.uuid}-chart`);

const webhookPath = join(chart, "templates", "mutation-webhook.yaml");
const webhook = readFileSync(webhookPath, "utf8");
const timeout = pkg.pepr.webhookTimeout ?? 10;
writeFileSync(webhookPath, scopeWebhook(pinLiterals(webhook, timeout, failurePolicy(pkg.pepr.onError))));

rmSync(join(chart, "templates", "namespace.yaml"));
applyChartRbac(chart);
console.log(`finalized ${chart}`);
