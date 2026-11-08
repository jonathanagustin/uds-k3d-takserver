// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { dismissMapPermissions, zoomMap } from './map-zoom.mjs';

const require = createRequire(new URL('./package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const root = fileURLToPath(new URL('.', import.meta.url));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6epkAAAAASUVORK5CYII=', 'base64');

function serve() {
  return http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    if (/^\/uds-basemap\/tiles\/\d+\/\d+\/\d+$/.test(pathname)) {
      res.writeHead(200, { 'Content-Type': 'image/png' });
      return res.end(png);
    }
    const relative = pathname === '/' ? 'fixtures/map-zoom.html' : pathname.slice(1);
    const file = path.resolve(root, relative);
    if (!file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404);
      return res.end();
    }
    const type = file.endsWith('.mjs') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    res.writeHead(200, { 'Content-Type': type });
    fs.createReadStream(file).pipe(res);
  });
}

async function checkZoom(mode = '', probeBlocked = false) {
  const server = serve();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
  const tiles = [];
  page.on('response', response => {
    const match = /\/uds-basemap\/tiles\/(\d+)\/\d+\/\d+$/.exec(response.url());
    if (match && response.status() === 200) tiles.push(Number(match[1]));
  });
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/${mode ? '?' + mode : ''}`);
    await expect.poll(() => tiles.length, { timeout: 15_000 }).toBeGreaterThan(3);
    await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible();
    await expect(page.locator('#loading')).toBeVisible();
    const before = Math.max(...tiles);
    assert.equal(await page.evaluate(() => localStorage.getItem('cloudtak-permissions-dismissed')), null);
    if (probeBlocked || mode === 'unknown') {
      await expect(page.getByTitle('Zoom In Button', { exact: true })).toBeVisible();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.getByText('Welcome to CloudTAK', { exact: true })).toHaveCount(0);
      if (probeBlocked) {
        await assert.rejects(page.getByTitle('Zoom In Button', { exact: true }).click({ timeout: 500 }),
          error => error.message.includes('intercepts pointer events'));
      }
    }
    if (mode === 'unknown') {
      await assert.rejects(dismissMapPermissions(page), /Unexpected CloudTAK dialog/);
      await expect(page.getByRole('dialog')).toBeVisible();
      return;
    }
    await dismissMapPermissions(page);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    if (mode) assert.equal(await page.evaluate(() => localStorage.getItem('cloudtak-permissions-dismissed')), 'true');
    await zoomMap(page, page.locator('canvas.maplibregl-canvas'));
    await expect.poll(() => Math.max(...tiles), { timeout: 10_000 }).toBeGreaterThan(before);
    assert.ok(tiles.some(zoom => zoom > before));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

test('visible CloudTAK zoom control requests higher tiles from pinned MapLibre', async () => {
  await checkZoom();
});

test('returning users dismiss permissions in a fresh browser before zooming', async () => {
  await checkZoom('permissions', true);
});

test('delayed returning-user permissions are handled after map/profile loading', async () => {
  await checkZoom('permissions');
});

test('unknown warning dialogs are not dismissed even with a skip button', async () => {
  await checkZoom('unknown');
});

test('location disclosure is declined before skipping permissions', async () => {
  await checkZoom('disclosure');
});
