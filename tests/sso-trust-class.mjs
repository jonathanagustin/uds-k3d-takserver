// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Classification for the SSO negative controls. Only a certificate-authority
// verification failure counts as the expected rejection. Transport failures
// stay inconclusive so they cannot pass the control.

const CA_CODES = new Set([
  'UNABLE_TO_GET_ISSUER_CERT',
  'UNABLE_TO_GET_ISSUER_CERT_LOCALLY',
  'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
  'CERT_SIGNATURE_FAILURE',
  'DEPTH_ZERO_SELF_SIGNED_CERT',
  'SELF_SIGNED_CERT_IN_CHAIN',
  'CERT_UNTRUSTED',
]);

const TRANSPORT_CODES = new Set([
  'ENOTFOUND',
  'EAI_AGAIN',
  'ECONNRESET',
  'ECONNREFUSED',
  'ECONNABORTED',
  'EPIPE',
  'ETIMEDOUT',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ERR_SOCKET_CONNECTION_TIMEOUT',
  'ERR_SOCKET_TIMEOUT',
  'UND_ERR_CONNECT_TIMEOUT',
  'ERR_TLS_HANDSHAKE_TIMEOUT',
]);

export function boundedDiagnostic(error) {
  const code = error && error.code ? String(error.code) : '';
  const message = String((error && error.message) || error || 'no error text')
    .replace(/\s+/g, ' ')
    .slice(0, 240);
  const text = code ? `${code}: ${message}` : message;
  return text.slice(0, 300);
}

export function classifyTlsError(error) {
  const code = error && error.code ? String(error.code) : '';
  const message = String((error && error.message) || '').toLowerCase();
  if (CA_CODES.has(code)) return 'ca-rejected';
  if (
    message.includes('unable to verify the first certificate')
    || message.includes('unable to get local issuer certificate')
    || message.includes('unable to get issuer certificate')
    || message.includes('certificate signature failure')
    || message.includes('self-signed certificate')
    || message.includes('self signed certificate in certificate chain')
  ) return 'ca-rejected';
  if (TRANSPORT_CODES.has(code)) return 'transport';
  if (
    message.includes('timeout')
    || message.includes('econnreset')
    || message.includes('enotfound')
    || message.includes('getaddrinfo')
    || message.includes('econnrefused')
  ) return 'transport';
  return 'other';
}

// A negative control passes only when the handshake failed certificate
// verification. Success, DNS, reset, timeout, and any other error do not.
export function negativeControl(outcome, label) {
  if (!outcome || outcome.kind === 'success') {
    return { pass: false, reason: `${label} unexpected success` };
  }
  if (outcome.kind === 'ca-rejected') {
    return { pass: true, diagnostic: outcome.detail || '' };
  }
  const detail = outcome.detail || 'no error text';
  return { pass: false, reason: `${label} inconclusive (${outcome.kind}): ${detail}`.slice(0, 300) };
}

// Keep cryptographic issuer links intact when a gateway sends intermediates.
// `parse` is supplied by the caller (Node's X509Certificate in production).
export function certificateChain(peer, parse, trust = []) {
  const chain = [];
  const seen = new Set();
  let current = peer;
  while (current && current.raw) {
    const cert = parse(current.raw);
    const fingerprint = cert.fingerprint256;
    if (seen.has(fingerprint)) break;
    seen.add(fingerprint);
    chain.push(cert);
    let parent = current.issuerCertificate;
    if (!parent || !parent.raw || parse(parent.raw).fingerprint256 === fingerprint) {
      const issuer = trust.find(candidate => candidate.fingerprint256 !== fingerprint
        && cert.checkIssued(candidate) && cert.verify(candidate.publicKey));
      parent = issuer ? { raw: issuer.raw } : undefined;
    }
    if (parent && parent.raw) {
      const issuer = parse(parent.raw);
      if (!cert.checkIssued(issuer) || !cert.verify(issuer.publicKey)) {
        throw new Error('SSO server sent an invalid certificate issuer chain');
      }
    }
    current = parent;
  }
  return chain;
}

export function bundledAnchor(peer, certificates, parse) {
  const trusted = new Map(certificates.map(cert => [cert.fingerprint256, cert]));
  const chain = certificateChain(peer, parse, certificates);
  return chain.map(cert => trusted.get(cert.fingerprint256)).filter(Boolean).at(-1);
}
