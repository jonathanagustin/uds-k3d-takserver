// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { a, Capability, Log } from "pepr";
import { runtime, TakClient, type DeploymentDoc } from "../cluster.ts";
import {
  CA_KEY_SECRET,
  CERT_CONFIGMAP,
  CLIENT_NAMESPACE,
  ensureCrl,
  finalizeTakClient,
  KEYSTORE_SECRET,
  readCa,
  reconcileTakClient,
  registerAll,
  RETRY,
  TAK_NAMESPACE,
  type Deps,
  type TakClientDoc,
} from "./takclient.ts";

export const TakClients = new Capability({
  name: "takserver-takclient",
  description: "Issue TAK client certificates and data packages from TakClient resources",
  namespaces: [CLIENT_NAMESPACE, TAK_NAMESPACE],
});

const { When } = TakClients;

export function deps(): Deps {
  return {
    cluster: runtime.takCluster,
    tak: runtime.tak,
    now: () => new Date(),
    domain: process.env.DOMAIN ?? "",
    log: msg => Log.warn(msg),
  };
}

export function onTakClient(client: object, phase: string): Promise<void> {
  return reconcileTakClient(client as TakClientDoc, phase, deps());
}

export const FINALIZE_RETRY_MS = 30000;

// Pepr removes the finalizer unless the callback returns false. On false,
// a later annotation write sends another update, which runs this again.
export async function onFinalize(client: object): Promise<boolean> {
  const d = deps();
  const doc = client as TakClientDoc;
  let done = false;
  try {
    done = await finalizeTakClient(doc, d);
  } catch (err) {
    d.log(`TakClient ${doc.metadata?.name}: finalize failed: ${(err as Error).message}`);
  }
  if (!done) {
    await d.cluster.sleep(FINALIZE_RETRY_MS);
    await d.cluster.annotateTakClient(CLIENT_NAMESPACE, doc.metadata!.name!, { [RETRY]: d.now().toISOString() });
  }
  return done;
}

// Registers every TakClient again when takserver-messaging goes from no
// available replicas to at least one.
let messagingAvailable = false;
export function resetMessaging(): void {
  messagingAvailable = false;
}

export async function onMessaging(deploy: object, phase: string): Promise<void> {
  const available = phase !== "DELETED" && ((deploy as DeploymentDoc).status?.availableReplicas ?? 0) > 0;
  const rose = available && !messagingAvailable;
  messagingAvailable = available;
  if (rose) {
    await registerAll(deps());
  }
}

// Keeps Secret takserver-crl present and current. TAK pods mount it, so the
// first one must exist before they start.
export async function onCaMaterial(_update: unknown, phase: string): Promise<void> {
  if (phase === "DELETED") {
    return;
  }
  const d = deps();
  const ca = await readCa(d.cluster);
  if (ca) {
    await ensureCrl(d.cluster, ca, d.now());
  }
}

When(TakClient).IsCreatedOrUpdated().InNamespace(CLIENT_NAMESPACE).Reconcile(onTakClient).Finalize(onFinalize);

When(a.Deployment)
  .IsCreatedOrUpdated()
  .InNamespace(TAK_NAMESPACE)
  .WithName("takserver-messaging")
  .Reconcile(onMessaging);

When(a.ConfigMap).IsCreatedOrUpdated().InNamespace(TAK_NAMESPACE).WithName(CERT_CONFIGMAP).Reconcile(onCaMaterial);
When(a.Secret).IsCreatedOrUpdated().InNamespace(TAK_NAMESPACE).WithName(CA_KEY_SECRET).Reconcile(onCaMaterial);
When(a.Secret).IsCreatedOrUpdated().InNamespace(TAK_NAMESPACE).WithName(KEYSTORE_SECRET).Reconcile(onCaMaterial);
