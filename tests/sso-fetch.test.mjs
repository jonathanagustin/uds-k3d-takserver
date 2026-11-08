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
    discoveryCa,
    issuerRequest,
    readTrustFiles,
} from '../.github/container-and-chart/cloudtak/sso-fetch.mjs';

test('a fetch failure keeps the cause code and drops secrets', () => {
    const cause = new Error('unable to verify the first certificate -----BEGIN CERTIFICATE-----\nSECRETPEM\n-----END CERTIFICATE----- https://sso.example/realms/uds/.well-known/openid-configuration?code=SECRETTOKEN Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signaturevalue');
    cause.code = 'UNABLE_TO_VERIFY_LEAF_SIGNATURE';
    const error = new TypeError('fetch failed');
    error.cause = cause;
    const text = boundedCause(error);
    assert.match(text, /TypeError: UNABLE_TO_VERIFY_LEAF_SIGNATURE/);
    assert.equal(text.includes('SECRETPEM'), false);
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
});

test('discovery reads a live bundle that the init copy does not have', async () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sso-fetch-'));
    const run = (args) => execFileSync('openssl', args, { stdio: 'ignore' });
    run(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=private-sso-ca',
        '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
        '-keyout', path.join(directory, 'ca.key'), '-out', path.join(directory, 'ca.pem')]);
    run(['req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=sso.uds.dev',
        '-keyout', path.join(directory, 'leaf.key'), '-out', path.join(directory, 'leaf.csr')]);
    fs.writeFileSync(path.join(directory, 'leaf.ext'), 'subjectAltName=IP:127.0.0.1\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n');
    run(['x509', '-req', '-in', path.join(directory, 'leaf.csr'), '-CA', path.join(directory, 'ca.pem'),
        '-CAkey', path.join(directory, 'ca.key'), '-CAcreateserial', '-out', path.join(directory, 'leaf.pem'),
        '-days', '1', '-extfile', path.join(directory, 'leaf.ext')]);
    const live = path.join(directory, 'ca-bundle.pem');
    fs.writeFileSync(live, fs.readFileSync(path.join(directory, 'ca.pem')));
    const missing = path.join(directory, 'missing-bundle.pem');
    assert.deepEqual(readTrustFiles([missing, live], fs.readFileSync).length, 1);
    const server = https.createServer({ cert: fs.readFileSync(path.join(directory, 'leaf.pem')), key: fs.readFileSync(path.join(directory, 'leaf.key')) }, (req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('{"issuer":"https://sso.uds.dev/realms/uds"}');
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const url = `https://127.0.0.1:${server.address().port}/realms/uds/.well-known/openid-configuration`;
    try {
        await assert.rejects(
            issuerRequest(url, { method: 'GET' }, discoveryCa([], tls.rootCertificates)),
            (error) => error.code === 'ERR_TLS_CERT_ALTNAME_INVALID' || error.code === 'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
        );
        const trusted = await issuerRequest(url, { method: 'GET' }, discoveryCa([fs.readFileSync(live, 'utf8')], tls.rootCertificates));
        assert.equal(trusted.status, 200);
        assert.match(trusted.text, /issuer/);
    } finally {
        server.close();
    }
});
