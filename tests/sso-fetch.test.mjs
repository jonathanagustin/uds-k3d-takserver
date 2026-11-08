// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import fs from 'node:fs';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
import tls from 'node:tls';
import {
    boundedCause,
    issuerRequest,
    issuerTrust,
    LIVE_BUNDLE_FILE,
    readOptional,
    sanitizeDiagnostic,
    TAK_CA_FILE,
} from '../.github/container-and-chart/cloudtak/sso-fetch.mjs';

test('a fetch failure keeps the cause code and drops secrets', () => {
    const cause = new Error(
        'unable to verify the first certificate '
        + 'https://sso.example/realms/uds/.well-known/openid-configuration?code=SECRETTOKEN '
        + 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signaturevalue '
        + '-----BEGIN CERTIFICATE-----\nSECRETPEM\n-----END CERTIFICATE----- TAILSECRET',
    );
    cause.code = 'UNABLE_TO_VERIFY_LEAF_SIGNATURE';
    const error = new TypeError('fetch failed');
    error.cause = cause;
    const text = boundedCause(error);
    assert.match(text, /TypeError: UNABLE_TO_VERIFY_LEAF_SIGNATURE/);
    assert.equal(text.includes('SECRETPEM'), false);
    assert.equal(text.includes('TAILSECRET'), false);
    assert.equal(text.includes('SECRETTOKEN'), false);
    assert.equal(text.includes('eyJ'), false);
    assert.equal(text.includes('BEGIN'), false);
    assert.match(text, /https:\/\/sso\.example\/realms\/uds\/\.well-known\/openid-configuration/);
});

test('an aggregate transport failure keeps its code', () => {
    const inner = new Error('getaddrinfo');
    inner.code = 'ENOTFOUND';
    const error = new TypeError('fetch failed');
    error.cause = new AggregateError([inner], 'fetch failed');
    assert.match(boundedCause(error), /ENOTFOUND/);
});

test('a plain failure reason stays bounded', () => {
    assert.equal(boundedCause('missing or expired state cookie'), 'missing or expired state cookie');
    const text = boundedCause(`preface ${'x'.repeat(5000)}`);
    assert.equal(text.length <= 240, true);
    assert.equal(text.startsWith('preface'), true);
});

test('text before the first pem marker remains and nothing after it does', () => {
    const text = sanitizeDiagnostic(
        'preface -----BEGIN CERTIFICATE-----\nONESECRET\n-----END CERTIFICATE----- kept '
        + '-----BEGIN PRIVATE KEY-----\nTWOSECRET\n-----END PRIVATE KEY-----',
    );
    assert.equal(text, 'preface [redacted]');
    assert.equal(text.includes('ONESECRET'), false);
    assert.equal(text.includes('TWOSECRET'), false);
    assert.equal(text.includes('kept'), false);
});

test('an unclosed pem block redacts every later fragment', () => {
    const text = sanitizeDiagnostic(
        'preface -----BEGIN PRIVATE KEY-----\nSHORTKEYFRAGMENT\n'
        + '-----BEGIN RSA PRIVATE KEY-----\nSECONDFRAGMENT',
    );
    assert.equal(text.includes('SHORTKEYFRAGMENT'), false);
    assert.equal(text.includes('SECONDFRAGMENT'), false);
    assert.equal(text.includes('BEGIN'), false);
    assert.equal(text.includes('preface'), true);
    const bounded = boundedCause(`-----BEGIN PRIVATE KEY-----\n${'SECRETUNCLOSED'.repeat(100)}`);
    assert.equal(bounded.includes('SECRETUNCLOSED'), false);
    assert.equal(bounded.length <= 240, true);
});

test('malformed and nested pem markers redact the rest', () => {
    const overlong = sanitizeDiagnostic(`preface -----BEGIN ${'A'.repeat(65)}-----\nSHORTKEYFRAGMENT`);
    assert.equal(overlong, 'preface [redacted]');
    const lowercase = sanitizeDiagnostic('preface -----BEGIN private key-----\nSHORTKEYFRAGMENT');
    assert.equal(lowercase, 'preface [redacted]');
    const truncated = sanitizeDiagnostic('preface -----BEGIN PRIVATE KEY\nSHORTKEYFRAGMENT');
    assert.equal(truncated, 'preface [redacted]');
    const nested = sanitizeDiagnostic(
        'preface\n-----BEGIN PRIVATE KEY-----\nOUTERSECRET\n'
        + '-----BEGIN CERTIFICATE-----\nINNERSECRET\n-----END CERTIFICATE-----\n'
        + 'TAILSECRET\n-----END PRIVATE KEY-----',
    );
    assert.equal(nested, 'preface [redacted]');
    assert.equal(nested.includes('TAILSECRET'), false);
    assert.equal(nested.includes('INNERSECRET'), false);
    const mismatched = sanitizeDiagnostic(
        'preface -----BEGIN PRIVATE KEY-----\nOUTERSECRET\n-----END CERTIFICATE-----\nTAILSECRET',
    );
    assert.equal(mismatched, 'preface [redacted]');
    assert.equal(mismatched.includes('TAILSECRET'), false);
});

test('long and repeated pem input stays redacted without a slow scan', () => {
    const body = `${'A'.repeat(200000)}SECRETLONG`;
    const longBlock = sanitizeDiagnostic(
        `preface -----BEGIN CERTIFICATE-----\n${body}\n-----END CERTIFICATE-----\nkept-tail`,
    );
    assert.equal(longBlock, 'preface [redacted]');
    assert.equal(longBlock.includes('SECRETLONG'), false);
    assert.equal(longBlock.includes('kept-tail'), false);
    const attack = `preface ${'-----BEGIN -----'.repeat(20000)}SHORTKEYFRAGMENT`;
    const started = performance.now();
    const repeated = sanitizeDiagnostic(attack);
    const elapsed = performance.now() - started;
    assert.equal(repeated, 'preface [redacted]');
    assert.equal(repeated.includes('SHORTKEYFRAGMENT'), false);
    assert.equal(elapsed < 1000, true);
    assert.equal(repeated.length <= 'preface [redacted]'.length, true);
});

function lookupLocal(_hostname, options, callback) {
    if (typeof options === 'function') {
        callback = options;
        options = {};
    }
    if (options && options.all) callback(null, [{ address: '127.0.0.1', family: 4 }]);
    else callback(null, '127.0.0.1', 4);
}

function makeCa(directory, name) {
    const run = (args) => execFileSync('openssl', args, { stdio: 'ignore' });
    const ca = path.join(directory, `${name}.pem`);
    const key = path.join(directory, `${name}.key`);
    run(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', `/CN=${name}`,
        '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
        '-keyout', key, '-out', ca]);
    return { ca, key };
}

function makeLeaf(directory, ca, name, san) {
    const run = (args) => execFileSync('openssl', args, { stdio: 'ignore' });
    const key = path.join(directory, `${name}.key`);
    const csr = path.join(directory, `${name}.csr`);
    const cert = path.join(directory, `${name}.pem`);
    const ext = path.join(directory, `${name}.ext`);
    run(['req', '-newkey', 'rsa:2048', '-nodes', '-subj', `/CN=${name}`, '-keyout', key, '-out', csr]);
    fs.writeFileSync(ext, `subjectAltName=${san}\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n`);
    run(['x509', '-req', '-in', csr, '-CA', ca.ca, '-CAkey', ca.key, '-CAcreateserial', '-out', cert, '-days', '1', '-extfile', ext]);
    return { cert, key };
}

function serve(leaf) {
    const server = https.createServer({
        cert: fs.readFileSync(leaf.cert),
        key: fs.readFileSync(leaf.key),
    }, (_req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('{"issuer":"https://sso.uds.dev/realms/uds"}');
    });
    return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function call(server, hostname, trust) {
    const url = `https://${hostname}:${server.address().port}/realms/uds/.well-known/openid-configuration`;
    return issuerRequest(url, { method: 'GET', lookup: lookupLocal }, trust);
}

test('a missing bundle file is not the same as an empty Core bundle', () => {
    const missing = path.join(os.tmpdir(), `missing-bundle-${process.pid}.pem`);
    assert.equal(readOptional(missing, fs.readFileSync), null);
    const present = path.join(os.tmpdir(), `empty-bundle-${process.pid}.pem`);
    fs.writeFileSync(present, '');
    try {
        assert.equal(readOptional(present, fs.readFileSync), '');
    } finally {
        fs.unlinkSync(present);
    }
});

test('live Core roots can be added and removed without dropping the TAK CA or a stale init copy', async () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sso-trust-'));
    const tak = makeCa(directory, 'tak');
    const core = makeCa(directory, 'core');
    const takLeaf = makeLeaf(directory, tak, 'tak-leaf', 'DNS:sso.uds.dev');
    const coreLeaf = makeLeaf(directory, core, 'core-leaf', 'DNS:sso.uds.dev');
    const wrongLeaf = makeLeaf(directory, core, 'wrong-leaf', 'DNS:other.example');
    const takPem = fs.readFileSync(tak.ca, 'utf8');
    const corePem = fs.readFileSync(core.ca, 'utf8');
    const staleInitCopy = `${takPem}\n${corePem}`;
    const takServer = await serve(takLeaf);
    const coreServer = await serve(coreLeaf);
    const wrongServer = await serve(wrongLeaf);
    const trust = (liveBundle) => issuerTrust({ takCa: takPem, liveBundle, roots: tls.rootCertificates });
    try {
        await assert.rejects(call(coreServer, 'sso.uds.dev', trust(null)), (error) => error.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE');
        assert.equal((await call(takServer, 'sso.uds.dev', trust(null))).status, 200);
        assert.equal((await call(coreServer, 'sso.uds.dev', trust(corePem))).status, 200);
        assert.equal((await call(takServer, 'sso.uds.dev', trust(corePem))).status, 200);
        await assert.rejects(call(coreServer, 'sso.uds.dev', trust('')), (error) => error.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE');
        assert.equal(staleInitCopy.includes('BEGIN CERTIFICATE'), true);
        await assert.rejects(call(coreServer, 'sso.uds.dev', trust(null)), (error) => error.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE');
        assert.equal((await call(takServer, 'sso.uds.dev', trust(''))).status, 200);
        await assert.rejects(
            call(wrongServer, 'sso.uds.dev', trust(corePem)),
            (error) => error.code === 'ERR_TLS_CERT_ALTNAME_INVALID',
        );
    } finally {
        takServer.close();
        coreServer.close();
        wrongServer.close();
    }
    assert.equal(LIVE_BUNDLE_FILE, '/var/run/uds-trust/ca-bundle.pem');
    assert.equal(TAK_CA_FILE, '/var/run/tak-ca/ca.pem');
});
