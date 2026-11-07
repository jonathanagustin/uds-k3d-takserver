// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Reconcile and Finalize for TakClient, ADR 24. TAK signs certificates via
// Basic enrollment, giving each a certificate-table row. Finalize revokes
// that row before deleting its file user and Secret. The CRL is a backstop;
// only legacy certificates still require a pod reload.

import { randomBytes, X509Certificate } from "node:crypto";
import type { Cluster, SecretDoc } from "../cluster.ts";
import {
  buildCrl,
  crlNextUpdate,
  dataPackage,
  fingerprint,
  loadCa,
  type Ca,
  type Issued,
  type Revoked,
} from "./takclient-pki.ts";
import { enroll, revokeEnrolled } from "./takclient-enrollment.ts";
import { readCredential, rememberCredential, forgetCredential } from "./takclient-credentials.ts";

export const TAK_NAMESPACE = "takserver";
// TakClients and their Secrets live here and nowhere else, so the watcher's
// Secret access outside takserver is this one namespace. See ADR 22.
export const CLIENT_NAMESPACE = "takclients";
export const GROUP = "tak.jonathanagustin.github.io";
export const CRL_SECRET = "takserver-crl";
export const CA_KEY_SECRET = "takserver-ca-key";
export const KEYSTORE_SECRET = "takserver-keystore";
export const CERTS_SECRET = "takserver-certs";
export const CERT_CONFIGMAP = "cert-migration";
export const SERIAL = `${GROUP}/serial`;
export const NOT_BEFORE = `${GROUP}/not-before`;
export const NOT_AFTER = `${GROUP}/not-after`;
export const FINGERPRINT = `${GROUP}/fingerprint`;
export const ISSUER = `${GROUP}/issuer`;
export const CALLSIGN = `${GROUP}/callsign`;
export const RETRY = `${GROUP}/finalize-retry`;
export const RECONCILE_RETRY = `${GROUP}/reconcile-retry`;
export const DEFAULT_DAYS = 30;
export const MAX_DAYS = 365;
export const CRL_DAYS = 730;
export const CRL_REFRESH_DAYS = 60;
const DAY = 24 * 60 * 60 * 1000;

export interface Condition {
  type: string;
  status: string;
  reason: string;
  message: string;
  lastTransitionTime: string;
  observedGeneration?: number;
}

export interface TakClientDoc {
  metadata?: {
    name?: string;
    namespace?: string;
    generation?: number;
    deletionTimestamp?: string;
    annotations?: Record<string, string>;
  };
  spec?: { callsign?: string; groups?: string[]; validityDays?: number };
  status?: { conditions?: Condition[] };
}

export interface TakTls {
  ca: string;
  cert: string;
  key: string;
  passphrase: string;
}

export interface TakResponse {
  status: number;
  body: string;
}

export interface TakApi {
  request(tls: TakTls, method: string, path: string, body?: unknown,
    options?: { port: 8446; auth: string; contentType: "text/plain" }): Promise<TakResponse>;
}

export interface TakClientCluster extends Cluster {
  patchTakClientStatus(namespace: string, name: string, conditions: Condition[]): Promise<void>;
  annotateTakClient(namespace: string, name: string, annotations: Record<string, string>): Promise<void>;
  listTakClients(namespace: string): Promise<TakClientDoc[]>;
  deleteSecret(namespace: string, name: string): Promise<void>;
  applySecretWithAnnotations(
    namespace: string,
    name: string,
    labels: Record<string, string>,
    annotations: Record<string, string>,
    data: Record<string, string>,
  ): Promise<void>;
}

export interface Deps {
  cluster: TakClientCluster;
  tak: TakApi;
  now: () => Date;
  domain: string;
  log: (msg: string) => void;
}

// TAK's UsernameUtils: at least 4 characters of letters, numbers, dots,
// underscores, and hyphens. A Kubernetes label value allows the same set.
const CALLSIGN_RE = /^[A-Za-z0-9_.-]{4,63}$/;
const GROUP_RE = /^[^\s/][^/]{0,62}$/;

export function validate(spec: TakClientDoc["spec"]): string | undefined {
  const callsign = spec?.callsign ?? "";
  if (!CALLSIGN_RE.test(callsign)) {
    return "spec.callsign must be 4 to 63 letters, numbers, dots, underscores, or hyphens";
  }
  const groups = spec?.groups ?? [];
  if (groups.length === 0 || !groups.every(group => GROUP_RE.test(group))) {
    return "spec.groups must list at least one TAK group name without slashes";
  }
  const days = spec?.validityDays ?? DEFAULT_DAYS;
  if (!Number.isInteger(days) || days < 1 || days > MAX_DAYS) {
    return `spec.validityDays must be a whole number from 1 to ${MAX_DAYS}`;
  }
  return undefined;
}

export function secretName(client: TakClientDoc): string {
  return client.metadata!.name!;
}

function decode(value: string | undefined): string | undefined {
  return value === undefined ? undefined : Buffer.from(value, "base64").toString("utf8");
}

function encode(value: string | Buffer): string {
  return Buffer.from(value).toString("base64");
}

// The CA, its key, and its passphrase. undefined until the cert Job has
// published all three.
export async function readCa(cluster: Cluster): Promise<Ca | undefined> {
  const configMap = await cluster.getConfigMap(TAK_NAMESPACE, CERT_CONFIGMAP);
  const caKey = await cluster.getSecret(TAK_NAMESPACE, CA_KEY_SECRET);
  const keystore = await cluster.getSecret(TAK_NAMESPACE, KEYSTORE_SECRET);
  const caPem = decode(configMap?.binaryData?.["ca.pem"]) ?? configMap?.data?.["ca.pem"];
  const keyPem = decode(caKey?.data?.["ca-do-not-share.key"]);
  const pass = decode(keystore?.data?.CAPASS);
  if (!caPem || !keyPem || pass === undefined) {
    return undefined;
  }
  try {
    return loadCa(caPem, keyPem, pass);
  } catch {
    // A CA in the middle of a rotation (cert-rotation test) or a key that
    // does not open. Nothing is signed until both are readable.
    return undefined;
  }
}

// The admin certificate the watcher uses for TAK's admin API on 8443.
export async function readAdmin(cluster: Cluster, ca: Ca): Promise<TakTls | undefined> {
  const configMap = await cluster.getConfigMap(TAK_NAMESPACE, CERT_CONFIGMAP);
  const certs = await cluster.getSecret(TAK_NAMESPACE, CERTS_SECRET);
  const keystore = await cluster.getSecret(TAK_NAMESPACE, KEYSTORE_SECRET);
  const cert = decode(configMap?.binaryData?.["admin.pem"] ?? certs?.data?.["admin.pem"]);
  const key = decode(certs?.data?.["admin.key"]);
  const passphrase = decode(keystore?.data?.CAPASS);
  if (!cert || !key || passphrase === undefined) {
    return undefined;
  }
  return { ca: ca.pem, cert, key, passphrase };
}

// A password TAK accepts (15 or more characters with upper, lower, digit,
// and special). It is persisted with the client key for Basic enrollment
// and recreation after a messaging restart. Clients authenticate with TLS.
export function unusedPassword(): string {
  return `${randomBytes(18).toString("base64url")}Aa1!`;
}

const USERS = "/user-management/api";

export async function register(tak: TakApi, tls: TakTls, callsign: string, groups: string[], password = unusedPassword()): Promise<void> {
  const update = await tak.request(tls, "PUT", `${USERS}/update-groups`, {
    username: callsign,
    groupList: groups,
    groupListIN: [],
    groupListOUT: [],
  });
  if (update.status < 300) {
    return;
  }
  const created = await tak.request(tls, "POST", `${USERS}/new-user`, {
    username: callsign,
    password,
    groupList: groups,
    groupListIN: [],
    groupListOUT: [],
  });
  if (created.status >= 300) {
    throw new Error(`TAK new-user returned HTTP ${created.status}`);
  }
}

export async function unregister(tak: TakApi, tls: TakTls, callsign: string): Promise<void> {
  const res = await tak.request(tls, "DELETE", `${USERS}/delete-user/${encodeURIComponent(callsign)}`);
  // 400 is TAK's "User not found!", which is the state we want.
  if (res.status >= 300 && res.status !== 400 && res.status !== 404) {
    throw new Error(`TAK delete-user returned HTTP ${res.status}`);
  }
}

export function condition(
  client: TakClientDoc,
  status: "True" | "False",
  reason: string,
  message: string,
  now: Date,
): Condition[] {
  const previous = client.status?.conditions?.find(c => c.type === "Ready");
  const lastTransitionTime =
    previous && previous.status === status ? previous.lastTransitionTime : now.toISOString();
  return [
    {
      type: "Ready",
      status,
      reason,
      message,
      lastTransitionTime,
      observedGeneration: client.metadata?.generation,
    },
  ];
}

function sameCondition(client: TakClientDoc, next: Condition[]): boolean {
  const current = client.status?.conditions?.find(c => c.type === "Ready");
  const want = next[0];
  return (
    current !== undefined &&
    current.status === want.status &&
    current.reason === want.reason &&
    current.message === want.message &&
    current.observedGeneration === want.observedGeneration
  );
}

async function setReady(
  deps: Deps,
  client: TakClientDoc,
  status: "True" | "False",
  reason: string,
  message: string,
): Promise<void> {
  const next = condition(client, status, reason, message, deps.now());
  // A status write is a watch event too, so an unchanged condition is not
  // written again.
  if (sameCondition(client, next)) {
    return;
  }
  await deps.cluster.patchTakClientStatus(CLIENT_NAMESPACE, client.metadata!.name!, next);
}

// One CRL writer at a time. Two finalizers could otherwise read the same
// list and each drop the other's serial.
let crlLock: Promise<unknown> = Promise.resolve();
export function withCrlLock<T>(fn: () => Promise<T>): Promise<T> {
  const run = crlLock.then(fn, fn);
  crlLock = run.catch(() => undefined);
  return run;
}

interface CrlState {
  entries: (Revoked & { notAfter?: string })[];
  number: number;
  pem?: string;
  ca?: string;
  reloadAt?: string;
}

export function readCrlState(secret: SecretDoc | undefined, now = new Date()): CrlState {
  const pem = decode(secret?.data?.["ca.crl"]);
  let entries: CrlState["entries"] = [];
  try {
    const parsed = JSON.parse(decode(secret?.data?.["revoked.json"]) ?? "[]");
    entries = Array.isArray(parsed) ? parsed : [];
  } catch {
    entries = [];
  }
  const number = Number.parseInt(decode(secret?.data?.number) ?? "0", 10);
  // An older module may have requested a reload just before this upgrade.
  // Preserve it rather than cancelling it on the first new-style CRL write.
  const reloadAt = decode(secret?.data?.["reload-at"]) ||
    (secret?.metadata?.labels?.["uds.dev/pod-reload"] === "true" ? now.toISOString() : undefined);
  return { entries, number: Number.isNaN(number) ? 0 : number, pem, ca: decode(secret?.data?.["ca-fingerprint"]), reloadAt };
}

async function writeCrl(cluster: Cluster, ca: Ca, state: CrlState, now: Date): Promise<void> {
  // Do not cancel a legacy revocation reload while another finalizer writes
  // the CRL. Only clear it once every consumer pod was created afterwards.
  if (state.reloadAt) {
    const pods = (await Promise.all(["takserver-api", "takserver-messaging"].map(app => cluster.listPods(TAK_NAMESPACE, app))));
    if (pods.every(found => found.length > 0 && found.every(pod => !pod.metadata?.deletionTimestamp &&
      pod.metadata?.creationTimestamp && new Date(pod.metadata.creationTimestamp) > new Date(state.reloadAt!)))) {
      state.reloadAt = undefined;
    }
  }
  const number = state.number + 1;
  const pem = buildCrl(ca, state.entries, number, now, CRL_DAYS);
  await cluster.applySecret(
    TAK_NAMESPACE,
    CRL_SECRET,
    { "uds.dev/pod-reload": state.reloadAt ? "true" : "false", "app.kubernetes.io/part-of": "takserver" },
    {
      "ca.crl": encode(pem),
      "revoked.json": encode(JSON.stringify(state.entries)),
      number: encode(String(number)),
      "ca-fingerprint": encode(fingerprint(ca.pem)),
      "reload-at": encode(state.reloadAt ?? ""),
    },
  );
}

// Writes an empty CRL when there is none, and a fresh one with the same
// entries when nextUpdate is close. Expired entries are dropped then.
export async function ensureCrl(cluster: Cluster, ca: Ca, now: Date): Promise<boolean> {
  return withCrlLock(async () => {
    const state = readCrlState(await cluster.getSecret(TAK_NAMESPACE, CRL_SECRET), now);
    const next = state.pem ? crlNextUpdate(state.pem) : undefined;
    const sameCa = state.ca === fingerprint(ca.pem);
    if (sameCa && next && next.getTime() - now.getTime() > CRL_REFRESH_DAYS * DAY) {
      return false;
    }
    if (!sameCa) {
      // A new CA: serials from the old one mean nothing to it, and Java
      // needs a CRL from the issuer of each client certificate.
      state.entries = [];
    }
    state.entries = state.entries.filter(entry => !entry.notAfter || new Date(entry.notAfter) > now);
    // Java caches nextUpdate along with the CRL. Refreshing only the file
    // would eventually reject every client when the cached CRL expires.
    // Initial creation needs no reload; periodic refresh and CA changes do.
    if (state.pem) state.reloadAt = now.toISOString();
    await writeCrl(cluster, ca, state, now);
    return true;
  });
}

export async function revoke(cluster: Cluster, ca: Ca, serial: string, notAfter: string | undefined, now: Date, legacy = true) {
  return withCrlLock(async () => {
    const state = readCrlState(await cluster.getSecret(TAK_NAMESPACE, CRL_SECRET), now);
    if (state.entries.some(entry => entry.serial === serial)) {
      return;
    }
    state.entries.push({ serial, date: now.toISOString(), notAfter });
    if (legacy) state.reloadAt = now.toISOString();
    await writeCrl(cluster, ca, state, now);
  });
}

function finiteWindow(notBefore: number, notAfter: number): { notBefore: number; notAfter: number } | undefined {
  if (!Number.isFinite(notBefore) || !Number.isFinite(notAfter) || notAfter <= notBefore) return undefined;
  return { notBefore, notAfter };
}

// The certificate TAK signed is the lifetime. Annotations are only a fallback
// when the PEM cannot be read. spec.validityDays is ignored, and so is a
// fixed fraction of the old 30-day default: a 7-day global certificate would
// otherwise be inside the last ten days on the reconcile that issued it.
function issuedValidity(secret: SecretDoc & { metadata?: { annotations?: Record<string, string> } }): { notBefore: number; notAfter: number } | undefined {
  const pem = decode(secret.data?.["client.pem"]);
  if (pem) {
    try {
      const cert = new X509Certificate(pem);
      return finiteWindow(Date.parse(cert.validFrom), Date.parse(cert.validTo));
    } catch {
      // A damaged PEM falls through to the dates stored at enrollment.
    }
  }
  const stored = secret.metadata!.annotations!;
  return finiteWindow(Date.parse(stored[NOT_BEFORE] ?? ""), Date.parse(stored[NOT_AFTER] ?? ""));
}

// Reissue legacy certificates once, missing or mismatched Secrets, changed
// callsigns, and certificates in the last third of the lifetime TAK issued.
export function needsIssue(client: TakClientDoc, secret: SecretDoc & { metadata?: { annotations?: Record<string, string> } } | undefined, now: Date): boolean {
  const annotations = secret?.metadata?.annotations ?? {};
  const serial = client.metadata?.annotations?.[SERIAL];
  if (!secret || !serial || annotations[SERIAL] !== serial || annotations[CALLSIGN] !== client.spec?.callsign || annotations[ISSUER] !== "tak") {
    return true;
  }
  const window = issuedValidity(secret);
  if (!window) return true;
  return window.notAfter - now.getTime() < (window.notAfter - window.notBefore) / 3;
}

export function streamHost(domain: string): string {
  return `takserver-stream.${domain}`;
}

export function secretData(callsign: string, issued: Issued, ca: Ca, host: string, password: string, uid?: string) {
  return {
    "client.pem": encode(issued.certPem),
    "client.key": encode(issued.keyPem),
    "ca.pem": encode(ca.pem),
    "package.zip": encode(dataPackage({ callsign, host, issued, ca, password, uid })),
    password: encode(password),
  };
}

// Returns true when the failure is one that clears on its own (the CA, the
// admin certificate, or TAK is not ready yet), so the caller tries again.
export async function reconcileTakClient(client: TakClientDoc, phase: string, deps: Deps): Promise<boolean> {
  if (phase === "DELETED" || client.metadata?.deletionTimestamp) {
    return false;
  }
  const { cluster } = deps;
  const name = client.metadata!.name!;
  const problem = validate(client.spec);
  if (problem) {
    await setReady(deps, client, "False", "InvalidSpec", problem);
    return false;
  }
  if (!deps.domain) {
    await setReady(deps, client, "False", "NoDomain", "The watcher has no DOMAIN for the data package host");
    return false;
  }
  const ca = await readCa(cluster);
  if (!ca) {
    await setReady(deps, client, "False", "WaitingForCa", "The TAK CA is not published yet");
    return true;
  }
  const now = deps.now();
  await ensureCrl(cluster, ca, now);
  const spec = client.spec!;
  const callsign = spec.callsign!;
  const current = (await cluster.getSecret(CLIENT_NAMESPACE, secretName(client))) as
    | (SecretDoc & { metadata?: { annotations?: Record<string, string> } })
    | undefined;
  const admin = await readAdmin(cluster, ca);
  if (!admin) {
    await setReady(deps, client, "False", "WaitingForAdmin", "The TAK admin certificate is not published yet");
    return true;
  }
  let notAfter = current?.metadata?.annotations?.[NOT_AFTER];
  // Keep the reusable enrollment capability out of device-delivered data.
  // Losing private state forces revoke/reissue with a new file-user password.
  const priorPassword = await readCredential(cluster, name);
  try {
    const userPassword = priorPassword ?? await rememberCredential(cluster, name);
    if (needsIssue(client, current, now) || !priorPassword) {
      const old = { ...client.metadata?.annotations, ...current?.metadata?.annotations };
      if (old[SERIAL]) {
        if (old[ISSUER] === "tak") {
          if (!old[FINGERPRINT]) throw new Error("The old TAK certificate fingerprint is missing");
          await revokeEnrolled(deps.tak, admin, old[FINGERPRINT]);
        }
        await revoke(cluster, ca, old[SERIAL], old[NOT_AFTER], now, old[ISSUER] !== "tak");
        // Legacy file-user passwords were discarded. Recreate the user with
        // the persisted password only after its old cert is revoked.
        if (old[CALLSIGN]) await unregister(deps.tak, admin, old[CALLSIGN]);
      }
      await register(deps.tak, admin, callsign, spec.groups!, userPassword);
      const issued = await enroll(deps.tak, admin, ca, callsign, userPassword, now);
      const password = randomBytes(16).toString("hex");
      notAfter = issued.notAfter.toISOString();
      const annotations = { [SERIAL]: issued.serial, [NOT_BEFORE]: issued.notBefore.toISOString(), [NOT_AFTER]: notAfter,
        [FINGERPRINT]: issued.fingerprint, [CALLSIGN]: callsign, [ISSUER]: "tak" };
      const data = secretData(callsign, issued, ca, streamHost(deps.domain), password);
      await cluster.applySecretWithAnnotations(CLIENT_NAMESPACE, name,
        { "app.kubernetes.io/managed-by": "takserver-oidc", [`${GROUP}/takclient`]: name }, annotations, data);
      await cluster.annotateTakClient(CLIENT_NAMESPACE, name, annotations);
    } else {
      await register(deps.tak, admin, callsign, spec.groups!, userPassword);
    }
  } catch (err) {
    // Never log response bodies or credentials. A failed enrollment/revoke
    // leaves Ready false and retries; it does not publish a new certificate.
    deps.log(`TakClient ${name}: ${(err as Error).message}`);
    await setReady(deps, client, "False", "TakUnavailable", "TAK enrollment or revocation is unavailable; retrying every minute");
    return true;
  }
  await setReady(deps, client, "True", "Issued", `Secret ${secretName(client)}, expires ${notAfter}`);
  return false;
}

// Returns false to keep the finalizer. The caller retries.
export async function finalizeTakClient(client: TakClientDoc, deps: Deps): Promise<boolean> {
  const { cluster } = deps;
  const name = client.metadata!.name!;
  const ca = await readCa(cluster);
  if (!ca) {
    deps.log(`TakClient ${name}: the TAK CA is missing, so the certificate cannot be revoked yet`);
    return false;
  }
  const current = await cluster.getSecret(CLIENT_NAMESPACE, name);
  const annotations = { ...client.metadata?.annotations, ...current?.metadata?.annotations };
  const callsign = annotations[CALLSIGN] ?? client.spec?.callsign;
  const admin = await readAdmin(cluster, ca);
  const serial = annotations[SERIAL];
  if (annotations[ISSUER] === "tak") {
    if (!admin || !annotations[FINGERPRINT]) return false;
    try {
      await revokeEnrolled(deps.tak, admin, annotations[FINGERPRINT]);
    } catch (err) {
      deps.log(`TakClient ${name}: ${(err as Error).message}`);
      return false;
    }
  }
  if (serial) await revoke(cluster, ca, serial, annotations[NOT_AFTER], deps.now(), annotations[ISSUER] !== "tak");
  // The Basic file user can enroll again. Do not drop the Secret or the
  // finalizer until TAK confirms that user is gone. 400 and 404 are already
  // gone, so a retry after a successful delete is safe.
  if (callsign) {
    if (!admin) {
      deps.log(`TakClient ${name}: the TAK admin certificate is missing, so the enrollment user cannot be deleted yet`);
      return false;
    }
    try {
      await unregister(deps.tak, admin, callsign);
    } catch (err) {
      deps.log(`TakClient ${name}: ${(err as Error).message}`);
      return false;
    }
  }
  await cluster.deleteSecret(CLIENT_NAMESPACE, secretName(client));
  await forgetCredential(cluster, name);
  return true;
}

// TAK keeps file users in memory, so a messaging restart loses them. When
// takserver-messaging is Available again, every TakClient is registered again.
export async function registerAll(deps: Deps): Promise<void> {
  const ca = await readCa(deps.cluster);
  if (!ca) {
    return;
  }
  const admin = await readAdmin(deps.cluster, ca);
  if (!admin) {
    return;
  }
  for (const client of await deps.cluster.listTakClients(CLIENT_NAMESPACE)) {
    const callsign = client.spec?.callsign;
    if (client.metadata?.deletionTimestamp || validate(client.spec) || !client.metadata?.annotations?.[SERIAL]) {
      continue;
    }
    try {
      const secret = await deps.cluster.getSecret(CLIENT_NAMESPACE, secretName(client));
      const password = await readCredential(deps.cluster, secretName(client));
      if (!password) {
        await setReady(deps, client, "False", "EnrollmentStateMissing", "Private enrollment state is missing; reissue required");
        await deps.cluster.annotateTakClient(CLIENT_NAMESPACE, secretName(client), { [RECONCILE_RETRY]: deps.now().toISOString() });
        continue;
      }
      await register(deps.tak, admin, callsign!, client.spec!.groups!, password);
      if (needsIssue(client, secret, deps.now())) {
        await setReady(deps, client, "False", "MigrationRequired", "The client certificate must be reissued by TAK");
        await deps.cluster.annotateTakClient(CLIENT_NAMESPACE, secretName(client), { [RECONCILE_RETRY]: deps.now().toISOString() });
        continue;
      }
      await setReady(deps, client, "True", "Issued", `Secret ${secretName(client)}, expires ${client.metadata.annotations[NOT_AFTER]}`);
    } catch (err) {
      deps.log(`TakClient ${client.metadata?.name}: ${(err as Error).message}`);
    }
  }
}
