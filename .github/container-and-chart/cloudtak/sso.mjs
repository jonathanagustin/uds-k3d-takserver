// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Keycloak sign-in for CloudTAK.
//
// CloudTAK v13 shows a "Sign in with <name>" button when the oidc settings
// are on, and links it to /api/login/oidc, but the API has no route there.
// nginx in the CloudTAK container sends /api/login/oidc* to this process
// on 127.0.0.1. It runs an authorization code flow with PKCE against the
// UDS Keycloak realm and then does what CloudTAK's password login does:
//
//   1. Enrol a TAK client certificate for the user. TAK accepts the Keycloak
//      access token as a bearer token on its enrolment port and takes the
//      username from preferred_username, so the certificate CN is the
//      Keycloak username and TAK gives it the user's Keycloak TAK groups.
//   2. Create or update the CloudTAK profile with that certificate.
//   3. Open a CloudTAK login session with CloudTAK's own session code.
//
// The browser gets the session (login token, refresh token, session id) in
// the URL fragment of a same-origin page, which never reaches a server or a
// log. That page stores it where CloudTAK's own login page does and opens
// the map.
import http from 'node:http';
import crypto from 'node:crypto';
import { Pool } from '@openaddresses/batch-generic';
import { TAKAPI, APIAuthToken } from '@tak-ps/node-tak';
import Models from './dist/common/models.js';
import * as pgtypes from './dist/common/schema.js';
import UserControl from './dist/stateless/lib/control/user.js';
import { issueSession } from './dist/stateless/lib/user/session.js';

const env = (name, fallback) => {
    const value = process.env[name] ?? fallback;
    if (value === undefined || value === '') throw new Error(`${name} is not set`);
    return value;
};

const PORT = Number(process.env.SSO_PORT || 5002);
const PUBLIC_URL = env('API_URL').replace(/\/$/, '');
const ISSUER = env('OIDC_ISSUER').replace(/\/$/, '');
const CLIENT_ID = env('OIDC_CLIENT_ID');
const CLIENT_SECRET = env('OIDC_CLIENT_SECRET');
const SCOPES = process.env.OIDC_SCOPES || 'openid profile email';
const ADMIN_GROUP = process.env.OIDC_ADMIN_GROUP || '';
const TAK_WEB_URL = env('TAK_WEB_URL');
const SIGNING_SECRET = env('SigningSecret');
const BASE = '/api/login/oidc';
const CALLBACK = `${PUBLIC_URL}${BASE}/callback`;
const COOKIE = 'cloudtak_sso';
const COOKIE_TTL = 600;

const log = (...args) => console.error(new Date().toISOString(), ...args);

// Same connection options as CloudTAK's own pool. CloudTAK treats an unset
// StackName as 'test' and then connects without TLS, as it must to the
// in-pod PostGIS here.
const stack = process.env.StackName || 'test';
const pg = await Pool.connect(env('POSTGRES'), pgtypes, {
    ssl: stack === 'test' ? undefined : { rejectUnauthorized: false },
});
const config = {
    pg,
    models: new Models(pg),
    SigningSecret: SIGNING_SECRET,
};
const users = new UserControl(config);

let discovery;
async function oidc() {
    if (discovery) return discovery;
    const res = await fetch(`${ISSUER}/.well-known/openid-configuration`);
    if (!res.ok) throw new Error(`discovery returned ${res.status}`);
    const doc = await res.json();
    if (doc.issuer !== ISSUER) throw new Error(`discovery issuer ${doc.issuer} is not ${ISSUER}`);
    discovery = doc;
    return doc;
}

const b64url = (buf) => Buffer.from(buf).toString('base64url');
const mac = (value) => crypto.createHmac('sha256', SIGNING_SECRET).update(`sso:${value}`).digest('base64url');

function seal(data) {
    const body = b64url(JSON.stringify(data));
    return `${body}.${mac(body)}`;
}

function unseal(value) {
    const [body, sig] = String(value || '').split('.');
    if (!body || !sig) return undefined;
    const want = Buffer.from(mac(body));
    const got = Buffer.from(sig);
    if (want.length !== got.length || !crypto.timingSafeEqual(want, got)) return undefined;
    const data = JSON.parse(Buffer.from(body, 'base64url').toString());
    if (!data.exp || data.exp < Date.now() / 1000) return undefined;
    return data;
}

function cookies(req) {
    const out = {};
    for (const part of String(req.headers.cookie || '').split(';')) {
        const i = part.indexOf('=');
        if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    }
    return out;
}

function setCookie(value, maxAge) {
    return `${COOKIE}=${encodeURIComponent(value)}; Path=${BASE}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;
}

// Only same-origin app paths. Anything else lands on the map.
function safePath(value) {
    const path = String(value || '/');
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return '/';
    if (path.startsWith('/login') || path.startsWith('/api/')) return '/';
    return path;
}

function claims(jwt) {
    const part = String(jwt || '').split('.')[1];
    if (!part) throw new Error('token is not a JWT');
    return JSON.parse(Buffer.from(part, 'base64url').toString());
}

function send(res, status, headers, body = '') {
    res.writeHead(status, { 'Cache-Control': 'no-store', ...headers });
    res.end(body);
}

function fail(res, reason) {
    log(`sign-in failed: ${reason}`);
    // sso=off keeps the auto-redirect script from looping. The login page
    // still shows the Keycloak button.
    send(res, 302, {
        Location: `/login?sso=off&error=${encodeURIComponent('Keycloak sign-in failed. Try again or contact an administrator.')}`,
        'Set-Cookie': setCookie('', 0),
    });
}

async function start(req, res, url) {
    const doc = await oidc();
    const verifier = b64url(crypto.randomBytes(32));
    const state = b64url(crypto.randomBytes(16));
    const nonce = b64url(crypto.randomBytes(16));
    const redirect = safePath(url.searchParams.get('redirect'));
    const target = new URL(doc.authorization_endpoint);
    target.search = new URLSearchParams({
        response_type: 'code',
        client_id: CLIENT_ID,
        redirect_uri: CALLBACK,
        scope: SCOPES,
        state,
        nonce,
        code_challenge: b64url(crypto.createHash('sha256').update(verifier).digest()),
        code_challenge_method: 'S256',
    }).toString();
    send(res, 302, {
        Location: target.toString(),
        'Set-Cookie': setCookie(seal({ state, nonce, verifier, redirect, exp: Math.floor(Date.now() / 1000) + COOKIE_TTL }), COOKIE_TTL),
    });
}

async function callback(req, res, url) {
    const saved = unseal(cookies(req)[COOKIE]);
    if (!saved) return fail(res, 'missing or expired state cookie');
    if (url.searchParams.get('error')) return fail(res, `Keycloak returned ${url.searchParams.get('error')}`);
    if (url.searchParams.get('state') !== saved.state) return fail(res, 'state mismatch');
    const code = url.searchParams.get('code');
    if (!code) return fail(res, 'no authorization code');

    const doc = await oidc();
    const tokenRes = await fetch(doc.token_endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
        body: new URLSearchParams({
            grant_type: 'authorization_code',
            code,
            redirect_uri: CALLBACK,
            client_id: CLIENT_ID,
            client_secret: CLIENT_SECRET,
            code_verifier: saved.verifier,
        }),
    });
    if (!tokenRes.ok) return fail(res, `token endpoint returned ${tokenRes.status}`);
    const tokens = await tokenRes.json();

    // The ID token came straight from the token endpoint over a verified
    // TLS connection, so its claims are checked rather than its signature
    // (OpenID Connect Core 3.1.3.7). TAK checks the access token signature.
    const id = claims(tokens.id_token);
    const now = Date.now() / 1000;
    const aud = Array.isArray(id.aud) ? id.aud : [id.aud];
    if (id.iss !== ISSUER) return fail(res, `issuer ${id.iss}`);
    if (!aud.includes(CLIENT_ID)) return fail(res, 'audience');
    if (id.nonce !== saved.nonce) return fail(res, 'nonce');
    if (!id.exp || id.exp < now) return fail(res, 'expired ID token');

    const access = claims(tokens.access_token);
    const username = String(access.preferred_username || id.preferred_username || '').toLowerCase();
    if (!username) return fail(res, 'no preferred_username claim');
    const groups = Array.isArray(access.groups) ? access.groups : [];

    // TAK certificate for this user, as CloudTAK's password login does.
    const tak = await TAKAPI.init(new URL(TAK_WEB_URL), new APIAuthToken(tokens.access_token));
    const auth = await tak.Credentials.generate({ username });

    let profile;
    const system_admin = ADMIN_GROUP !== '' && groups.includes(ADMIN_GROUP);
    try {
        await config.models.Profile.from(username);
        profile = await config.models.Profile.commit(username, {
            auth,
            system_admin,
            last_login: new Date().toISOString(),
        });
    } catch (err) {
        if (err.status !== 404) throw err;
        await users.generate({ username, auth });
        profile = await config.models.Profile.commit(username, { system_admin });
    }

    const session = await issueSession(config, req, profile);
    log(`signed in ${username} (CloudTAK ${session.access}, TAK certificate enrolled)`);

    const fragment = new URLSearchParams({
        token: session.token,
        refresh: session.refresh,
        session: session.session,
        id_token: tokens.id_token || '',
        redirect: saved.redirect,
    });
    send(res, 302, {
        Location: `${BASE}/finish#${fragment}`,
        'Set-Cookie': setCookie('', 0),
    });
}

// Browser logout. CloudTAK clears its own session and opens /login. auto.js
// sends that here so Keycloak's session ends before the next sign-in.
// post_logout_redirect_uri is this route's start path, which is registered
// on the client. Keycloak then comes back and the authorization request
// shows the login page.
async function logout(_req, res, url) {
    const doc = await oidc();
    if (!doc.end_session_endpoint) return fail(res, 'no end_session_endpoint');
    const params = new URLSearchParams({
        client_id: CLIENT_ID,
        post_logout_redirect_uri: `${PUBLIC_URL}${BASE}`,
    });
    const hint = url.searchParams.get('id_token_hint');
    if (hint) params.set('id_token_hint', hint);
    const target = new URL(doc.end_session_endpoint);
    target.search = params.toString();
    send(res, 302, {
        Location: target.toString(),
        'Set-Cookie': setCookie('', 0),
    });
}

// Served as files so the page works under CloudTAK's script-src 'self'.
const FINISH_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>Signing in</title>
<script src="${BASE}/finish.js"></script></head>
<body>Signing in to CloudTAK...</body></html>
`;

// Capacitor Preferences on the web keeps values in localStorage under the
// CapacitorStorage. prefix. The app's boot only restores a session when a
// login token is stored, then rotates the refresh token, which also writes
// the rest of its session state.
const FINISH_JS = `(function () {
    var p = new URLSearchParams(location.hash.slice(1));
    var token = p.get('token');
    var refresh = p.get('refresh');
    var session = p.get('session');
    var redirect = p.get('redirect') || '/';
    history.replaceState(null, '', location.pathname);
    if (!token || !refresh || !session) { location.replace('/login?sso=off'); return; }
    localStorage.setItem('CapacitorStorage.token', token);
    localStorage.setItem('CapacitorStorage.refresh', refresh);
    localStorage.setItem('CapacitorStorage.sessionId', session);
    var idToken = p.get('id_token');
    if (idToken) localStorage.setItem('cloudtak_sso_id_token', idToken);
    if (redirect.charAt(0) !== '/' || redirect.charAt(1) === '/') redirect = '/';
    location.replace(redirect);
})();
`;

// Loaded into every CloudTAK page by nginx. When the app routes to its
// login page, end the Keycloak session and then show the Keycloak login.
// A visit that is already signed in at Keycloak must not bounce back onto
// the map without a password.
// /login?sso=off shows the page as is. A second redirect within 30 seconds
// also shows the page, so a session the app rejects cannot loop.
const AUTO_JS = `(function () {
    var sent = false;
    var KEY = 'cloudtak-sso-redirect';
    function check() {
        if (sent || location.pathname !== '/login') return;
        var p = new URLSearchParams(location.search);
        if (p.get('sso') === 'off') return;
        var last = Number(sessionStorage.getItem(KEY) || 0);
        if (Date.now() - last < 30000) return;
        sessionStorage.setItem(KEY, String(Date.now()));
        sent = true;
        var hint = localStorage.getItem('cloudtak_sso_id_token') || '';
        localStorage.removeItem('cloudtak_sso_id_token');
        var logout = '${BASE}/logout';
        if (hint) logout += '?id_token_hint=' + encodeURIComponent(hint);
        location.replace(logout);
    }
    check();
    setInterval(check, 250);
})();
`;

const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, PUBLIC_URL);
    try {
        if (req.method !== 'GET') return send(res, 405, { Allow: 'GET' });
        switch (url.pathname) {
        case BASE:
            return await start(req, res, url);
        case `${BASE}/callback`:
            return await callback(req, res, url);
        case `${BASE}/logout`:
            return await logout(req, res, url);
        case `${BASE}/finish`:
            return send(res, 200, { 'Content-Type': 'text/html; charset=utf-8' }, FINISH_HTML);
        case `${BASE}/finish.js`:
            return send(res, 200, { 'Content-Type': 'text/javascript; charset=utf-8' }, FINISH_JS);
        case `${BASE}/auto.js`:
            return send(res, 200, { 'Content-Type': 'text/javascript; charset=utf-8' }, AUTO_JS);
        case '/healthz':
            return send(res, 200, { 'Content-Type': 'text/plain' }, 'ok\n');
        default:
            return send(res, 404, { 'Content-Type': 'text/plain' }, 'not found\n');
        }
    } catch (err) {
        return fail(res, err && err.stack ? err.stack : String(err));
    }
});

server.listen(PORT, '127.0.0.1', () => log(`Keycloak sign-in for ${PUBLIC_URL} on 127.0.0.1:${PORT}, issuer ${ISSUER}`));
