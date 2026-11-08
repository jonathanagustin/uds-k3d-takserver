// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { howToSteps } from './how-to-ui.mjs';

const guides = ['backup-and-restore', 'check-uptime-and-portal', 'connect-atak-test-device', 'connect-takx-desktop', 'upgrade-from-0-6'];

test('current guides gain Steps without changing commands or warning callouts', () => {
  for (const guide of guides) {
    const source = readFileSync(new URL(`../../docs/how-to/${guide}.md`, import.meta.url), 'utf8');
    const result = howToSteps(source);
    assert.ok(result.includes('<Steps>\n1. '), guide);
    assert.match(result, /<\/Steps>\n\n## Verification/);
    assert.deepEqual(result.match(/```[\s\S]*?```/g), source.match(/```[\s\S]*?```/g));
    assert.deepEqual(result.match(/^>.*$/gm), source.match(/^>.*$/gm));
  }
});

test('MDX protects prose literals and preserves inline code and hidden comments', () => {
  const source = 'Literal {value} and <domain>. `keep {this}`\n<!-- hidden -->\n\n## Steps\n\n1. Run it.\n\n## Verification\n\nCheck it.\n';
  const result = howToSteps(source);
  assert.ok(result.includes('Literal &#123;value&#125; and &lt;domain>. `keep {this}`'));
  assert.ok(result.includes('{/* hidden */}'));
  assert.equal(howToSteps('## Steps\n\nNo procedure yet.\n'), null);
});
