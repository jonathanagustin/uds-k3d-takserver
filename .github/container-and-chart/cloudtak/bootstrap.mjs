// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Connect CloudTAK to the in-cluster TAK Server, then keep that state.
//
// Runs as a second container in the CloudTAK pod and talks to CloudTAK on
// 127.0.0.1, so its calls never cross the mesh or Authservice. Every
// BOOTSTRAP_INTERVAL_SECONDS it:
//
// 1. Makes sure the TAK file user CLOUDTAK_USERNAME exists with the password
//    from the Secret. TAK keeps file users in a file inside the API pod, so a
//    restarted API pod has lost the user. The admin certificate creates it
//    again through /user-management/api on 8443.
// 2. If CloudTAK is unconfigured, sends PATCH /api/server with the TAK URLs,
//    the admin certificate, and that user. CloudTAK answers this call without
//    a login only while it is unconfigured, and makes the user its system
//    administrator. Doing it at startup closes that window.
//
// `node bootstrap.mjs status` logs in as that user and prints the server
// record, including connection_status. It exits 1 unless the admin
// connection is live.

import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';

const env = (name, fallback) => {
    const value = process.env[name] ?? fallback;
    if (value === undefined || value === '') throw new Error(`${name} is not set`);
    return value;
};

const cloudtak = new URL(env('CLOUDTAK_LOCAL_URL', 'http://127.0.0.1:5000'));
const takApi = new URL(env('TAK_API_URL'));
const takWeb = new URL(env('TAK_WEB_URL'));
const takStream = env('TAK_STREAM_URL');
const certDir = env('TAK_ADMIN_DIR', '/var/run/tak-admin');
const username = env('CLOUDTAK_USERNAME');
const password = env('CLOUDTAK_PASSWORD');
const groups = env('TAK_USER_GROUPS', 'Operators').split(',').map((g) => g.trim()).filter(Boolean);
const interval = Number(env('BOOTSTRAP_INTERVAL_SECONDS', '300')) * 1000;

const ca = fs.readFileSync(`${certDir}/ca.pem`, 'utf8');
const adminCert = fs.readFileSync(`${certDir}/admin.pem`, 'utf8');
// makeCert.sh encrypts client keys with the keystore password. CloudTAK
// stores a key it can load without one, so hand it an unencrypted PKCS#8 copy.
const adminKey = crypto.createPrivateKey({
    key: fs.readFileSync(`${certDir}/admin.key`, 'utf8'),
    passphrase: env('TAK_ADMIN_KEY_PASSPHRASE', 'atakatak'),
}).export({ type: 'pkcs8', format: 'pem' });

function request(url, { method = 'GET', headers = {}, body, tls = {} } = {}) {
    const payload = body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body));
    const lib = url.protocol === 'https:' ? https : http;
    return new Promise((resolve, reject) => {
        const req = lib.request(url, {
            method,
            headers: {
                ...(payload !== undefined && typeof body !== 'string' ? { 'Content-Type': 'application/json' } : {}),
                ...(payload !== undefined ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
                ...headers,
            },
            timeout: 30000,
            ...tls,
        }, (res) => {
            let text = '';
            res.setEncoding('utf8');
            res.on('data', (chunk) => { text += chunk; });
            res.on('end', () => resolve({ status: res.statusCode, text }));
        });
        req.on('timeout', () => req.destroy(new Error(`timeout: ${method} ${url}`)));
        req.on('error', reject);
        if (payload !== undefined) req.write(payload);
        req.end();
    });
}

// 8447 has a certificate for its Service name, so it gets full verification.
// 8443 presents TAK's generated server certificate, which is signed by the
// same CA but names no in-cluster host. The chain is still checked against
// that CA. Only the host name check is off for 8443.
const webTls = { ca };
const adminTls = { ca, cert: adminCert, key: adminKey, checkServerIdentity: () => undefined };

const takAdmin = (path, opts = {}) => request(new URL(path, takApi), { ...opts, tls: adminTls });
const local = (path, opts = {}) => request(new URL(path, cloudtak), opts);

async function passwordWorks() {
    const url = new URL('/oauth/token', takWeb);
    const form = new URLSearchParams({ grant_type: 'password', username, password }).toString();
    const res = await request(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form,
        tls: webTls,
    });
    return res.status === 200;
}

async function ensureUser() {
    if (await passwordWorks()) return 'present';
    const user = { username, password, groupList: groups, groupListIN: [], groupListOUT: [] };
    let res = await takAdmin('/user-management/api/new-user', { method: 'POST', body: user });
    if (res.status !== 200 && /already exists/i.test(res.text)) {
        // Same name, different password. Replace the account.
        await takAdmin(`/user-management/api/delete-user/${encodeURIComponent(username)}`, { method: 'DELETE' });
        res = await takAdmin('/user-management/api/new-user', { method: 'POST', body: user });
    }
    if (res.status !== 200) throw new Error(`TAK new-user returned ${res.status}: ${res.text.slice(0, 300)}`);
    if (!(await passwordWorks())) throw new Error('TAK did not accept the new password');
    return 'created';
}

async function configure() {
    const res = await local('/api/server');
    if (res.status === 401 || res.status === 403) return 'configured';
    if (res.status !== 200) throw new Error(`GET /api/server returned ${res.status}`);
    if (JSON.parse(res.text).status !== 'unconfigured') return 'configured';

    const patch = await local('/api/server', {
        method: 'PATCH',
        body: {
            name: 'TAK Server',
            url: takStream,
            api: takApi.origin,
            webtak: takWeb.origin,
            auth: { cert: adminCert, key: adminKey },
            username,
            password,
        },
    });
    if (patch.status !== 200) throw new Error(`PATCH /api/server returned ${patch.status}: ${patch.text.slice(0, 300)}`);
    return `configured now, connection ${JSON.parse(patch.text).connection_status}`;
}

async function status() {
    const login = await local('/api/login', { method: 'POST', body: { username, password } });
    if (login.status !== 200) throw new Error(`POST /api/login returned ${login.status}: ${login.text.slice(0, 300)}`);
    const { token } = JSON.parse(login.text);
    const server = await local('/api/server', { headers: { Authorization: `Bearer ${token}` } });
    if (server.status !== 200) throw new Error(`GET /api/server returned ${server.status}`);
    const body = JSON.parse(server.text);
    delete body.auth;
    delete body.certificate;
    return body;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitForCloudTAK() {
    for (;;) {
        try {
            const res = await local('/api');
            if (res.status === 200) return;
        } catch {
            // CloudTAK is still starting.
        }
        await sleep(5000);
    }
}

if (process.argv[2] === 'status') {
    const body = await status();
    console.log(JSON.stringify(body));
    process.exit(body.connection_status === 'live' ? 0 : 1);
}

await waitForCloudTAK();
for (;;) {
    try {
        const user = await ensureUser();
        const server = await configure();
        console.log(`ok - TAK user ${username}: ${user}; CloudTAK server: ${server}`);
    } catch (err) {
        console.error(`not ok - ${err.message}`);
        await sleep(15000);
        continue;
    }
    await sleep(interval);
}
