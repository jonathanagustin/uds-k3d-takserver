// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { DestinationRule, runtime } from "../cluster.ts";
import { CERT_CONFIGMAP, GATEWAY_DESTINATION_RULE, reconcileGatewayCa, TAK_NAMESPACE } from "./gateway-ca.ts";

export const GatewayCa = new Capability({
  name: "takserver-gateway-ca",
  description: "Copy the TAK CA certificate to the tenant gateway namespace",
  namespaces: [TAK_NAMESPACE],
});

const { When } = GatewayCa;

export function onGatewayCa(_update: unknown, phase: string): Promise<void> {
  return reconcileGatewayCa(phase, runtime.cluster);
}

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName(CERT_CONFIGMAP)
  .Reconcile(onGatewayCa);

When(DestinationRule)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName(GATEWAY_DESTINATION_RULE)
  .Reconcile(onGatewayCa);
