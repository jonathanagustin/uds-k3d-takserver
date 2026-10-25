// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { runtime, type ConfigMapDoc, type StatefulSetDoc } from "../cluster.ts";
import { TAK_NAMESPACE } from "./gateway-ca.ts";
import {
  enqueueIgnite,
  prepareDeployment,
  prepareIgniteConfigMap,
  prepareIgniteStatefulSet,
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

export function onDeploymentMutate(deploy: object): Promise<void> {
  return prepareDeployment(deploy as WorkloadDeploy, process.env, runtime.cluster);
}

export function onIgniteConfigMutate(configMap: object): void {
  prepareIgniteConfigMap(configMap as ConfigMapDoc);
}

export function onIgniteSetMutate(statefulSet: object): void {
  prepareIgniteStatefulSet(statefulSet as StatefulSetDoc);
}

for (const name of TAK_DEPLOYS) {
  When(a.Deployment)
    .IsCreatedOrUpdated()
    .InNamespace(TAK_NAMESPACE)
    .WithName(name)
    .Mutate(request => onDeploymentMutate(request.Raw));
  When(a.Deployment).IsCreatedOrUpdated().InNamespace(TAK_NAMESPACE).WithName(name).Reconcile(onDeployment);
}

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite-configmap")
  .Mutate(request => onIgniteConfigMutate(request.Raw));

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite-configmap")
  .Reconcile(onIgnite);

When(a.StatefulSet)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite")
  .Mutate(request => onIgniteSetMutate(request.Raw));

When(a.StatefulSet)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-ignite")
  .Reconcile(onIgnite);
