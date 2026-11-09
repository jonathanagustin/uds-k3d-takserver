// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import test from 'node:test';
import { boundedDiagnostic, classifyTlsError, negativeControl } from './sso-trust-class.mjs';

test('a certificate-authority verification error is the only expected rejection', () => {
  for (const code of [
    'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
    'UNABLE_TO_GET_ISSUER_CERT_LOCALLY',
    'CERT_SIGNATURE_FAILURE',
    'DEPTH_ZERO_SELF_SIGNED_CERT',
    'SELF_SIGNED_CERT_IN_CHAIN',
  ]) {
    const error = { code, message: `unable to verify the first certificate (${code})` };
    assert.equal(classifyTlsError(error), 'ca-rejected');
    const decision = negativeControl({ kind: 'ca-rejected', detail: boundedDiagnostic(error) }, 'trial-CA check');
    assert.equal(decision.pass, true);
    assert.match(decision.diagnostic, new RegExp(code));
    assert.match(decision.diagnostic, /unable to verify the first certificate/);
  }
});

test('a message-only issuer failure is still a CA rejection', () => {
  const error = { message: 'unable to get local issuer certificate' };
  assert.equal(classifyTlsError(error), 'ca-rejected');
  assert.equal(negativeControl({ kind: classifyTlsError(error), detail: boundedDiagnostic(error) }, 'public-root check').pass, true);
});

test('DNS failure does not pass a negative control and keeps the diagnostic', () => {
  const error = { code: 'ENOTFOUND', message: 'getaddrinfo ENOTFOUND sso.uds.dev' };
  assert.equal(classifyTlsError(error), 'transport');
  const decision = negativeControl({ kind: 'transport', detail: boundedDiagnostic(error) }, 'public-root check');
  assert.equal(decision.pass, false);
  assert.match(decision.reason, /inconclusive \(transport\)/);
  assert.match(decision.reason, /ENOTFOUND/);
  assert.match(decision.reason, /getaddrinfo ENOTFOUND sso\.uds\.dev/);
});

test('connection reset and timeout do not pass a negative control', () => {
  for (const error of [
    { code: 'ECONNRESET', message: 'read ECONNRESET' },
    { code: 'ETIMEDOUT', message: 'connect ETIMEDOUT 10.0.0.1:443' },
    { code: 'ERR_SOCKET_CONNECTION_TIMEOUT', message: 'TLS connection timed out' },
    { message: 'socket timeout while waiting for the handshake' },
  ]) {
    const kind = classifyTlsError(error);
    assert.equal(kind, 'transport', boundedDiagnostic(error));
    const decision = negativeControl({ kind, detail: boundedDiagnostic(error) }, 'trial-CA check');
    assert.equal(decision.pass, false);
    assert.match(decision.reason, /inconclusive \(transport\)/);
    assert.match(decision.reason, new RegExp(error.code || 'timeout'));
  }
});

test('an accepted connection is unexpected success, not a rejection', () => {
  const decision = negativeControl({ kind: 'success', detail: '' }, 'trial-CA check');
  assert.equal(decision.pass, false);
  assert.equal(decision.reason, 'trial-CA check unexpected success');
});

test('an unclassified error stays inconclusive and keeps a bounded diagnostic', () => {
  const error = { code: 'ERR_TLS_CERT_ALTNAME_INVALID', message: `hostname mismatch ${'x'.repeat(500)}` };
  assert.equal(classifyTlsError(error), 'other');
  const decision = negativeControl({ kind: 'other', detail: boundedDiagnostic(error) }, 'public-root check');
  assert.equal(decision.pass, false);
  assert.match(decision.reason, /inconclusive \(other\)/);
  assert.ok(decision.reason.length <= 300);
  assert.match(decision.reason, /ERR_TLS_CERT_ALTNAME_INVALID/);
  assert.match(decision.reason, /hostname mismatch/);
});
