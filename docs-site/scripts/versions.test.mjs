// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { selectReleaseTags } from './build-versions.mjs';
import { versionForPath, versionHref, relativePage } from '../src/lib/versions.mjs';

const site = path.resolve(import.meta.dirname, '..');
const versions = JSON.parse(readFileSync(path.join(site, 'src/generated/versions.json'), 'utf8'));

test('release selection keeps newest stable patch per minor, numerically, with a bounded history', () => {
  assert.deepEqual(selectReleaseTags(['v0.6.8', 'v0.7.0', 'v0.7.10', 'v0.7.2', 'v0.8.0',
    'v0.9.1', 'v0.10.0', 'v1.0.0', 'v1.1.0-rc.1', 'demo', 'v1.0.1'], 3), [
    { id: 'v1-0', ref: 'v1.0.1', minor: '1.0' },
    { id: 'v0-10', ref: 'v0.10.0', minor: '0.10' },
    { id: 'v0-9', ref: 'v0.9.1', minor: '0.9' },
  ]);
});

test('version navigation preserves matching pages and falls back when the destination lacks one', () => {
  const current = versionForPath('/uds-k3d-takserver/main/data/', versions);
  assert.equal(current.id, 'main');
  assert.equal(relativePage('/uds-k3d-takserver/main/data/', current), 'data');
  assert.equal(versionHref(versions[0], 'data'), '/uds-k3d-takserver/data/');
  assert.equal(versionHref(versions[0], 'not-a-page'), '/uds-k3d-takserver/');
  assert.equal(versionForPath('/uds-k3d-takserver/mainly/', versions).id, versions[0].id);
});

test('each channel publishes its own content, search filter, source links, and navigation', () => {
  assert.ok(versions.length >= 2);
  assert.equal(versions[0].prefix, '');
  assert.match(versions[0].ref, /^v\d+\.\d+\.\d+$/);
  for (const version of versions) {
    const root = path.join(site, 'dist', version.prefix);
    assert.ok(existsSync(path.join(root, 'index.html')), `${version.id} has no landing page`);
    const html = readFileSync(path.join(root, 'data/index.html'), 'utf8');
    assert.ok(html.includes(`data-docs-version="${version.id}"`), `${version.id} filter is missing`);
    assert.ok(html.includes(`data-pagefind-filter="version:${version.id}"`));
    const source = version.id === 'main' ? 'edit/main' : `blob/${version.ref}`;
    assert.ok(html.includes(`${source}/docs/data.md`), `${version.id} points to the wrong source`);
    assert.equal(html.includes('You are reading unreleased main documentation.'), version.id === 'main');
    assert.ok(html.includes('Documentation version'));
    const historyRef = version.id === 'main' ? 'HEAD' : version.ref;
    const date = execFileSync('git', ['log', '-1', '--format=%cI', historyRef, '--', 'docs/data.md'],
      { cwd: path.join(site, '..'), encoding: 'utf8' }).trim().slice(0, 10);
    const sourceFile = readFileSync(path.join(site, 'src/content/docs', version.prefix, 'data.md'), 'utf8');
    assert.ok(sourceFile.includes(`lastUpdated: ${date}`), `${version.id} uses the wrong history`);
  }
});
