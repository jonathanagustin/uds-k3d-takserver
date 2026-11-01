// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { runtime } from "../cluster.ts";
import { TAK_NAMESPACE } from "./gateway-ca.ts";
import {
  enqueueIgnite,
  reconcileDeployment,
  reconcileIgnite,
  TAK_DEPLOYS,
  type WorkloadDeploy,
} from "./workload.ts";

export const Workload = new Capability({
  name: "takserver-workload",
  description: "Startup order, probes, and Ignite timeouts for the TAK workloads",
  namespaces: [TAK_NAMESPACE],
});

const { When } = Workload;

export function onDeployment(deploy: object, phase: string): Promise<void> {
  return reconcileDeployment(deploy as WorkloadDeploy, phase, runtime.cluster, process.env);
}

export function onIgnite(_update: unknown, phase: string): Promise<void> {
  return enqueueIgnite(() => reconcileIgnite(phase, runtime.cluster));
}

for (const name of TAK_DEPLOYS) {
  When(a.Deployment).IsCreatedOrUpdated().InNamespace(TAK_NAMESPACE).WithName(name).Reconcile(onDeployment);
}

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite-configmap")
  .Reconcile(onIgnite);

When(a.StatefulSet)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite")
  .Reconcile(onIgnite);
