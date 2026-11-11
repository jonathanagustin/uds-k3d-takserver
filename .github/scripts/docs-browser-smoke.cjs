// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Resolve from the locked Docs install, not a globally installed browser.
const { createRequire } = require('node:module');
const { join } = require('node:path');
const assert = require('node:assert/strict');
const local = createRequire(join(process.cwd(), 'package.json'));
assert.equal(local('playwright-core/package.json').version, '1.65.0');
const { chromium } = local('playwright-core');
if (process.argv[2] === 'paths') {
  const { registry } = local('playwright-core/lib/coreBundle').registry;
  console.log(JSON.stringify(['chromium', 'chromium-headless-shell'].map(
    name => registry.findExecutable(name).executablePathOrDie('javascript'))));
} else if (process.argv[2] === 'launch') {
  (async () => {
    // The test suite defaults to headless_shell; also exercise full Chromium.
    for (const options of [{}, { channel: 'chromium' }]) {
      const browser = await chromium.launch({ ...options, headless: true, timeout: 15000 });
      try {
        const page = await browser.newPage();
        await page.setContent('<title>Docs browser ready</title><p>ready</p>');
        assert.equal(await page.title(), 'Docs browser ready');
        assert.equal(await page.locator('p').textContent(), 'ready');
        assert.equal(await page.evaluate(() => 6 * 7), 42);
      } finally { await browser.close(); }
    }
    console.log('Both locked Chromium executables launched and evaluated a page');
  })().catch(error => { console.error(error); process.exitCode = 1; });
} else { throw new Error('Expected paths or launch'); }
