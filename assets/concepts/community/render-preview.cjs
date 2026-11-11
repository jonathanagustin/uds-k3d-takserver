// Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only
// Render the hand-authored SVGs with a fresh, isolated Chromium profile.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const types = { '.svg': 'image/svg+xml', '.html': 'text/html', '.png': 'image/png' };

(async () => {
  const server = http.createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      const filename = path.resolve(root, '.' + pathname);
      if (!filename.startsWith(root + path.sep)) throw new Error('Outside preview root');
      const data = await fs.readFile(filename);
      response.writeHead(200, { 'Content-Type': types[path.extname(filename)] || 'application/octet-stream' });
      response.end(data);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({
      executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
    const base = `http://127.0.0.1:${server.address().port}/assets/concepts/community/`;
    const failures = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('response', response => { if (response.status() >= 400 && !response.url().endsWith('/favicon.ico')) failures.push(response.url()); });
    await page.goto(base + 'index.html');
    await page.screenshot({ path: path.join(__dirname, 'usage-proof.png'), fullPage: true });
    for (const [name, height] of [['review-sheet', 996], ['wordmark-sheet', 640]]) {
      await page.goto(base + name + '.svg');
      await page.screenshot({ path: path.join(__dirname, name + '.png'), clip: { x: 0, y: 0, width: 1440, height } });
    }
    for (const name of ['stack-relay', 'trail-relay']) {
      for (const theme of ['light', 'dark', 'mono', 'indigo']) {
        for (const size of [16, 24, 32]) {
          await page.setViewportSize({ width: size, height: size });
          await page.goto(base + name + '-' + theme + '.svg');
          await page.locator('svg').evaluate((svg, size) => {
            svg.setAttribute('width', size);
            svg.setAttribute('height', size);
          }, size);
          await page.screenshot({ path: path.join(__dirname, 'favicon-proof', `${name}-${theme}-${size}.png`), omitBackground: true });
        }
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + 'index.html');
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) failures.push('Mobile horizontal overflow');
    if (failures.length) throw new Error(failures.join('\n'));
    console.log('Rendered overview, wordmarks, usage proof and 24 exact-size transparent favicon PNGs; mobile layout has no horizontal overflow.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
