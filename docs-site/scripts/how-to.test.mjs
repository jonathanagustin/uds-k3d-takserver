// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';

// Run after the production build: a source link can otherwise fall back to
// GitHub and let link validation pass even if discovery omitted a guide.
const siteRoot = path.resolve(import.meta.dirname, '..');
const guides = [
  'backup-and-restore',
  'check-uptime-and-portal',
  'connect-atak-test-device',
  'connect-takx-desktop',
  'upgrade-from-0-6',
];

test('the operational guides are published and use the how-to sections', () => {
  for (const slug of guides) {
    const output = path.join(siteRoot, 'dist/main/how-to', slug, 'index.html');
    assert.ok(existsSync(output), `missing guide route: ${slug}`);
    const html = readFileSync(output, 'utf8');
    for (const section of ['what-youll-accomplish', 'prerequisites', 'before-you-begin',
      'steps', 'verification', 'troubleshooting', 'related-documentation']) {
      assert.ok(html.includes(`id="${section}"`), `${slug} is missing ${section}`);
    }
    assert.ok(html.includes(`edit/main/docs/how-to/${slug}.md`), `${slug} has no source edit link`);
  }
});

test('the authoring template is not published', () => {
  assert.ok(!existsSync(path.join(siteRoot, 'src/content/docs/main/how-to/_template.md')));
  assert.ok(!existsSync(path.join(siteRoot, 'dist/main/how-to/_template')));
});

test('the original reference routes remain available', () => {
  for (const route of ['data', 'atak-device', 'networking']) {
    assert.ok(existsSync(path.join(siteRoot, 'dist/main', route, 'index.html')), `missing ${route}`);
  }
});
