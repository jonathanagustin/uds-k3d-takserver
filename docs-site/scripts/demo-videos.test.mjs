// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { embedDemoVideos } from './demo-videos.mjs';

const available = new Set(['demo-deploy.mp4', 'demo-operate-and-trust.mp4']);

test('the actual README renders both recordings without download links', () => {
  const readme = readFileSync(new URL('../../README.md', import.meta.url), 'utf8');
  assert.doesNotMatch(readme, /\[Download[^\]]*\]/);
  const rendered = embedDemoVideos(readme, available);
  assert.equal((rendered.match(/<video controls preload="none" playsinline/g) ?? []).length, 2);
  for (const name of available) {
    assert.ok(rendered.includes(`<source src="/uds-takserver/demo/${name}" type="video/mp4" />`));
  }
  assert.doesNotMatch(rendered, /^https:\/\/github.com\/user-attachments\/assets\//m);
});

test('recordings without a verified local asset remain untouched', () => {
  const input = 'https://github.com/user-attachments/assets/7d727d39-b4f1-4251-b440-57c7799c51d1';
  assert.equal(embedDemoVideos(input, new Set()), input);
});

test('historical attachment and poster links retain their existing embedding', () => {
  const attachment = 'https://github.com/user-attachments/assets/historical-id\n\n[Download](https://github.com/example/project/releases/download/demo/demo-deploy.mp4)';
  assert.match(embedDemoVideos(attachment, available), /<source src="\/uds-takserver\/demo\/demo-deploy.mp4"/);
  const poster = '[![Deploy](poster.jpg)](https://github.com/example/project/releases/download/demo/demo-deploy.mp4)';
  assert.match(embedDemoVideos(poster, available), /poster="poster.jpg" aria-label="Deploy"/);
  assert.equal(embedDemoVideos(poster, new Set()), poster);
});
