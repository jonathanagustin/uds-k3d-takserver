// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability } from "pepr";
import { runtime } from "../cluster.ts";
import { KEYSTORE_SECRET, reconcileCloudtak } from "./cloudtak-admin.ts";
import { CERT_CONFIGMAP, TAK_NAMESPACE } from "./gateway-ca.ts";

export const CloudtakAdmin = new Capability({
  name: "takserver-cloudtak-admin",
  description: "Copy the TAK admin certificate into the cloudtak namespace",
  namespaces: [TAK_NAMESPACE],
});

const { When } = CloudtakAdmin;

export function onCloudtak(_update: unknown, phase: string): Promise<void> {
  return reconcileCloudtak(phase, runtime.cluster);
}

When(a.ConfigMap)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName(CERT_CONFIGMAP)
  .Reconcile(onCloudtak);

When(a.Secret)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName(KEYSTORE_SECRET)
  .Reconcile(onCloudtak);
