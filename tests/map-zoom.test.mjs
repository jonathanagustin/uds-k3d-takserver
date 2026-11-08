// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';
import { zoomMap } from './map-zoom.mjs';

const require = createRequire(new URL('./package.json', import.meta.url));
const { chromium } = require('@playwright/test');

async function launch() {
  try {
    return await chromium.launch();
  } catch {
    return await chromium.launch({ channel: 'chrome' });
  }
}

test('wheels before the canvas is ready do not zoom, and a later gesture does', async () => {
  const browser = await launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
  try {
    await page.goto(new URL('./fixtures/map-zoom.html', import.meta.url).href);
    const canvas = page.locator('canvas.maplibregl-canvas');
    await canvas.waitFor({ state: 'visible' });
    const early = await canvas.boundingBox();
    assert.ok(early && early.width < 100);
    await page.mouse.move(early.x + 1, early.y + 1);
    for (let i = 0; i < 4; i++) await page.mouse.wheel(0, -600);
    await page.waitForTimeout(800);
    assert.equal(await page.evaluate(() => window.mapZoom()), 5);
    await zoomMap(page, canvas);
    assert.ok(await page.evaluate(() => window.mapZoom()) > 5);
    assert.equal(await page.evaluate(() => window.clicked), true);
  } finally {
    await browser.close();
  }
});
