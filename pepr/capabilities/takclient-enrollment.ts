// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// ADR 24: certificates signed by TAK have a certificate-table row, which
// certadmin can revoke and disconnect without rebuilding TLS contexts.
import { generateKeyPairSync, X509Certificate, createPrivateKey } from "node:crypto";
import forge from "node-forge";
import type { Ca, Issued } from "./takclient-pki.ts";
import { fingerprint } from "./takclient-pki.ts";
import type { TakApi, TakTls } from "./takclient.ts";

function responseJson(body: string): Record<string, any> {
  try {
    const value = JSON.parse(body);
    if (!value || typeof value !== "object") throw new Error();
    return value;
  } catch {
    throw new Error("TAK returned invalid JSON");
  }
}

export function clientCsr(callsign: string): { keyPem: string; csrPem: string } {
  const pair = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const keyPem = pair.privateKey.export({ type: "pkcs1", format: "pem" }).toString();
  const csr = forge.pki.createCertificationRequest();
  csr.publicKey = forge.pki.publicKeyFromPem(pair.publicKey.export({ type: "spki", format: "pem" }).toString());
  csr.setSubject([{ shortName: "CN", value: callsign }, { shortName: "O", value: "TAK" }, { shortName: "OU", value: "UDS" }]);
  csr.sign(forge.pki.privateKeyFromPem(keyPem), forge.md.sha256.create());
  return { keyPem, csrPem: forge.pki.certificationRequestToPem(csr) };
}

export async function enroll(
  tak: TakApi, tls: TakTls, ca: Ca, callsign: string, password: string, now: Date,
): Promise<Issued> {
  const { keyPem, csrPem } = clientCsr(callsign);
  const response = await tak.request(tls, "POST", `/Marti/api/tls/signClient/v2?clientUid=${encodeURIComponent(callsign)}&version=1`, csrPem,
    { port: 8446, auth: `${callsign}:${password}`, contentType: "text/plain" });
  if (response.status !== 200) throw new Error(`TAK signClient returned HTTP ${response.status}`);
  const body = responseJson(response.body);
  if (body.token || body.data?.token) throw new Error("TAK returned an OAuth token for Basic enrollment");
  if (typeof body.signedCert !== "string") throw new Error("TAK enrollment has no signedCert");
  const certPem = body.signedCert.includes("-----BEGIN CERTIFICATE-----") ? body.signedCert
    : `-----BEGIN CERTIFICATE-----\n${body.signedCert.replace(/\s/g, "")}\n-----END CERTIFICATE-----\n`;
  const cert = new X509Certificate(certPem);
  const issuer = new X509Certificate(ca.pem);
  if (!cert.checkIssued(issuer) || !cert.verify(issuer.publicKey) || !cert.checkPrivateKey(createPrivateKey(keyPem))) {
    throw new Error("TAK enrollment certificate does not match the requested key and CA");
  }
  const leaf = forge.pki.certificateFromPem(certPem);
  if (leaf.subject.getField("CN")?.value !== callsign || cert.ca ||
      !cert.keyUsage?.includes("1.3.6.1.5.5.7.3.2") || leaf.validity.notAfter <= now || leaf.validity.notBefore > now) {
    throw new Error("TAK enrollment certificate has invalid subject, usage or validity");
  }
  return { certPem, keyPem, serial: leaf.serialNumber.toLowerCase(), fingerprint: fingerprint(certPem), notAfter: leaf.validity.notAfter };
}

export async function revokeEnrolled(tak: TakApi, tls: TakTls, hash: string): Promise<void> {
  const lookup = await tak.request(tls, "GET", `/Marti/api/certadmin/cert/${encodeURIComponent(hash)}`);
  if (lookup.status !== 200) throw new Error(`TAK certificate lookup returned HTTP ${lookup.status}`);
  const body = responseJson(lookup.body);
  const id = (body.data ?? body).id;
  if (!/^[1-9][0-9]*$/.test(String(id))) throw new Error("TAK certificate lookup has no valid id");
  const result = await tak.request(tls, "DELETE", `/Marti/api/certadmin/cert/revoke/${id}`);
  if (result.status !== 200) throw new Error(`TAK certificate revoke returned HTTP ${result.status}`);
}
