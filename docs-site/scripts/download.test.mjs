// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import test from 'node:test';
import { download } from './download.mjs';

function fixture(results) {
  const calls = [], sleeps = [];
  return { calls, sleeps, options: {
    fetchImpl: async (url, options) => {
      calls.push({ url, ...options });
      const result = results.shift();
      if (result instanceof Error) throw result;
      return result;
    },
    sleep: async (ms) => sleeps.push(ms),
  } };
}
const networkFailure = () => new TypeError('fetch failed', { cause: Object.assign(new Error('reset'), { code: 'ECONNRESET' }) });

test('retries transient HTTP responses and returns the final complete body', async () => {
  const f = fixture([new Response('', { status: 504 }), new Response('', { status: 429 }), new Response('verified later')]);
  assert.equal((await download('https://example.test/asset', f.options)).toString(), 'verified later');
  assert.deepEqual(f.sleeps, [1000, 2000]);
  assert.equal(f.calls.length, 3);
  assert.ok(f.calls.every(({ signal }) => signal instanceof AbortSignal));
});

test('bounds transient network failures at three attempts', async () => {
  const f = fixture([networkFailure(), networkFailure(), networkFailure()]);
  await assert.rejects(download('https://example.test/asset', f.options), /fetch failed/);
  assert.equal(f.calls.length, 3);
  assert.deepEqual(f.sleeps, [1000, 2000]);
});

test('retries interrupted bodies and deadlines, without returning partial bytes', async () => {
  for (const error of [networkFailure(), new DOMException('deadline', 'TimeoutError')]) {
    const f = fixture([{ ok: true, arrayBuffer: async () => { throw error; } }, new Response('complete')]);
    assert.equal((await download('https://example.test/video', f.options)).toString(), 'complete');
    assert.equal(f.calls.length, 2);
  }
});

test('permanent HTTP, URL, TLS, and caller abort errors fail immediately', async () => {
  for (const result of [new Response('', { status: 404 }), new Response('', { status: 403 }),
    new TypeError('Invalid URL'), Object.assign(new Error('untrusted certificate'), { code: 'CERT_HAS_EXPIRED' }),
    new DOMException('cancelled', 'AbortError')]) {
    const f = fixture([result]);
    await assert.rejects(download('https://example.test/asset', f.options));
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.sleeps, []);
  }
});

test('successful but invalid content is returned once for fail-closed caller validation', async () => {
  const f = fixture([new Response('not valid provenance')]);
  const bytes = await download('https://example.test/provenance', f.options);
  assert.throws(() => JSON.parse(bytes.toString()), SyntaxError);
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.sleeps, []);
});
