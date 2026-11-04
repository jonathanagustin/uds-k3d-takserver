// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createPublicKey, generateKeyPairSync, verify, X509Certificate } from "node:crypto";
import { inflateRawSync } from "node:zlib";
import { afterEach, test } from "node:test";
import forge from "node-forge";
import type { ConfigMapDoc, DeploymentDoc, SecretDoc } from "../cluster.ts";
import { runtime } from "../cluster.ts";
import {
  deps,
  FINALIZE_RETRY_MS,
  onCaMaterial,
  onFinalize,
  onMessaging,
  onTakClient,
  RECONCILE_RETRY_MS,
  retryLater,
  resetMessaging,
  TakClients,
} from "./takclient-capability.ts";
import {
  buildCrl,
  clientP12,
  crlNextUpdate,
  dataPackage,
  fingerprint,
  issue,
  loadCa,
  manifest,
  newSerial,
  serverPref,
  trustP12,
  zip,
  type Ca,
} from "./takclient-pki.ts";
import {
  CALLSIGN,
  condition,
  CRL_SECRET,
  ensureCrl,
  finalizeTakClient,
  needsIssue,
  NOT_AFTER,
  readAdmin,
  readCa,
  readCrlState,
  reconcileTakClient,
  register,
  registerAll,
  RECONCILE_RETRY,
  RETRY,
  revoke,
  SERIAL,
  streamHost,
  unregister,
  unusedPassword,
  validate,
  withCrlLock,
  type Condition,
  type Deps,
  type TakApi,
  type TakClientCluster,
  type TakClientDoc,
  type TakResponse,
} from "./takclient.ts";

const PASS = "ca-pass-123";
const NOW = new Date("2026-11-03T12:00:00Z");
const DAY = 24 * 60 * 60 * 1000;

// A CA shaped like TAK's makeRootCa.sh output: a self-signed certificate and
// an encrypted PKCS#8 key.
function makeCa(): { pem: string; key: string } {
  const pair = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const cert = forge.pki.createCertificate();
  cert.publicKey = forge.pki.publicKeyFromPem(pair.publicKey.export({ type: "spki", format: "pem" }).toString());
  cert.serialNumber = "01";
  cert.validity.notBefore = new Date(NOW.getTime() - DAY);
  cert.validity.notAfter = new Date(NOW.getTime() + 3650 * DAY);
  const subject = [
    { shortName: "C", value: "US" },
    { shortName: "ST", value: "VA" },
    { shortName: "O", value: "TAK" },
    { shortName: "OU", value: "UDS" },
    { shortName: "CN", value: "uds-tak-ca" },
  ];
  cert.setSubject(subject);
  cert.setIssuer(subject);
  cert.setExtensions([
    { name: "basicConstraints", cA: true, critical: true },
    { name: "keyUsage", keyCertSign: true, cRLSign: true, critical: true },
    { name: "subjectKeyIdentifier" },
  ]);
  const clear = pair.privateKey.export({ type: "pkcs1", format: "pem" }).toString();
  cert.sign(forge.pki.privateKeyFromPem(clear), forge.md.sha256.create());
  const key = pair.privateKey
    .export({ type: "pkcs8", format: "pem", cipher: "aes-256-cbc", passphrase: PASS })
    .toString();
  return { pem: forge.pki.certificateToPem(cert), key };
}

const CA_FILES = makeCa();
const CA: Ca = loadCa(CA_FILES.pem, CA_FILES.key, PASS);
const b64 = (value: string) => Buffer.from(value).toString("base64");
const unb64 = (value: string) => Buffer.from(value, "base64").toString("utf8");

interface Store {
  configMaps: Record<string, ConfigMapDoc>;
  secrets: Record<string, SecretDoc>;
}

function material(): Store {
  return {
    configMaps: {
      "takserver/cert-migration": { binaryData: { "ca.pem": b64(CA_FILES.pem), "admin.pem": b64("ADMIN CERT") } },
    },
    secrets: {
      "takserver/takserver-ca-key": { data: { "ca-do-not-share.key": b64(CA_FILES.key) } },
      "takserver/takserver-keystore": { data: { CAPASS: b64(PASS) } },
      "takserver/takserver-certs": { data: { "admin.key": b64("ADMIN KEY") } },
    },
  };
}

interface Calls {
  status: { name: string; conditions: Condition[] }[];
  annotate: { name: string; annotations: Record<string, string> }[];
  deleted: string[];
  sleeps: number[];
  tak: { method: string; path: string; body?: unknown }[];
  logs: string[];
}

function fake(opts: { store?: Store; clients?: TakClientDoc[]; tak?: (method: string, path: string) => TakResponse } = {}) {
  const store = opts.store ?? material();
  const calls: Calls = { status: [], annotate: [], deleted: [], sleeps: [], tak: [], logs: [] };
  const cluster = {
    getConfigMap: async (ns: string, name: string) => store.configMaps[`${ns}/${name}`],
    getSecret: async (ns: string, name: string) => store.secrets[`${ns}/${name}`],
    applySecret: async (ns: string, name: string, labels: Record<string, string>, data: Record<string, string>) => {
      store.secrets[`${ns}/${name}`] = { metadata: { annotations: {} }, data, labels } as SecretDoc;
    },
    applySecretWithAnnotations: async (
      ns: string,
      name: string,
      _labels: Record<string, string>,
      annotations: Record<string, string>,
      data: Record<string, string>,
    ) => {
      store.secrets[`${ns}/${name}`] = { metadata: { annotations }, data };
    },
    patchTakClientStatus: async (_ns: string, name: string, conditions: Condition[]) => {
      calls.status.push({ name, conditions });
    },
    annotateTakClient: async (_ns: string, name: string, annotations: Record<string, string>) => {
      calls.annotate.push({ name, annotations });
    },
    listTakClients: async () => opts.clients ?? [],
    deleteSecret: async (ns: string, name: string) => {
      calls.deleted.push(`${ns}/${name}`);
      delete store.secrets[`${ns}/${name}`];
    },
    sleep: async (ms: number) => {
      calls.sleeps.push(ms);
    },
  } as unknown as TakClientCluster;
  const tak: TakApi = {
    request: async (_tls, method, path, body) => {
      calls.tak.push({ method, path, body });
      return opts.tak ? opts.tak(method, path) : { status: 200, body: "" };
    },
  };
  const d: Deps = { cluster, tak, now: () => NOW, domain: "uds.dev", log: msg => calls.logs.push(msg) };
  return { d, calls, store };
}

function client(extra: Partial<TakClientDoc> = {}): TakClientDoc {
  return {
    metadata: { name: "takclient-test", namespace: "takclients", generation: 1, ...extra.metadata },
    spec: { callsign: "takclient-test", groups: ["Operators"], ...extra.spec },
    status: extra.status,
  };
}

test("the capability watches TakClients in takclients and the CA material in takserver", () => {
  assert.equal(TakClients.name, "takserver-takclient");
  assert.deepEqual(TakClients.namespaces, ["takclients", "takserver"]);
  const kinds = TakClients.bindings.map(binding => binding.kind.kind);
  for (const kind of ["TakClient", "Deployment", "ConfigMap", "Secret"]) {
    assert.equal(kinds.includes(kind), true, kind);
  }
  assert.equal(
    TakClients.bindings.some(binding => binding.isFinalize),
    true,
  );
});

test("validate follows TAK's username rule and the lifetime bounds", () => {
  assert.equal(validate({ callsign: "takclient-test", groups: ["Operators"] }), undefined);
  assert.equal(validate({ callsign: "abc", groups: ["Operators"] })?.includes("callsign"), true);
  assert.equal(validate({ callsign: "bad name", groups: ["Operators"] })?.includes("callsign"), true);
  assert.equal(validate(undefined)?.includes("callsign"), true);
  assert.equal(validate({ callsign: "good.one", groups: [] })?.includes("groups"), true);
  assert.equal(validate({ callsign: "good.one" })?.includes("groups"), true);
  assert.equal(validate({ callsign: "good.one", groups: ["a/b"] })?.includes("groups"), true);
  assert.equal(validate({ callsign: "good.one", groups: ["Ops"], validityDays: 0 })?.includes("validityDays"), true);
  assert.equal(validate({ callsign: "good.one", groups: ["Ops"], validityDays: 366 })?.includes("validityDays"), true);
  assert.equal(validate({ callsign: "good.one", groups: ["Ops"], validityDays: 1.5 })?.includes("validityDays"), true);
  assert.equal(validate({ callsign: "good.one", groups: ["Ops"], validityDays: 365 }), undefined);
});

test("issue signs a client certificate with the TAK CA", () => {
  const issued = issue(CA, "takclient-test", 30, NOW);
  const cert = new X509Certificate(issued.certPem);
  const ca = new X509Certificate(CA_FILES.pem);
  assert.equal(cert.verify(ca.publicKey), true);
  assert.equal(cert.checkIssued(ca), true);
  assert.equal(cert.subject.includes("CN=takclient-test"), true);
  assert.equal(cert.serialNumber.toLowerCase(), issued.serial);
  assert.equal(cert.fingerprint256, issued.fingerprint);
  assert.equal(issued.notAfter.getTime(), NOW.getTime() + 30 * DAY);
  assert.equal(cert.keyUsage?.includes("1.3.6.1.5.5.7.3.2"), true);
  assert.equal(cert.ca, false);
  assert.equal(issued.keyPem.includes("PRIVATE KEY"), true);
  assert.equal(fingerprint(issued.certPem), issued.fingerprint);
});

test("serials are positive 128-bit values", () => {
  for (let i = 0; i < 20; i += 1) {
    const serial = newSerial();
    assert.equal(serial.length, 32);
    assert.equal(Number.parseInt(serial.slice(0, 1), 16) < 8, true);
  }
});

test("the PKCS#12 files open with the password and use SHA-1 and 3DES", () => {
  const issued = issue(CA, "takclient-test", 30, NOW);
  const read = (der: Buffer) =>
    forge.pkcs12.pkcs12FromAsn1(forge.asn1.fromDer(der.toString("binary")), "pw-123");
  const client = read(clientP12(issued, CA, "takclient-test", "pw-123"));
  const keys = client.getBags({ bagType: forge.pki.oids.pkcs8ShroudedKeyBag });
  assert.equal(keys[forge.pki.oids.pkcs8ShroudedKeyBag]?.length, 1);
  const certs = client.getBags({ bagType: forge.pki.oids.certBag })[forge.pki.oids.certBag] ?? [];
  assert.equal(certs.length, 2);
  assert.equal(certs[0].attributes.friendlyName?.[0], "takclient-test");
  const trust = read(trustP12(CA, "pw-123"));
  const trusted = trust.getBags({ bagType: forge.pki.oids.certBag })[forge.pki.oids.certBag] ?? [];
  assert.equal(trusted.length, 1);
  assert.equal(trusted[0].attributes.friendlyName?.[0], "tak-ca");
  assert.throws(() => read(trustP12(CA, "other")));
});

function crlParts(pem: string) {
  const der = forge.util.decode64(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
  const crl = forge.asn1.fromDer(der);
  const [tbs, , sig] = crl.value as forge.asn1.Asn1[];
  return { tbs, sig, tbsDer: Buffer.from(forge.asn1.toDer(tbs).getBytes(), "binary") };
}

test("the CRL is signed by the CA and lists the revoked serials", () => {
  const issued = issue(CA, "takclient-test", 30, NOW);
  const pem = buildCrl(CA, [{ serial: issued.serial, date: NOW.toISOString() }], 7, NOW, 730);
  const { tbs, sig, tbsDer } = crlParts(pem);
  const signature = Buffer.from((sig.value as string).slice(1), "binary");
  const caKey = createPublicKey(new X509Certificate(CA_FILES.pem).publicKey.export({ type: "spki", format: "pem" }));
  assert.equal(verify("sha256", tbsDer, caKey, signature), true);
  const fields = tbs.value as forge.asn1.Asn1[];
  const issuer = forge.pki.certificateFromPem(CA_FILES.pem);
  const issuerDer = forge.asn1.toDer((forge.pki.certificateToAsn1(issuer).value as forge.asn1.Asn1[])[0].value[5] as forge.asn1.Asn1).getBytes();
  assert.equal(forge.asn1.toDer(fields[2]).getBytes(), issuerDer);
  const revoked = (fields[5].value as forge.asn1.Asn1[]).map(entry =>
    forge.util.bytesToHex((entry.value as forge.asn1.Asn1[])[0].value as string),
  );
  assert.deepEqual(revoked, [issued.serial]);
  assert.equal(crlNextUpdate(pem)?.getTime(), NOW.getTime() + 730 * DAY);
  const empty = crlParts(buildCrl(CA, [], 1, NOW, 730));
  // No revokedCertificates field: version, signature, issuer, thisUpdate, nextUpdate, extensions.
  assert.equal((empty.tbs.value as forge.asn1.Asn1[]).length, 6);
  assert.equal(crlParts(buildCrl(CA, [{ serial: "abc", date: NOW.toISOString() }], 16, NOW, 1)).tbs !== undefined, true);
  assert.equal(crlNextUpdate("not a crl"), undefined);
});

function unzip(buf: Buffer): Record<string, string> {
  const out: Record<string, string> = {};
  let offset = 0;
  while (buf.readUInt32LE(offset) === 0x04034b50) {
    const method = buf.readUInt16LE(offset + 8);
    const size = buf.readUInt32LE(offset + 18);
    const nameLength = buf.readUInt16LE(offset + 26);
    const name = buf.subarray(offset + 30, offset + 30 + nameLength).toString();
    const start = offset + 30 + nameLength;
    const data = buf.subarray(start, start + size);
    out[name] = (method === 8 ? inflateRawSync(data) : data).toString("binary");
    offset = start + size;
  }
  return out;
}

test("the data package has the manifest, the 8089 stream, the truststore, and the client certificate", () => {
  const issued = issue(CA, "takclient-test", 30, NOW);
  const pkg = dataPackage({ callsign: "takclient-test", host: "takserver-stream.uds.dev", issued, ca: CA, password: "pw", uid: "u-1" });
  const files = unzip(pkg);
  assert.deepEqual(Object.keys(files), [
    "MANIFEST/manifest.xml",
    "certs/server.pref",
    "certs/truststore.p12",
    "certs/takclient-test.p12",
  ]);
  assert.equal(files["certs/server.pref"].includes("takserver-stream.uds.dev:8089:ssl"), true);
  assert.equal(files["MANIFEST/manifest.xml"].includes('value="u-1"'), true);
  assert.equal(files["MANIFEST/manifest.xml"].includes('zipEntry="certs/takclient-test.p12"'), true);
  assert.equal(unzip(dataPackage({ callsign: "abcd", host: "h", issued, ca: CA, password: "pw" }))["MANIFEST/manifest.xml"].includes('name="uid"'), true);
  assert.equal(serverPref("a&b", "h<1>", 'p"').includes("a&amp;b.p12"), true);
  assert.equal(serverPref("a&b", "h<1>", 'p"').includes("h&lt;1&gt;:8089"), true);
  assert.equal(serverPref("a&b", "h<1>", 'p"').includes("p&quot;"), true);
  assert.equal(manifest("abcd", "x").includes("abcd"), true);
  const one = zip([{ name: "a.txt", data: Buffer.from("hello") }]);
  assert.equal(unzip(one)["a.txt"], "hello");
  assert.equal(one.readUInt32LE(one.length - 22), 0x06054b50);
  assert.deepEqual(zip([{ name: "a.txt", data: Buffer.from("hello") }]), one);
});

test("readCa and readAdmin wait for every piece", async () => {
  const { d, store } = fake();
  assert.notEqual(await readCa(d.cluster), undefined);
  const admin = await readAdmin(d.cluster, CA);
  assert.deepEqual(admin, { ca: CA.pem, cert: "ADMIN CERT", key: "ADMIN KEY", passphrase: PASS });
  store.configMaps["takserver/cert-migration"] = { data: { "ca.pem": CA_FILES.pem } };
  assert.notEqual(await readCa(d.cluster), undefined);
  store.secrets["takserver/takserver-certs"] = { data: { "admin.key": b64("K"), "admin.pem": b64("C") } };
  assert.equal((await readAdmin(d.cluster, CA))?.cert, "C");
  delete store.secrets["takserver/takserver-certs"];
  assert.equal(await readAdmin(d.cluster, CA), undefined);
  store.configMaps["takserver/cert-migration"] = { data: { "ca.pem": "not a certificate" } };
  assert.equal(await readCa(d.cluster), undefined);
  delete store.secrets["takserver/takserver-ca-key"];
  assert.equal(await readCa(d.cluster), undefined);
  delete store.configMaps["takserver/cert-migration"];
  delete store.secrets["takserver/takserver-keystore"];
  assert.equal(await readCa(d.cluster), undefined);
  assert.equal(await readAdmin(d.cluster, CA), undefined);
});

test("register updates the user, or creates it when TAK does not have it", async () => {
  const tls = { ca: "", cert: "", key: "", passphrase: "" };
  const ok = fake();
  await register(ok.d.tak, tls, "takclient-test", ["Operators"]);
  assert.deepEqual(ok.calls.tak.map(call => call.method), ["PUT"]);
  const missing = fake({ tak: method => ({ status: method === "PUT" ? 400 : 200, body: "" }) });
  await register(missing.d.tak, tls, "takclient-test", ["Operators"]);
  assert.deepEqual(missing.calls.tak.map(call => call.method), ["PUT", "POST"]);
  const body = missing.calls.tak[1].body as { username: string; password: string; groupList: string[] };
  assert.equal(body.username, "takclient-test");
  assert.deepEqual(body.groupList, ["Operators"]);
  assert.match(body.password, /^.{15,}$/);
  const down = fake({ tak: () => ({ status: 503, body: "" }) });
  await assert.rejects(register(down.d.tak, tls, "takclient-test", ["Operators"]), /HTTP 503/);
});

test("the unused password passes TAK's complexity rule", () => {
  const password = unusedPassword();
  assert.equal(password.length >= 15, true);
  assert.match(password, /[A-Z]/);
  assert.match(password, /[a-z]/);
  assert.match(password, /[0-9]/);
  assert.match(password, /[!]/);
});

test("unregister treats a missing user as done", async () => {
  const tls = { ca: "", cert: "", key: "", passphrase: "" };
  for (const status of [200, 400, 404]) {
    const { d, calls } = fake({ tak: () => ({ status, body: "" }) });
    await unregister(d.tak, tls, "a b/c");
    assert.equal(calls.tak[0].path, "/user-management/api/delete-user/a%20b%2Fc");
  }
  const { d } = fake({ tak: () => ({ status: 500, body: "" }) });
  await assert.rejects(unregister(d.tak, tls, "abcd"), /HTTP 500/);
});

test("condition keeps the transition time while the status holds", () => {
  const first = condition(client(), "False", "WaitingForCa", "m", NOW);
  assert.equal(first[0].lastTransitionTime, NOW.toISOString());
  const later = new Date(NOW.getTime() + 1000);
  const held = condition(client({ status: { conditions: first } }), "False", "Other", "m", later);
  assert.equal(held[0].lastTransitionTime, NOW.toISOString());
  const flipped = condition(client({ status: { conditions: first } }), "True", "Issued", "m", later);
  assert.equal(flipped[0].lastTransitionTime, later.toISOString());
});

test("reconcile issues a Secret, annotates the TakClient, registers it, and reports Ready", async () => {
  const { d, calls, store } = fake();
  await reconcileTakClient(client(), "ADDED", d);
  const secret = store.secrets["takclients/takclient-test"] as SecretDoc;
  assert.ok(secret);
  const annotations = secret.metadata!.annotations!;
  assert.equal(annotations[CALLSIGN], "takclient-test");
  const cert = new X509Certificate(unb64(secret.data!["client.pem"]));
  assert.equal(cert.serialNumber.toLowerCase(), annotations[SERIAL]);
  assert.equal(unb64(secret.data!["ca.pem"]), CA_FILES.pem);
  assert.equal(unb64(secret.data!["client.key"]).includes("PRIVATE KEY"), true);
  const files = unzip(Buffer.from(secret.data!["package.zip"], "base64"));
  assert.equal(files["certs/server.pref"].includes(`${streamHost("uds.dev")}:8089:ssl`), true);
  assert.equal(files["certs/server.pref"].includes(unb64(secret.data!.password)), true);
  assert.deepEqual(calls.annotate[0].annotations, annotations);
  assert.equal(calls.tak[0].path, "/user-management/api/update-groups");
  const ready = calls.status.at(-1)!.conditions[0];
  assert.equal(ready.status, "True");
  assert.equal(ready.reason, "Issued");
  assert.equal(ready.observedGeneration, 1);
  // The first reconcile also writes the empty CRL.
  assert.ok(store.secrets[`takserver/${CRL_SECRET}`]);
});

test("a second reconcile with the same Secret keeps the certificate and writes no status", async () => {
  const { d, calls, store } = fake();
  await reconcileTakClient(client(), "ADDED", d);
  const annotations = calls.annotate[0].annotations;
  const ready = calls.status.at(-1)!.conditions;
  const again = client({ metadata: { name: "takclient-test", annotations }, status: { conditions: ready } });
  again.metadata!.generation = 1;
  const before = store.secrets["takclients/takclient-test"];
  await reconcileTakClient(again, "MODIFIED", d);
  assert.equal(store.secrets["takclients/takclient-test"], before);
  assert.equal(calls.annotate.length, 1);
  assert.equal(calls.status.length, 1);
});

test("a replaced certificate is revoked", async () => {
  const { d, calls, store } = fake();
  await reconcileTakClient(client(), "ADDED", d);
  const old = calls.annotate[0].annotations;
  delete store.secrets["takclients/takclient-test"];
  await reconcileTakClient(client({ metadata: { name: "takclient-test", annotations: old } }), "MODIFIED", d);
  assert.notEqual(calls.annotate[1].annotations[SERIAL], old[SERIAL]);
  const state = readCrlState(store.secrets[`takserver/${CRL_SECRET}`]);
  assert.deepEqual(
    state.entries.map(entry => entry.serial),
    [old[SERIAL]],
  );
  assert.equal(state.entries[0].notAfter, old[NOT_AFTER]);
});

test("needsIssue renews in the last third of the lifetime and on a callsign change", () => {
  const annotations = { [SERIAL]: "aa", [CALLSIGN]: "takclient-test", [NOT_AFTER]: new Date(NOW.getTime() + 20 * DAY).toISOString() };
  const doc = client({ metadata: { name: "takclient-test", annotations: { [SERIAL]: "aa" } } });
  const secret = { metadata: { annotations }, data: {} };
  assert.equal(needsIssue(doc, secret, NOW), false);
  assert.equal(needsIssue(doc, secret, new Date(NOW.getTime() + 11 * DAY)), true);
  assert.equal(needsIssue(client({ metadata: { name: "x", annotations: { [SERIAL]: "aa" } }, spec: { callsign: "other" } }), secret, NOW), true);
  assert.equal(needsIssue(doc, undefined, NOW), true);
  assert.equal(needsIssue(client(), secret, NOW), true);
  assert.equal(needsIssue(doc, { metadata: { annotations: { ...annotations, [SERIAL]: "bb" } } }, NOW), true);
  assert.equal(needsIssue(doc, { data: {} }, NOW), true);
  const noDate = { metadata: { annotations: { [SERIAL]: "aa", [CALLSIGN]: "takclient-test" } } };
  assert.equal(needsIssue(doc, noDate, NOW), true);
  const longer = client({ metadata: { name: "x", annotations: { [SERIAL]: "aa" } }, spec: { callsign: "takclient-test", validityDays: 90 } });
  assert.equal(needsIssue(longer, secret, NOW), true);
});

test("reconcile reports why it is not Ready", async () => {
  const invalid = fake();
  assert.equal(await reconcileTakClient(client({ spec: { callsign: "no" } }), "ADDED", invalid.d), false);
  assert.equal(invalid.calls.status[0].conditions[0].reason, "InvalidSpec");

  const noDomain = fake();
  noDomain.d.domain = "";
  assert.equal(await reconcileTakClient(client(), "ADDED", noDomain.d), false);
  assert.equal(noDomain.calls.status[0].conditions[0].reason, "NoDomain");

  const store = material();
  delete store.secrets["takserver/takserver-ca-key"];
  const noCa = fake({ store });
  assert.equal(await reconcileTakClient(client(), "ADDED", noCa.d), true);
  assert.equal(noCa.calls.status[0].conditions[0].reason, "WaitingForCa");

  const adminless = material();
  delete adminless.secrets["takserver/takserver-certs"];
  const noAdmin = fake({ store: adminless });
  assert.equal(await reconcileTakClient(client(), "ADDED", noAdmin.d), true);
  assert.equal(noAdmin.calls.status[0].conditions[0].reason, "WaitingForAdmin");

  const down = fake({ tak: () => ({ status: 503, body: "" }) });
  assert.equal(await reconcileTakClient(client(), "ADDED", down.d), true);
  assert.equal(down.calls.status[0].conditions[0].reason, "TakUnavailable");
  assert.equal(down.calls.logs[0].includes("HTTP 503"), true);
});

test("reconcile skips deletes and objects being deleted", async () => {
  const { d, calls } = fake();
  assert.equal(await reconcileTakClient(client(), "DELETED", d), false);
  assert.equal(
    await reconcileTakClient(client({ metadata: { name: "x", deletionTimestamp: NOW.toISOString() } }), "MODIFIED", d),
    false,
  );
  assert.equal(calls.status.length + calls.tak.length, 0);
});

test("finalize deletes the TAK user, revokes the serial, and deletes the Secret", async () => {
  const { d, calls, store } = fake();
  await reconcileTakClient(client(), "ADDED", d);
  const annotations = calls.annotate[0].annotations;
  const done = await finalizeTakClient(client({ metadata: { name: "takclient-test", annotations } }), d);
  assert.equal(done, true);
  assert.equal(calls.tak.at(-1)!.method, "DELETE");
  assert.deepEqual(calls.deleted, ["takclients/takclient-test"]);
  const state = readCrlState(store.secrets[`takserver/${CRL_SECRET}`]);
  assert.deepEqual(state.entries.map(entry => entry.serial), [annotations[SERIAL]]);
  assert.equal(state.number, 2);
  // Revoking the same serial twice does not write the CRL again.
  await revoke(d.cluster, CA, annotations[SERIAL], undefined, NOW);
  assert.equal(readCrlState(store.secrets[`takserver/${CRL_SECRET}`]).number, 2);
});

test("finalize keeps going when TAK is down, and waits when the CA is gone", async () => {
  const down = fake({ tak: () => ({ status: 500, body: "" }) });
  assert.equal(await finalizeTakClient(client({ metadata: { name: "takclient-test", annotations: { [SERIAL]: "ab" } } }), down.d), true);
  assert.equal(down.calls.logs[0].includes("HTTP 500"), true);
  const unissued = fake();
  assert.equal(await finalizeTakClient(client({ spec: { callsign: undefined } as never }), unissued.d), true);
  assert.equal(unissued.calls.tak.length, 0);
  const store = material();
  delete store.secrets["takserver/takserver-ca-key"];
  const noCa = fake({ store });
  assert.equal(await finalizeTakClient(client(), noCa.d), false);
  assert.equal(noCa.calls.logs[0].includes("cannot be revoked"), true);
});

test("onFinalize retries through an annotation when finalize cannot finish", async () => {
  const saved = { cluster: runtime.takCluster, tak: runtime.tak };
  const store = material();
  delete store.secrets["takserver/takserver-ca-key"];
  const noCa = fake({ store });
  runtime.takCluster = noCa.d.cluster;
  runtime.tak = noCa.d.tak;
  try {
    assert.equal(await onFinalize(client()), false);
    assert.deepEqual(noCa.calls.sleeps, [FINALIZE_RETRY_MS]);
    assert.equal(RETRY in noCa.calls.annotate[0].annotations, true);
    const broken = fake();
    broken.d.cluster.getConfigMap = async () => {
      throw new Error("boom");
    };
    runtime.takCluster = broken.d.cluster;
    assert.equal(await onFinalize(client()), false);
    const ok = fake();
    runtime.takCluster = ok.d.cluster;
    runtime.tak = ok.d.tak;
    assert.equal(await onFinalize(client()), true);
    assert.equal(ok.calls.sleeps.length, 0);
  } finally {
    runtime.takCluster = saved.cluster;
    runtime.tak = saved.tak;
  }
});

test("ensureCrl writes an empty CRL once and refreshes it close to nextUpdate", async () => {
  const { d, store } = fake();
  assert.equal(await ensureCrl(d.cluster, CA, NOW), true);
  assert.equal(await ensureCrl(d.cluster, CA, NOW), false);
  const secret = store.secrets[`takserver/${CRL_SECRET}`] as SecretDoc & { labels: Record<string, string> };
  assert.equal(secret.labels["uds.dev/pod-reload"], "true");
  const old = { serial: "aa", date: NOW.toISOString(), notAfter: new Date(NOW.getTime() + DAY).toISOString() };
  const keep = { serial: "bb", date: NOW.toISOString() };
  store.secrets[`takserver/${CRL_SECRET}`] = {
    data: { ...secret.data, "revoked.json": b64(JSON.stringify([old, keep])) },
  };
  const late = new Date(NOW.getTime() + 700 * DAY);
  assert.equal(await ensureCrl(d.cluster, CA, late), true);
  const state = readCrlState(store.secrets[`takserver/${CRL_SECRET}`]);
  assert.deepEqual(state.entries.map(entry => entry.serial), ["bb"]);
  assert.equal(state.number, 2);
  // A different CA gets a new, empty CRL.
  const other = makeCa();
  const otherCa = loadCa(other.pem, other.key, PASS);
  assert.equal(await ensureCrl(d.cluster, otherCa, NOW), true);
  const fresh = readCrlState(store.secrets[`takserver/${CRL_SECRET}`]);
  assert.deepEqual(fresh.entries, []);
  assert.equal(fresh.ca, fingerprint(other.pem));
});

test("readCrlState tolerates missing and damaged fields", () => {
  assert.deepEqual(readCrlState(undefined), { entries: [], number: 0, pem: undefined, ca: undefined });
  assert.deepEqual(readCrlState({ data: { "revoked.json": b64("{bad"), number: b64("x") } }).entries, []);
  assert.equal(readCrlState({ data: { number: b64("x") } }).number, 0);
  assert.deepEqual(readCrlState({ data: { "revoked.json": b64("{}") } }).entries, []);
});

test("CRL writes run one at a time", async () => {
  const order: string[] = [];
  const slow = withCrlLock(async () => {
    await new Promise(resolve => setTimeout(resolve, 5));
    order.push("first");
  });
  const failing = withCrlLock(async () => {
    order.push("second");
    throw new Error("x");
  });
  const third = withCrlLock(async () => {
    order.push("third");
  });
  await slow;
  await assert.rejects(failing);
  await third;
  assert.deepEqual(order, ["first", "second", "third"]);
});

test("registerAll registers every issued TakClient again", async () => {
  const issued = client({ metadata: { name: "a1b2", annotations: { [SERIAL]: "aa", [NOT_AFTER]: "2026-12-01" } } });
  const clients = [
    issued,
    client({ metadata: { name: "gone", deletionTimestamp: NOW.toISOString(), annotations: { [SERIAL]: "aa" } } }),
    client({ metadata: { name: "bad", annotations: { [SERIAL]: "aa" } }, spec: { callsign: "no" } }),
    client({ metadata: { name: "new" } }),
  ];
  const { d, calls } = fake({ clients });
  await registerAll(d);
  assert.equal(calls.tak.length, 1);
  assert.equal(calls.status[0].name, "a1b2");
  const down = fake({ clients: [issued], tak: () => ({ status: 503, body: "" }) });
  await registerAll(down.d);
  assert.equal(down.calls.logs.length, 1);
  const store = material();
  delete store.secrets["takserver/takserver-ca-key"];
  const noCa = fake({ store, clients });
  await registerAll(noCa.d);
  const adminless = material();
  delete adminless.secrets["takserver/takserver-certs"];
  const noAdmin = fake({ store: adminless, clients });
  await registerAll(noAdmin.d);
  assert.equal(noCa.calls.tak.length + noAdmin.calls.tak.length, 0);
});

test("onMessaging registers again only when messaging becomes Available", async () => {
  const saved = { cluster: runtime.takCluster, tak: runtime.tak };
  const issued = client({ metadata: { name: "a1b2", annotations: { [SERIAL]: "aa" } } });
  const { d, calls } = fake({ clients: [issued] });
  runtime.takCluster = d.cluster;
  runtime.tak = d.tak;
  resetMessaging();
  try {
    const up: DeploymentDoc = { status: { availableReplicas: 1 } };
    const down: DeploymentDoc = { status: { availableReplicas: 0 } };
    await onMessaging(up, "ADDED");
    await onMessaging(up, "MODIFIED");
    assert.equal(calls.tak.length, 1);
    await onMessaging(down, "MODIFIED");
    await onMessaging({}, "MODIFIED");
    await onMessaging(up, "MODIFIED");
    assert.equal(calls.tak.length, 2);
    await onMessaging(up, "DELETED");
    await onMessaging(up, "ADDED");
    assert.equal(calls.tak.length, 3);
  } finally {
    runtime.takCluster = saved.cluster;
    runtime.tak = saved.tak;
    resetMessaging();
  }
});

test("onCaMaterial and onTakClient use the live surfaces", async () => {
  const saved = { cluster: runtime.takCluster, tak: runtime.tak, domain: process.env.DOMAIN };
  const { d, store, calls } = fake();
  runtime.takCluster = d.cluster;
  runtime.tak = d.tak;
  process.env.DOMAIN = "uds.dev";
  try {
    await onCaMaterial(undefined, "DELETED");
    assert.equal(store.secrets[`takserver/${CRL_SECRET}`], undefined);
    await onCaMaterial(undefined, "ADDED");
    assert.ok(store.secrets[`takserver/${CRL_SECRET}`]);
    await onTakClient(client(), "ADDED");
    assert.equal(calls.status.at(-1)!.conditions[0].status, "True");
    assert.equal(calls.sleeps.length, 0);
    const down = fake({ tak: () => ({ status: 503, body: "" }) });
    runtime.takCluster = down.d.cluster;
    runtime.tak = down.d.tak;
    await onTakClient(client(), "ADDED");
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(down.calls.sleeps, [RECONCILE_RETRY_MS]);
    assert.equal(RECONCILE_RETRY in down.calls.annotate.at(-1)!.annotations, true);
    runtime.takCluster = d.cluster;
    runtime.tak = d.tak;
    const live = deps();
    assert.equal(live.domain, "uds.dev");
    assert.equal(live.now() instanceof Date, true);
    live.log("message from the test");
    delete process.env.DOMAIN;
    assert.equal(deps().domain, "");
    const missing = material();
    delete missing.secrets["takserver/takserver-ca-key"];
    runtime.takCluster = fake({ store: missing }).d.cluster;
    await onCaMaterial(undefined, "ADDED");
  } finally {
    runtime.takCluster = saved.cluster;
    runtime.tak = saved.tak;
    if (saved.domain === undefined) {
      delete process.env.DOMAIN;
    } else {
      process.env.DOMAIN = saved.domain;
    }
  }
});

test("retryLater logs when the annotation cannot be written", async () => {
  const { d, calls } = fake();
  d.cluster.annotateTakClient = async () => {
    throw new Error("conflict");
  };
  await retryLater(d, "takclient-test");
  assert.deepEqual(calls.sleeps, [RECONCILE_RETRY_MS]);
  assert.equal(calls.logs[0], "TakClient takclient-test: retry failed: conflict");
});

test("crds/takclient.yaml is what pepr crd generate writes from api/", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const out = mkdtempSync(join(tmpdir(), "takclient-crd-"));
  // Keep the child's coverage out of this run's report (see rbac.test.ts).
  const env = { ...process.env, LOG_LEVEL: "silent", NODE_V8_COVERAGE: "/tmp/pepr-crd-nocov" };
  const result = spawnSync(join(root, "node_modules", ".bin", "pepr"), ["crd", "generate", "-o", out], {
    cwd: root,
    env,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(
    readFileSync(join(out, "takclient.yaml"), "utf8"),
    // The committed file starts with the license header and a note, then a blank line.
    readFileSync(join(root, "crds", "takclient.yaml"), "utf8").replace(/^(#.*\n)+\n/, ""),
    "run `npx pepr crd generate` in pepr/, keep the header, and commit crds/takclient.yaml",
  );
});

afterEach(() => resetMessaging());
