// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import { docsReleaseTags, publishedReleaseTags, releaseInventoryMode } from './published-releases.mjs';
import { selectReleaseTags } from './build-versions.mjs';

const base = 'https://api.github.com/repos/jonathanagustin/uds-takserver';
const row = (id, tag, extra = {}) => ({ id, tag_name: tag, draft: false, prerelease: false,
  url: `${base}/releases/${id}`, ...extra });
const inventory = [row(13, 'v0.13.0', { draft: true }), row(12, 'v0.12.2'), row(11, 'v0.11.1'),
  row(10, 'v0.10.1'), row(9, 'v0.9.0'), row(8, 'v0.8.0'), row(7, 'v0.7.0'),
  row(14, 'v0.14.0-rc.1', { prerelease: true }), row(15, 'demo')];
const gitTags = inventory.map((release) => release.tag_name);
const response = (value) => new Response(JSON.stringify(value));

function api(rows = inventory) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    if (url === `${base}/releases?per_page=100&page=1`) return response(rows);
    const tag = url.split('/releases/tags/')[1];
    const release = rows.find((value) => value.tag_name === tag && !value.draft);
    return release ? response(release) : new Response('not found', { status: 404 });
  };
  return { fetcher, calls };
}

test('hosted versions exclude draft Git tags and retain five published minor lines', async () => {
  const { fetcher, calls } = api();
  const result = await docsReleaseTags(gitTags, { fetcher, environment: { CI: 'true' } });
  assert.equal(result.mode, 'published');
  assert.deepEqual(selectReleaseTags(result.tags).map((version) => version.ref),
    ['v0.12.2', 'v0.11.1', 'v0.10.1', 'v0.9.0', 'v0.8.0']);
  assert.equal(result.tags.includes('v0.13.0'), false);
  assert.equal(result.tags.includes('v0.14.0-rc.1'), false);
  assert.equal(calls[0].options.redirect, 'error');
  assert.ok(calls[0].options.signal instanceof AbortSignal);
  const generator = readFileSync(new URL('./build-versions.mjs', import.meta.url), 'utf8');
  assert.match(generator, /main \(unreleased\)/);
  assert.ok(generator.indexOf('await docsReleaseTags') < generator.indexOf('await rm(output'));
});

test('explicit requested release must be published by tag and match inventory identity', async () => {
  for (const requestedTag of ['v0.12.2', 'v0.13.0', 'v0.14.0-rc.1', 'main']) {
    const { fetcher, calls } = api();
    if (requestedTag === 'v0.12.2') {
      assert.ok((await publishedReleaseTags({ fetcher, requestedTag })).includes(requestedTag));
      assert.equal(calls.at(-1).url, `${base}/releases/tags/v0.12.2`);
    } else await assert.rejects(publishedReleaseTags({ fetcher, requestedTag }));
  }
  const ordinary = api();
  await assert.rejects(publishedReleaseTags({ requestedTag: 'v0.12.2', fetcher: async (url, opts) =>
    url.includes('/releases/tags/') ? response(row(999, 'v0.12.2')) : ordinary.fetcher(url, opts) }));
});

test('unavailable or malformed inventory cannot fall back to Git tags in CI', async () => {
  const invalid = [{}, null, [row(1, 'v0.12.2', { draft: undefined })],
    [row(1, 'v0.12.2', { url: 'https://api.github.com/repos/foreign/repo/releases/1' })],
    [row(1, 'v0.12.2'), row(1, 'v0.11.0')], [row(1, 'v0.12.2'), row(2, 'v0.12.2')], []];
  for (const value of invalid) await assert.rejects(docsReleaseTags(gitTags, {
    environment: { CI: 'true' }, fetcher: async () => response(value) }));
  for (const status of [401, 403, 404, 429, 503]) await assert.rejects(docsReleaseTags(gitTags, {
    environment: { CI: 'true' }, fetcher: async () => new Response('failure', { status }) }));
  await assert.rejects(docsReleaseTags(gitTags, { environment: { CI: 'true' },
    fetcher: async () => { throw new Error('unavailable'); } }));
  await assert.rejects(publishedReleaseTags({ fetcher: async () => new Response('not JSON') }));
  await assert.rejects(publishedReleaseTags({ fetcher: async () => new Response('x'.repeat(2 * 1024 * 1024 + 1)) }));
  await assert.rejects(docsReleaseTags(['v0.11.1'], { fetcher: api().fetcher, environment: { CI: 'true' } }));
});

test('pagination is complete and bounded rather than accepting a truncated inventory', async () => {
  const first = Array.from({ length: 100 }, (_, index) => row(index + 1, `historical-${index}`));
  const calls = [];
  assert.deepEqual(await publishedReleaseTags({ fetcher: async (url) => {
    calls.push(url); return response(url.endsWith('page=1') ? first : [row(101, 'v0.12.2')]);
  } }), ['v0.12.2']);
  assert.equal(calls.length, 2);
  let page = 0;
  await assert.rejects(publishedReleaseTags({ fetcher: async () => {
    page++;
    return response(Array.from({ length: 100 }, (_, index) => row(page * 100 + index + 1, `archive-${page}-${index}`)));
  } }));
  assert.equal(page, 10);
});

test('offline Git-tag previews require explicit non-CI mode and cannot verify releases', async () => {
  const fetcher = async () => { throw new Error('network must not run'); };
  assert.equal(releaseInventoryMode({}), 'published');
  assert.equal(releaseInventoryMode({ CI: 'true' }), 'published');
  assert.throws(() => releaseInventoryMode({ CI: 'true', DOCS_LOCAL_TAG_PREVIEW: '1' }));
  assert.throws(() => releaseInventoryMode({ DOCS_LOCAL_TAG_PREVIEW: 'false' }));
  assert.deepEqual(await docsReleaseTags(gitTags, { fetcher,
    environment: { DOCS_LOCAL_TAG_PREVIEW: '1' } }), { tags: gitTags, mode: 'git-preview' });
  await assert.rejects(docsReleaseTags(gitTags, { fetcher,
    environment: { DOCS_LOCAL_TAG_PREVIEW: '1', DOCS_RELEASE_TAG: 'v0.13.0' } }));
});

test('manual Docs rejects non-main or missing tag before building and preserves publication guards', () => {
  const root = path.resolve(import.meta.dirname, '../..');
  const workflow = readFileSync(path.join(root, '.github/workflows/docs.yaml'), 'utf8');
  const manual = workflow.split('  workflow_dispatch:')[1].split('  release:')[0];
  assert.match(manual, /release_tag:[\s\S]*required: true/);
  const guard = workflow.split('- name: Require manual publication from main')[1].split('- name: Verify')[0];
  assert.match(guard, /if: github.event_name == 'workflow_dispatch'/);
  const script = guard.split('        run: |\n')[1].split('\n').map((line) => line.trim()).filter(Boolean).join('\n');
  for (const [ref, tag, success] of [['refs/heads/main', 'v0.12.2', true],
    ['refs/heads/other', 'v0.12.2', false], ['refs/heads/main', '', false]]) {
    const result = spawnSync('bash', ['-euc', script], { env: { ...process.env, DOCS_REF: ref, RELEASE_TAG: tag } });
    assert.equal(result.status === 0, success);
  }
  assert.match(workflow, /DOCS_RELEASE_TAG: \$\{\{ inputs.release_tag \|\| github.event.release.tag_name \}\}/);
  assert.match(workflow, /git merge-base --is-ancestor "refs\/tags\/\$\{RELEASE_TAG\}" HEAD/);
  assert.equal((workflow.match(/github.event_name != 'pull_request' &&/g) || []).length, 2);
  assert.match(workflow, /permissions:\n  contents: read/);
  assert.match(workflow, /NODE_USE_ENV_PROXY: 1/);
  assert.match(readFileSync(path.join(root, '.github/workflows/unit-tests.yaml'), 'utf8'),
    /run: node --test docs-site\/scripts\/published-releases.test.mjs/);
  assert.match(JSON.parse(readFileSync(path.join(root, 'docs-site/package.json'), 'utf8')).scripts.build,
    /published-releases.test.mjs/);
});
