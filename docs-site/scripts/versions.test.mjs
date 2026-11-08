// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { readFileSync, existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
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
  const current = versionForPath('/uds-takserver/main/data/', versions);
  assert.equal(current.id, 'main');
  assert.equal(relativePage('/uds-takserver/main/data/', current), 'data');
  assert.equal(versionHref(versions[0], 'data'), '/uds-takserver/data/');
  assert.equal(versionHref(versions[0], 'not-a-page'), '/uds-takserver/');
  assert.equal(versionForPath('/uds-takserver/mainly/', versions).id, versions[0].id);
});

test('each channel publishes its own content, search filter, source links, and navigation', () => {
  assert.ok(versions.length >= 2);
  assert.equal(versions[0].prefix, '');
  assert.match(versions[0].ref, /^v\d+\.\d+\.\d+$/);
  for (const version of versions) {
    const root = path.join(site, 'dist', version.prefix);
    assert.ok(existsSync(path.join(root, 'index.html')), `${version.id} has no landing page`);
    if (version.prefix === '') {
      const landing = readFileSync(path.join(site, 'src/content/docs/index.mdx'), 'utf8');
      const authored = readFileSync(path.join(site, 'src/home.mdx'), 'utf8');
      const body = (markdown) => markdown.replace(/^---\r?\n[\s\S]*?\r?\n---/, '').trim();
      assert.equal(body(landing), body(authored), 'the default root must publish the current project overview');
      assert.ok(landing.includes('edit/main/docs-site/src/home.mdx'), 'the shared landing must edit its actual main source');
    }
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


test('the current root landing does not replace released guides or archived homes', () => {
  const temporary = mkdtempSync(path.join(tmpdir(), 'tak-landing-source-'));
  try {
    const released = path.join(temporary, 'released');
    const output = path.join(temporary, 'output');
    mkdirSync(path.join(released, 'docs'), { recursive: true });
    mkdirSync(path.join(released, 'adr'));
    writeFileSync(path.join(released, 'adr/0001-example.md'), '# Example decision\n\nReleased decision sentinel.\n');
    mkdirSync(path.join(released, 'docs-site/src'), { recursive: true });
    writeFileSync(path.join(released, 'README.md'), '# Released installation\n\nReleased installation sentinel.\n');
    writeFileSync(path.join(released, 'docs/data.md'), '# Released data\n\nReleased guide sentinel.\n');
    writeFileSync(path.join(released, 'docs-site/src/home.mdx'), `---
title: Historical home
editUrl: https://github.com/jonathanagustin/uds-takserver/edit/main/docs-site/src/home.mdx
---
Historical home sentinel. [Data](/uds-takserver/data/)
`);
    const landing = path.join(temporary, 'current-home.mdx');
    writeFileSync(landing, `---
title: Current project home
editUrl: https://example.invalid/wrong-source
---
Current landing sentinel. [Data](/uds-takserver/data/)
`);
    const sync = (prefix, current) => execFileSync(process.execPath, [path.join(site, 'scripts/sync-docs.mjs'),
      '--repo-root', released, '--output-root', path.join(output, prefix),
      '--url-prefix', prefix, '--source-ref', prefix ? 'v0.8.0' : 'v0.9.1',
      '--version-id', prefix || 'v0-9', '--skip-video-download',
      ...(current ? ['--landing-source', landing] : []),
    ], { stdio: 'pipe' });
    sync('', true);
    const rootHome = readFileSync(path.join(output, 'index.mdx'), 'utf8');
    assert.match(rootHome, /Current landing sentinel/);
    assert.doesNotMatch(rootHome, /Historical home sentinel|example\.invalid/);
    assert.match(rootHome, /editUrl: "https:\/\/github\.com\/jonathanagustin\/uds-takserver\/edit\/main\/docs-site\/src\/home\.mdx"/);
    assert.match(rootHome, /\[Data\]\(\/uds-takserver\/data\/\)/);
    const guide = readFileSync(path.join(output, 'data.md'), 'utf8');
    assert.match(guide, /Released guide sentinel/);
    assert.match(guide, /blob\/v0\.9\.1\/docs\/data\.md/);
    assert.match(readFileSync(path.join(output, 'getting-started.md'), 'utf8'), /Released installation sentinel/);
    sync('v0-8', false);
    const oldHome = readFileSync(path.join(output, 'v0-8/index.mdx'), 'utf8');
    assert.match(oldHome, /Historical home sentinel/);
    assert.doesNotMatch(oldHome, /Current landing sentinel/);
    assert.match(oldHome, /blob\/v0\.8\.0\/docs-site\/src\/home\.mdx/);
    assert.match(oldHome, /\[Data\]\(\/uds-takserver\/v0-8\/data\/\)/);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});


test('a titleless README uses its centered introduction without consuming fenced shell comments', () => {
  const temporary = mkdtempSync(path.join(tmpdir(), 'tak-titleless-readme-'));
  try {
    const source = path.join(temporary, 'source');
    const output = path.join(temporary, 'output');
    mkdirSync(path.join(source, 'adr'), { recursive: true });
    writeFileSync(path.join(source, 'adr/0001-example.md'), '# Example decision\n\nA decision.\n');
    const readme = `<p align="center"><img src="badge.svg" alt="Badge"></p>

<p align="center">TAK Server and <strong>CloudTAK</strong> on UDS Core.</p>

## Install

\`\`\`bash
# Create the package from this directory.
printf '%s\\n' 'Keep this command intact.'
\`\`\`

~~~~sh
# Keep this other shell comment too.
echo 'A second fenced block.'
~~~~
`;
    writeFileSync(path.join(source, 'README.md'), readme);
    execFileSync(process.execPath, [path.join(site, 'scripts/sync-docs.mjs'),
      '--repo-root', source, '--output-root', output, '--source-ref', 'main',
      '--version-id', 'main', '--skip-video-download',
    ], { stdio: 'pipe' });
    const generated = readFileSync(path.join(output, 'getting-started.md'), 'utf8');
    assert.match(generated, /^title: "Getting started"$/m);
    assert.match(generated, /^description: "TAK Server and CloudTAK on UDS Core\."$/m);
    assert.deepEqual(generated.match(/(```[\s\S]*?```|~~~~[\s\S]*?~~~~)/g), readme.match(/(```[\s\S]*?```|~~~~[\s\S]*?~~~~)/g));
    assert.ok(generated.includes('# Create the package from this directory.'));
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
