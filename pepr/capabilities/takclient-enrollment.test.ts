// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { generateKeyPairSync, X509Certificate } from "node:crypto";
import { test } from "node:test";
import forge from "node-forge";
import { clientCsr, enroll, revokeEnrolled } from "./takclient-enrollment.ts";
import type { Ca } from "./takclient-pki.ts";
import type { TakApi, TakTls } from "./takclient.ts";

const NOW = new Date("2026-11-07T12:00:00Z");
const keypair = generateKeyPairSync("rsa", { modulusLength: 2048 });
const key = forge.pki.privateKeyFromPem(keypair.privateKey.export({ type: "pkcs1", format: "pem" }).toString());
const cert = forge.pki.createCertificate();
cert.publicKey = forge.pki.publicKeyFromPem(keypair.publicKey.export({ type: "spki", format: "pem" }).toString());
cert.serialNumber = "01";
cert.setSubject([{ shortName: "CN", value: "test-ca" }]);
cert.setIssuer(cert.subject.attributes);
cert.setExtensions([{ name: "basicConstraints", cA: true }, { name: "keyUsage", keyCertSign: true }]);
cert.sign(key, forge.md.sha256.create());
const ca: Ca = { cert, key, pem: forge.pki.certificateToPem(cert) };
const tls: TakTls = { ca: ca.pem, cert: "admin", key: "key", passphrase: "pass" };

function signed(csrPem: string, change: (leaf: forge.pki.Certificate) => void = () => {}) {
  const csr = forge.pki.certificationRequestFromPem(csrPem);
  assert.equal(csr.verify(), true);
  const leaf = forge.pki.createCertificate();
  leaf.publicKey = csr.publicKey!;
  leaf.serialNumber = "02";
  leaf.setSubject(csr.subject.attributes);
  leaf.setIssuer(ca.cert.subject.attributes);
  leaf.validity.notBefore = new Date(NOW.getTime() - 60000);
  leaf.validity.notAfter = new Date(NOW.getTime() + 86400000);
  leaf.setExtensions([{ name: "extKeyUsage", clientAuth: true }]);
  change(leaf);
  leaf.sign(key, forge.md.sha256.create());
  return forge.pki.certificateToPem(leaf);
}

test("TAK enroll uses a signed CSR, Basic auth and the returned certificate lifetime", async () => {
  const request: TakApi["request"] = async (actualTls, method, path, body, options) => {
    assert.equal(actualTls, tls);
    assert.equal(method, "POST");
    assert.equal(path, "/Marti/api/tls/signClient/v2?clientUid=client.one&version=1");
    assert.deepEqual(options, { port: 8446, auth: "client.one:secret", contentType: "text/plain" });
    return { status: 200, body: JSON.stringify({ signedCert: signed(body as string) }) };
  };
  const issued = await enroll({ request }, tls, ca, "client.one", "secret", NOW);
  assert.equal(issued.serial, "02");
  assert.equal(issued.notBefore.toISOString(), "2026-11-07T11:59:00.000Z");
  assert.equal(issued.notAfter.toISOString(), "2026-11-08T12:00:00.000Z");
  assert.equal(new X509Certificate(issued.certPem).subject, "CN=client.one\nO=TAK\nOU=UDS");
  assert.equal(issued.keyPem.includes("PRIVATE KEY"), true);
  const raw: TakApi = { request: async (_tls, _method, _path, body) => ({ status: 200,
    body: JSON.stringify({ signedCert: signed(body as string).replace(/-----[^-]+-----|\s/g, "") }) }) };
  assert.equal((await enroll(raw, tls, ca, "client.one", "secret", NOW)).serial, "02");
});

test("TAK enrollment rejects failures, OAuth tokens and malformed response bodies without echoing them", async () => {
  for (const response of [
    { status: 503, body: "private-body" },
    { status: 200, body: "private-body" },
    { status: 200, body: "null" },
    { status: 200, body: '{"token":"secret"}' },
    { status: 200, body: '{"data":{"token":"secret"}}' },
    { status: 200, body: "{}" },
  ]) {
    await assert.rejects(enroll({ request: async () => response }, tls, ca, "client.one", "secret", NOW),
      (error: Error) => !error.message.includes("private-body") && !error.message.includes("secret"));
  }
});

test("TAK enrollment validates key, issuer, identity, lifetime and client usage", async () => {
  const changes: ((leaf: forge.pki.Certificate) => void)[] = [
    leaf => { leaf.publicKey = ca.cert.publicKey; },
    leaf => { leaf.setIssuer([{ shortName: "CN", value: "wrong-ca" }]); },
    leaf => { leaf.setSubject([{ shortName: "CN", value: "different" }]); },
    leaf => { leaf.setSubject([]); },
    leaf => { leaf.setExtensions([{ name: "basicConstraints", cA: true }]); },
    leaf => { leaf.setExtensions([]); },
    leaf => { leaf.setExtensions([{ name: "extKeyUsage", serverAuth: true }]); },
    leaf => { leaf.validity.notAfter = new Date(NOW.getTime() - 1); },
    leaf => { leaf.validity.notBefore = new Date(NOW.getTime() + 60000); },
  ];
  for (const change of changes) {
    const tak: TakApi = { request: async (_tls, _method, _path, body) => ({ status: 200,
      body: JSON.stringify({ signedCert: signed(body as string, change) }) }) };
    await assert.rejects(enroll(tak, tls, ca, "client.one", "secret", NOW));
  }
  const wrongCa = { ...ca, pem: signed(clientCsr("wrong-ca").csrPem) };
  const tak: TakApi = { request: async (_tls, _method, _path, body) => ({ status: 200,
    body: JSON.stringify({ signedCert: signed(body as string) }) }) };
  await assert.rejects(enroll(tak, tls, wrongCa, "client.one", "secret", NOW));
});

test("certadmin revocation validates the lookup and never treats errors as success", async () => {
  const calls: string[] = [];
  for (const body of ['{"id":12}', '{"data":{"id":"12"}}']) {
    await revokeEnrolled({ request: async (_tls, method, path) => {
      calls.push(`${method} ${path}`);
      return { status: 200, body: method === "GET" ? body : "" };
    } }, tls, "AA:BB");
  }
  assert.deepEqual(calls.slice(0, 2), ["GET /Marti/api/certadmin/cert/AA%3ABB", "DELETE /Marti/api/certadmin/cert/revoke/12"]);
  for (const response of [{ status: 404, body: "" }, { status: 200, body: "{}" },
    { status: 200, body: '{"id":0}' }, { status: 200, body: '{"id":"../1"}' }]) {
    await assert.rejects(revokeEnrolled({ request: async () => response }, tls, "AA"));
  }
  await assert.rejects(revokeEnrolled({ request: async (_tls, method) =>
    method === "GET" ? { status: 200, body: '{"id":1}' } : { status: 503, body: "" } }, tls, "AA"), /HTTP 503/);
  const already: string[] = [];
  await revokeEnrolled({ request: async (_tls, method, path) => {
    already.push(`${method} ${path}`);
    return { status: 200, body: '{"data":{"revocationDate":"2026-11-07T00:00:00.000Z"}}' };
  } }, tls, "AA:BB");
  assert.deepEqual(already, ["GET /Marti/api/certadmin/cert/AA%3ABB"]);
  const emptyDate: string[] = [];
  await revokeEnrolled({ request: async (_tls, method, path) => {
    emptyDate.push(`${method} ${path}`);
    return { status: 200, body: method === "GET" ? '{"data":{"id":4,"revocationDate":""}}' : "" };
  } }, tls, "CC");
  assert.deepEqual(emptyDate, ["GET /Marti/api/certadmin/cert/CC", "DELETE /Marti/api/certadmin/cert/revoke/4"]);
});
