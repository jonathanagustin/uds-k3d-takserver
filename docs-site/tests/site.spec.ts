// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { expect, test, type APIResponse, type Page } from '@playwright/test';

// Current-feature checks use /main/; version-channel behavior is tested separately.

async function head(page: Page, path: string): Promise<APIResponse> {
  return page.request.fetch(path, { method: 'HEAD' });
}

test('home page links the four tasks and the theme toggle changes the document', async ({ page }) => {
  await page.goto('');
  await expect(page.getByRole('heading', { level: 1, name: 'TAK Server on UDS' })).toBeVisible();
  await expect(page.locator('.hero .tagline')).toHaveText('All-in-one solution for packaging, deploying, and operating TAK Server');
  await expect(page.locator('.hero .actions')).toHaveCount(0);
  await expect(page.locator('.hero .project-wordmark')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Deploy', exact: true })).toHaveAttribute(
    'href',
    '/uds-takserver/main/getting-started/#deploy-a-release',
  );
  await expect(page.getByRole('link', { name: 'Upgrade', exact: true })).toHaveAttribute(
    'href',
    '/uds-takserver/main/getting-started/#upgrade-from-06',
  );
  await expect(page.getByRole('link', { name: 'Back up', exact: true })).toHaveAttribute(
    'href',
    '/uds-takserver/main/data/#backup',
  );
  await expect(page.getByRole('link', { name: 'Reference', exact: true })).toHaveAttribute(
    'href',
    '/uds-takserver/main/getting-started/#documentation',
  );

  const theme = page.getByLabel('Select theme').first();
  await theme.selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await theme.selectOption('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('the preview anchor stays on home and reaches its inline player', async ({ page, baseURL }) => {
  for (const hash of ['#ui-preview', '#ui%2Dpreview']) {
    await page.goto('about:blank');
    await page.goto(hash, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(new URL(hash, baseURL).href);
    const preview = page.locator('#ui-preview');
    await expect(preview).toBeVisible();
    await expect(preview.locator('video')).toHaveAttribute('controls', '');
    await expect(preview.locator('video')).toHaveAttribute('preload', 'none');
  }
});

test('an old home-page anchor opens that section on Getting started', async ({ page }) => {
  // The README includes third-party badges; they do not gate local content.
  await page.goto('#quick-start', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/\/getting-started\/#quick-start$/);
  await expect(page.getByRole('heading', { level: 3, name: 'Quick start' })).toBeVisible();
});

test('an unknown page is a 404 with a link home', async ({ page }) => {
  const response = await page.goto('this-page-does-not-exist/');
  expect(response?.status()).toBe(404);
  await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible();
  await expect(page.getByText('will not be included in production')).toHaveCount(0);
  const home = page.getByRole('link', { name: 'home page', exact: true });
  await expect(home).toHaveAttribute('href', '/uds-takserver/');
  await home.click();
  await expect(page.getByRole('heading', { level: 1, name: 'TAK Server on UDS' })).toBeVisible();
});

test('Getting started serves the demo videos without preloading them', async ({ page }) => {
  await page.goto('getting-started/', { waitUntil: 'domcontentloaded' });
  const videos = page.locator('video');
  expect(await videos.count()).toBeGreaterThanOrEqual(2);

  const sources = await videos.locator('source').evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('src')),
  );
  expect(sources.length).toBeGreaterThanOrEqual(2);

  for (const source of sources) {
    expect(source, 'video source').toMatch(/\.mp4$/);
    const response = await head(page, source!);
    expect(response.status(), source!).toBe(200);
    expect(response.headers()['content-type'] ?? '', source!).toContain('video/');
    const length = Number(response.headers()['content-length'] ?? '0');
    expect(length, source!).toBeGreaterThan(100_000);
  }

  const preloads = await videos.evaluateAll((elements) =>
    elements.map((element) => element.getAttribute('preload')),
  );
  expect(preloads.every((value) => value === 'none')).toBe(true);
});

test('architecture diagrams render their labels', async ({ page }) => {
  await page.goto('getting-started/#architecture', { waitUntil: 'domcontentloaded' });
  const diagrams = page.locator('pre.mermaid svg');
  await expect(diagrams).toHaveCount(2, { timeout: 15_000 });
  await expect(diagrams.first()).toContainText('Browser');
  await expect(diagrams.nth(1)).toContainText('Public source');
});

test('YAML examples show the file title', async ({ page }) => {
  await page.goto('profiles/');
  const title = (name: string) => page.locator('.expressive-code figure.has-title .title', { hasText: name });
  await expect(title('uds-bundle.yaml')).toBeVisible();
  await expect(title('uds-config.yaml')).toBeVisible();

  await page.goto('configuration/');
  await expect(title('values.yaml')).toBeVisible();

  await page.goto('data/');
  await expect(title('uds-config.yaml')).toBeVisible();
});

test('llms.txt lists the guides', async ({ page }) => {
  const listing = await page.request.get('/uds-takserver/llms.txt');
  expect(listing.status()).toBe(200);
  const text = await listing.text();
  expect(text).toContain('# TAK Server on UDS');
  expect(text).toContain('llms-full.txt');

  const full = await head(page, '/uds-takserver/llms-full.txt');
  expect(full.status()).toBe(200);
  expect(full.headers()['content-type'] ?? '').toContain('text/plain');
  const fullBody = await (await page.request.get('/uds-takserver/llms-full.txt')).text();
  expect(fullBody).toContain('Quick start');
  expect(fullBody).toContain('Deploy a release');
});

test('deployment choices support keyboard selection and link to the current channel', async ({ page }) => {
  await page.goto('');
  const cluster = page.getByRole('tab', { name: 'Existing UDS Core cluster', exact: true });
  const local = page.getByRole('tab', { name: 'Local test environment', exact: true });
  await cluster.focus();
  await page.keyboard.press('ArrowRight');
  await expect(local).toBeFocused();
  await expect(local).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tabpanel').getByRole('link', { name: 'Quick start', exact: true }))
    .toHaveAttribute('href', /\/main\/getting-started\/#quick-start$/);
  await page.keyboard.press('ArrowLeft');
  await expect(cluster).toBeFocused();
  await expect(cluster).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tabpanel').getByRole('link', { name: 'Deploy a release', exact: true }))
    .toHaveAttribute('href', /\/main\/getting-started\/#deploy-a-release$/);
});
