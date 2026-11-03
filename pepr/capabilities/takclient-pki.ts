// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Certificates, PKCS#12 files, the CRL, and the data package for TakClient.
// See ADR 22. Nothing here writes to disk. The CA key is decrypted in memory
// with Node's crypto, because the TAK CA key is an OpenSSL 3 encrypted PKCS#8
// file, and is then handed to node-forge for signing.

import { createHash, createPrivateKey, generateKeyPairSync, randomBytes, randomUUID } from "node:crypto";
import { crc32 } from "node:zlib";
import forge from "node-forge";

const { asn1, pki, pkcs12, util } = forge;

export interface Ca {
  cert: forge.pki.Certificate;
  key: forge.pki.rsa.PrivateKey;
  pem: string;
}

export interface Issued {
  certPem: string;
  keyPem: string;
  serial: string;
  fingerprint: string;
  notAfter: Date;
}

export interface Revoked {
  serial: string;
  date: string;
}

const DAY = 24 * 60 * 60 * 1000;

export function loadCa(caPem: string, caKeyPem: string, passphrase: string): Ca {
  const key = createPrivateKey({ key: caKeyPem, passphrase });
  const clear = key.export({ type: "pkcs1", format: "pem" }).toString();
  return { cert: pki.certificateFromPem(caPem), key: pki.privateKeyFromPem(clear) as forge.pki.rsa.PrivateKey, pem: caPem };
}

export function newSerial(): string {
  // A positive 128-bit integer: the top bit is cleared so DER needs no sign byte.
  const bytes = randomBytes(16);
  bytes[0] &= 0x7f;
  bytes[0] |= 0x10;
  return bytes.toString("hex");
}

export function fingerprint(certPem: string): string {
  const der = Buffer.from(asn1.toDer(pki.certificateToAsn1(pki.certificateFromPem(certPem))).getBytes(), "binary");
  return createHash("sha256")
    .update(der)
    .digest("hex")
    .toUpperCase()
    .match(/../g)!
    .join(":");
}

export function issue(ca: Ca, callsign: string, days: number, now: Date, serial = newSerial()): Issued {
  const pair = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const keyPem = pair.privateKey.export({ type: "pkcs1", format: "pem" }).toString();
  const publicPem = pair.publicKey.export({ type: "spki", format: "pem" }).toString();
  const cert = pki.createCertificate();
  cert.publicKey = pki.publicKeyFromPem(publicPem);
  cert.serialNumber = serial;
  // Back-dated a minute for clock skew between the watcher and TAK.
  cert.validity.notBefore = new Date(now.getTime() - 60 * 1000);
  cert.validity.notAfter = new Date(now.getTime() + days * DAY);
  cert.setSubject([
    { shortName: "CN", value: callsign },
    { shortName: "O", value: "TAK" },
    { shortName: "OU", value: "UDS" },
  ]);
  cert.setIssuer(ca.cert.subject.attributes);
  cert.setExtensions([
    { name: "basicConstraints", cA: false },
    { name: "keyUsage", critical: true, digitalSignature: true, keyEncipherment: true },
    { name: "extKeyUsage", clientAuth: true },
    { name: "subjectKeyIdentifier" },
    { name: "authorityKeyIdentifier", keyIdentifier: ca.cert.generateSubjectKeyIdentifier().getBytes() },
  ]);
  cert.sign(ca.key, forge.md.sha256.create());
  const certPem = pki.certificateToPem(cert);
  return { certPem, keyPem, serial, fingerprint: fingerprint(certPem), notAfter: cert.validity.notAfter };
}

// ATAK on Android 9 reads PKCS#12 with SHA-1 and 3DES only, as atak/ci/e2e.sh
// notes for OpenSSL. node-forge writes that by default.
export function clientP12(issued: Issued, ca: Ca, name: string, password: string): Buffer {
  const p12 = pkcs12.toPkcs12Asn1(
    pki.privateKeyFromPem(issued.keyPem),
    [pki.certificateFromPem(issued.certPem), ca.cert],
    password,
    { algorithm: "3des", friendlyName: name },
  );
  return Buffer.from(asn1.toDer(p12).getBytes(), "binary");
}

export function trustP12(ca: Ca, password: string): Buffer {
  const p12 = pkcs12.toPkcs12Asn1(null, [ca.cert], password, { algorithm: "3des", friendlyName: "tak-ca" });
  return Buffer.from(asn1.toDer(p12).getBytes(), "binary");
}

function utcTime(date: Date): forge.asn1.Asn1 {
  return asn1.create(asn1.Class.UNIVERSAL, asn1.Type.UTCTIME, false, asn1.dateToUtcTime(date));
}

function integer(hex: string): forge.asn1.Asn1 {
  return asn1.create(asn1.Class.UNIVERSAL, asn1.Type.INTEGER, false, util.hexToBytes(hex.length % 2 ? `0${hex}` : hex));
}

function sha256WithRsa(): forge.asn1.Asn1 {
  return asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OID, false, asn1.oidToDer(pki.oids.sha256WithRSAEncryption).getBytes()),
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.NULL, false, ""),
  ]);
}

// A version 2 CRL (RFC 5280 5.1) with a CRL number. The issuer is copied
// from the CA certificate's own subject, so Java matches it byte for byte.
export function buildCrl(ca: Ca, revoked: Revoked[], number: number, now: Date, nextUpdateDays: number): string {
  const caAsn1 = pki.certificateToAsn1(ca.cert);
  const tbsCert = (caAsn1.value as forge.asn1.Asn1[])[0].value as forge.asn1.Asn1[];
  // tbsCertificate: [0] version, serial, signature, issuer, validity, subject, ...
  const subject = tbsCert[5];
  const entries = revoked.map(entry =>
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [integer(entry.serial), utcTime(new Date(entry.date))]),
  );
  const crlNumber = asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OID, false, asn1.oidToDer("2.5.29.20").getBytes()),
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OCTETSTRING, false, asn1.toDer(integer(number.toString(16))).getBytes()),
  ]);
  const tbs = [
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.INTEGER, false, util.hexToBytes("01")),
    sha256WithRsa(),
    subject,
    utcTime(now),
    utcTime(new Date(now.getTime() + nextUpdateDays * DAY)),
  ];
  if (entries.length > 0) {
    tbs.push(asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, entries));
  }
  tbs.push(
    asn1.create(asn1.Class.CONTEXT_SPECIFIC, 0, true, [asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [crlNumber])]),
  );
  const tbsAsn1 = asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, tbs);
  const md = forge.md.sha256.create();
  md.update(asn1.toDer(tbsAsn1).getBytes());
  const signature = ca.key.sign(md);
  const crl = asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [
    tbsAsn1,
    sha256WithRsa(),
    asn1.create(asn1.Class.UNIVERSAL, asn1.Type.BITSTRING, false, String.fromCharCode(0) + signature),
  ]);
  const body = util.encode64(asn1.toDer(crl).getBytes(), 64);
  return `-----BEGIN X509 CRL-----\r\n${body}\r\n-----END X509 CRL-----\r\n`;
}

export interface DataPackage {
  callsign: string;
  host: string;
  issued: Issued;
  ca: Ca;
  password: string;
  uid?: string;
}

function xml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// The same connection data package atak/ci/e2e.sh builds: one 8089 ssl
// stream, the truststore, and the client certificate.
export function serverPref(callsign: string, host: string, password: string): string {
  const name = xml(callsign);
  const pass = xml(password);
  return `<?xml version='1.0' standalone='yes'?>
<preferences>
  <preference version="1" name="cot_streams">
    <entry key="count" class="class java.lang.Integer">1</entry>
    <entry key="description0" class="class java.lang.String">TAK Server</entry>
    <entry key="enabled0" class="class java.lang.Boolean">true</entry>
    <entry key="connectString0" class="class java.lang.String">${xml(host)}:8089:ssl</entry>
    <entry key="caLocation0" class="class java.lang.String">cert/truststore.p12</entry>
    <entry key="caPassword0" class="class java.lang.String">${pass}</entry>
    <entry key="certificateLocation0" class="class java.lang.String">cert/${name}.p12</entry>
    <entry key="clientPassword0" class="class java.lang.String">${pass}</entry>
  </preference>
  <preference version="1" name="com.atakmap.app_preferences">
    <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
  </preference>
</preferences>
`;
}

export function manifest(callsign: string, uid: string): string {
  const name = xml(callsign);
  return `<MissionPackageManifest version="2">
  <Configuration>
    <Parameter name="uid" value="${xml(uid)}"/>
    <Parameter name="name" value="${name}"/>
    <Parameter name="onReceiveDelete" value="true"/>
  </Configuration>
  <Contents>
    <Content ignore="false" zipEntry="certs/server.pref"/>
    <Content ignore="false" zipEntry="certs/truststore.p12"/>
    <Content ignore="false" zipEntry="certs/${name}.p12"/>
  </Contents>
</MissionPackageManifest>
`;
}

export function dataPackage(pkg: DataPackage): Buffer {
  return zip([
    { name: "MANIFEST/manifest.xml", data: Buffer.from(manifest(pkg.callsign, pkg.uid ?? randomUUID())) },
    { name: "certs/server.pref", data: Buffer.from(serverPref(pkg.callsign, pkg.host, pkg.password)) },
    { name: "certs/truststore.p12", data: trustP12(pkg.ca, pkg.password) },
    { name: `certs/${pkg.callsign}.p12`, data: clientP12(pkg.issued, pkg.ca, pkg.callsign, pkg.password) },
  ]);
}

// A stored (uncompressed) ZIP, enough for a data package. Fixed timestamps
// (1980-01-01) keep the bytes the same for the same input.
export function zip(files: { name: string; data: Buffer }[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.name, "utf8");
    const crc = crc32(file.data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(0, 10);
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(file.data.length, 18);
    local.writeUInt32LE(file.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0x21, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(file.data.length, 20);
    central.writeUInt32LE(file.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, name, file.data);
    centrals.push(central, name);
    offset += local.length + name.length + file.data.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

// The nextUpdate of a PEM CRL, or undefined when it cannot be read.
export function crlNextUpdate(pem: string): Date | undefined {
  try {
    const der = util.decode64(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
    const crl = asn1.fromDer(der);
    const tbs = (crl.value as forge.asn1.Asn1[])[0].value as forge.asn1.Asn1[];
    // version, signature, issuer, thisUpdate, nextUpdate
    return asn1.utcTimeToDate(tbs[4].value as string);
  } catch {
    return undefined;
  }
}
