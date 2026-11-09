// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Discovery and token calls to Keycloak. The TAK CA is stable. Core's live
// bundle is the only source of Core roots: a CA Core removes is not trusted
// on the next call, and a missing bundle does not fall back to the init copy.
// Certificate verification stays enabled.
export const TAK_CA_FILE = '/var/run/tak-ca/ca.pem';
export const LIVE_BUNDLE_FILE = '/var/run/uds-trust/ca-bundle.pem';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';

const JWT = /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/g;
const LONG_TOKEN = /[A-Za-z0-9+/_-]{40,}={0,2}/g;
const PEM_BEGIN = '-----BEGIN';

// A diagnostic does not need the bytes after a PEM marker. One search keeps
// the work linear, and every malformed, nested, or mismatched tail stays out.
function redactPemBlocks(text) {
    const start = text.indexOf(PEM_BEGIN);
    if (start < 0) return text;
    return `${text.slice(0, start)}[redacted]`;
}

export function sanitizeDiagnostic(value) {
    let text = String(value || '');
    text = redactPemBlocks(text);
    text = text.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]');
    text = text.replace(JWT, '[redacted]');
    text = text.replace(/https?:\/\/[^\s]+/g, (url) => {
        try {
            const parsed = new URL(url);
            return `${parsed.origin}${parsed.pathname}`;
        } catch {
            return '[url]';
        }
    });
    text = text.replace(LONG_TOKEN, '[redacted]');
    return text.replace(/\s+/g, ' ').trim();
}

export function boundedCause(error) {
    if (typeof error === 'string') return sanitizeDiagnostic(error).slice(0, 240);
    const codes = [];
    const messages = [];
    const seen = new Set();
    const walk = (current, depth) => {
        if (!current || typeof current !== 'object' || depth > 4 || seen.has(current)) return;
        seen.add(current);
        if (current.code) codes.push(String(current.code));
        if (current.message) messages.push(String(current.message));
        if (Array.isArray(current.errors)) current.errors.forEach((item) => walk(item, depth + 1));
        walk(current.cause, depth + 1);
    };
    walk(error, 0);
    const code = codes.find((item) => /^[A-Z][A-Z0-9_]{0,79}$/.test(item)) || '';
    const name = error && error.name ? String(error.name) : 'Error';
    const message = sanitizeDiagnostic(messages.join('; ')).slice(0, 180);
    return (code ? `${name}: ${code}: ${message}` : `${name}: ${message}`).slice(0, 240);
}

export function certificates(text) {
    return String(text || '').match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) || [];
}

export function readOptional(path, readFileSync) {
    try {
        return readFileSync(path, 'utf8');
    } catch (error) {
        if (!error || error.code !== 'ENOENT') throw error;
        return null;
    }
}

// `liveBundle === null` means Core has no bundle file. An empty file means
// Core currently publishes no custom roots. The init container's combined
// copy is intentionally not an input.
export function issuerTrust({ takCa = '', liveBundle = null, roots = tls.rootCertificates } = {}) {
    const core = liveBundle == null ? [] : certificates(liveBundle);
    return [...roots, ...certificates(takCa), ...core];
}

export function issuerRequest(url, options, ca) {
    return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (fn, value) => {
            if (settled) return;
            settled = true;
            fn(value);
        };
        const parsed = new URL(url);
        const request = https.request({
            hostname: parsed.hostname,
            port: parsed.port || 443,
            path: `${parsed.pathname}${parsed.search}`,
            method: options.method || 'GET',
            headers: options.headers,
            ca,
            rejectUnauthorized: true,
            servername: net.isIP(parsed.hostname) ? undefined : parsed.hostname,
            lookup: options.lookup,
            timeout: 20000,
        }, (response) => {
            const chunks = [];
            response.on('data', (chunk) => chunks.push(chunk));
            response.on('end', () => finish(resolve, {
                status: response.statusCode,
                text: Buffer.concat(chunks).toString('utf8'),
            }));
        });
        request.on('error', (error) => finish(reject, error));
        request.on('timeout', () => {
            const error = new Error('TLS connection timed out');
            error.code = 'ETIMEDOUT';
            request.destroy(error);
        });
        if (options.body) request.write(options.body);
        request.end();
    });
}
