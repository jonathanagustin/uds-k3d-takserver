// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Reconcile and Finalize for TakClient. See ADR 22.
//
// Reconcile signs a client certificate with the TAK CA, writes it, the key,
// the CA, and an ATAK data package to a Secret with the TakClient's name in
// namespace takclients, and
// registers the callsign as a TAK file user with the requested groups.
// Finalize deletes that user, adds the serial to the CRL in Secret
// takserver-crl, and deletes the client's Secret. UDS Core restarts the TAK
// pods that mount takserver-crl when it changes, because TAK reads the CRL
// only at startup.

import { randomBytes } from "node:crypto";
import type { Cluster, SecretDoc } from "../cluster.ts";
import {
  buildCrl,
  crlNextUpdate,
  dataPackage,
  fingerprint,
  issue,
  loadCa,
  type Ca,
  type Issued,
  type Revoked,
} from "./takclient-pki.ts";

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
export const NOT_AFTER = `${GROUP}/not-after`;
export const FINGERPRINT = `${GROUP}/fingerprint`;
export const CALLSIGN = `${GROUP}/callsign`;
export const RETRY = `${GROUP}/finalize-retry`;
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
  request(tls: TakTls, method: string, path: string, body?: unknown): Promise<TakResponse>;
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
// and special). TAK needs one for a file user. Nobody keeps it: the client
// authenticates with its certificate.
export function unusedPassword(): string {
  return `${randomBytes(18).toString("base64url")}Aa1!`;
}

const USERS = "/user-management/api";

export async function register(tak: TakApi, tls: TakTls, callsign: string, groups: string[]): Promise<void> {
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
    password: unusedPassword(),
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
}

export function readCrlState(secret: SecretDoc | undefined): CrlState {
  const pem = decode(secret?.data?.["ca.crl"]);
  let entries: CrlState["entries"] = [];
  try {
    const parsed = JSON.parse(decode(secret?.data?.["revoked.json"]) ?? "[]");
    entries = Array.isArray(parsed) ? parsed : [];
  } catch {
    entries = [];
  }
  const number = Number.parseInt(decode(secret?.data?.number) ?? "0", 10);
  return { entries, number: Number.isNaN(number) ? 0 : number, pem, ca: decode(secret?.data?.["ca-fingerprint"]) };
}

async function writeCrl(cluster: Cluster, ca: Ca, state: CrlState, now: Date): Promise<void> {
  const number = state.number + 1;
  const pem = buildCrl(ca, state.entries, number, now, CRL_DAYS);
  await cluster.applySecret(
    TAK_NAMESPACE,
    CRL_SECRET,
    { "uds.dev/pod-reload": "true", "app.kubernetes.io/part-of": "takserver" },
    {
      "ca.crl": encode(pem),
      "revoked.json": encode(JSON.stringify(state.entries)),
      number: encode(String(number)),
      "ca-fingerprint": encode(fingerprint(ca.pem)),
    },
  );
}

// Writes an empty CRL when there is none, and a fresh one with the same
// entries when nextUpdate is close. Expired entries are dropped then.
export async function ensureCrl(cluster: Cluster, ca: Ca, now: Date): Promise<boolean> {
  return withCrlLock(async () => {
    const state = readCrlState(await cluster.getSecret(TAK_NAMESPACE, CRL_SECRET));
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
    await writeCrl(cluster, ca, state, now);
    return true;
  });
}

export async function revoke(cluster: Cluster, ca: Ca, serial: string, notAfter: string | undefined, now: Date) {
  return withCrlLock(async () => {
    const state = readCrlState(await cluster.getSecret(TAK_NAMESPACE, CRL_SECRET));
    if (state.entries.some(entry => entry.serial === serial)) {
      return;
    }
    state.entries.push({ serial, date: now.toISOString(), notAfter });
    await writeCrl(cluster, ca, state, now);
  });
}

// Reissue when there is no Secret, when the Secret is for another serial or
// callsign, or when less than a third of the lifetime is left.
export function needsIssue(client: TakClientDoc, secret: SecretDoc & { metadata?: { annotations?: Record<string, string> } } | undefined, now: Date): boolean {
  const annotations = secret?.metadata?.annotations ?? {};
  const serial = client.metadata?.annotations?.[SERIAL];
  if (!secret || !serial || annotations[SERIAL] !== serial || annotations[CALLSIGN] !== client.spec?.callsign) {
    return true;
  }
  const days = client.spec?.validityDays ?? DEFAULT_DAYS;
  const notAfter = new Date(annotations[NOT_AFTER] ?? 0).getTime();
  return notAfter - now.getTime() < (days * DAY) / 3;
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

export async function reconcileTakClient(client: TakClientDoc, phase: string, deps: Deps): Promise<void> {
  if (phase === "DELETED" || client.metadata?.deletionTimestamp) {
    return;
  }
  const { cluster } = deps;
  const name = client.metadata!.name!;
  const problem = validate(client.spec);
  if (problem) {
    await setReady(deps, client, "False", "InvalidSpec", problem);
    return;
  }
  if (!deps.domain) {
    await setReady(deps, client, "False", "NoDomain", "The watcher has no DOMAIN for the data package host");
    return;
  }
  const ca = await readCa(cluster);
  if (!ca) {
    await setReady(deps, client, "False", "WaitingForCa", "The TAK CA is not published yet");
    return;
  }
  const now = deps.now();
  await ensureCrl(cluster, ca, now);
  const spec = client.spec!;
  const callsign = spec.callsign!;
  const current = (await cluster.getSecret(CLIENT_NAMESPACE, secretName(client))) as
    | (SecretDoc & { metadata?: { annotations?: Record<string, string> } })
    | undefined;
  let notAfter = current?.metadata?.annotations?.[NOT_AFTER];
  if (needsIssue(client, current, now)) {
    const previous = client.metadata?.annotations?.[SERIAL];
    const issued = issue(ca, callsign, spec.validityDays ?? DEFAULT_DAYS, now);
    const password = randomBytes(16).toString("hex");
    notAfter = issued.notAfter.toISOString();
    const annotations = {
      [SERIAL]: issued.serial,
      [NOT_AFTER]: notAfter,
      [FINGERPRINT]: issued.fingerprint,
      [CALLSIGN]: callsign,
    };
    const data = secretData(callsign, issued, ca, streamHost(deps.domain), password);
    await cluster.applySecretWithAnnotations(
      CLIENT_NAMESPACE,
      secretName(client),
      { "app.kubernetes.io/managed-by": "takserver-oidc", [`${GROUP}/takclient`]: name },
      annotations,
      data,
    );
    await cluster.annotateTakClient(CLIENT_NAMESPACE, name, annotations);
    if (previous && previous !== issued.serial) {
      // The old certificate is replaced, so it should stop working too.
      await revoke(cluster, ca, previous, client.metadata?.annotations?.[NOT_AFTER], now);
    }
  }
  const admin = await readAdmin(cluster, ca);
  if (!admin) {
    await setReady(deps, client, "False", "WaitingForAdmin", "The TAK admin certificate is not published yet");
    return;
  }
  try {
    await register(deps.tak, admin, callsign, spec.groups!);
  } catch (err) {
    deps.log(`TakClient ${name}: ${(err as Error).message}`);
    await setReady(
      deps,
      client,
      "False",
      "TakUnavailable",
      "The certificate is issued, but TAK did not accept the user. It is retried when takserver-messaging is Available",
    );
    return;
  }
  await setReady(deps, client, "True", "Issued", `Secret ${secretName(client)}, expires ${notAfter}`);
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
  const callsign = client.spec?.callsign;
  const admin = await readAdmin(cluster, ca);
  if (callsign && admin) {
    try {
      await unregister(deps.tak, admin, callsign);
    } catch (err) {
      // The CRL is what stops the certificate. A user left behind has no
      // certificate that TAK accepts once the pods restart.
      deps.log(`TakClient ${name}: ${(err as Error).message}`);
    }
  }
  const serial = client.metadata?.annotations?.[SERIAL];
  if (serial) {
    await revoke(cluster, ca, serial, client.metadata?.annotations?.[NOT_AFTER], deps.now());
  }
  await cluster.deleteSecret(CLIENT_NAMESPACE, secretName(client));
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
      await register(deps.tak, admin, callsign!, client.spec!.groups!);
      await setReady(deps, client, "True", "Issued", `Secret ${secretName(client)}, expires ${client.metadata.annotations[NOT_AFTER]}`);
    } catch (err) {
      deps.log(`TakClient ${client.metadata?.name}: ${(err as Error).message}`);
    }
  }
}
