// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { runtime } from "../cluster.ts";
import {
  COREDNS_CONFIGMAP,
  COREDNS_NAMESPACE,
  GATEWAYS,
  reconcileCoreDns,
  readCoreDnsEnv,
} from "./coredns-rewrite.ts";

export const CoreDns = new Capability({
  name: "takserver-coredns",
  description: "Rewrite DOMAIN hosts to the Istio gateways inside the cluster",
  namespaces: [COREDNS_NAMESPACE, ...GATEWAYS.map(([namespace]) => namespace)],
});

const { When } = CoreDns;

export function onCoreDns(): Promise<void> {
  return reconcileCoreDns(runtime.cluster, readCoreDnsEnv());
}

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(COREDNS_NAMESPACE)
  .WithName(COREDNS_CONFIGMAP)
  .Reconcile(onCoreDns);

for (const [namespace, service] of GATEWAYS) {
  When(a.Service).IsCreatedOrUpdated().InNamespace(namespace).WithName(service).Reconcile(onCoreDns);
}
