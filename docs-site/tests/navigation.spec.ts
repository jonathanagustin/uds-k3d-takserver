// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { expect, test } from '@playwright/test';

test('the UDS-style groups keep the active reference visible and unrelated project pages collapsed', async ({ page }) => {
  await page.goto('configuration/');
  const sidebar = page.locator('.sidebar-content');
  const labels = await sidebar.locator('ul.top-level > li > details > summary').allTextContents();
  expect(labels.map((label) => label.trim())).toEqual([
    'Getting started', 'Concepts', 'How-to guides', 'Reference', 'Project',
  ]);
  const reference = sidebar.locator('details').filter({
    has: page.locator('summary').filter({ hasText: /^Reference$/ }),
  });
  await expect.poll(() => reference.evaluate((element) => element.hasAttribute('open'))).toBe(true);
  await expect(reference.getByRole('link', { name: 'TAK Server', exact: true })).toBeVisible();
  const project = sidebar.locator('details').filter({
    has: page.locator('summary').filter({ hasText: /^Project$/ }),
  });
  await expect.poll(() => project.evaluate((element) => element.hasAttribute('open'))).toBe(false);
  await project.locator('summary').first().click();
  await project.getByRole('link', { name: 'CI workflows', exact: true }).click();
  await expect(page).toHaveURL(/\/main\/ci\/$/);
  await expect(project.getByRole('link', { name: 'CI workflows', exact: true })).toBeVisible();
  await expect.poll(() => project.evaluate((element) => element.hasAttribute('open'))).toBe(true);
});

test('concepts and installation retain their routes and expand their own navigation group', async ({ page }) => {
  await page.goto('networking/');
  const sidebar = page.locator('.sidebar-content');
  const concepts = sidebar.locator('details').filter({
    has: page.locator('summary').filter({ hasText: /^Concepts$/ }),
  });
  await expect.poll(() => concepts.evaluate((element) => element.hasAttribute('open'))).toBe(true);
  await expect(concepts.getByRole('link', { name: 'Networking', exact: true })).toHaveAttribute('aria-current', 'page');
  // Navigation assertions do not depend on third-party README badge images.
  await page.goto('getting-started/', { waitUntil: 'domcontentloaded' });
  const gettingStarted = sidebar.locator('details').filter({
    has: page.locator('summary').filter({ hasText: /^Getting started$/ }),
  });
  await expect.poll(() => gettingStarted.evaluate((element) => element.hasAttribute('open'))).toBe(true);
  await expect(gettingStarted.getByRole('link', { name: 'Install and deploy', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('the search bar supports the keyboard shortcut and returns focus on Escape', async ({ page }) => {
  await page.goto('configuration/');
  const search = page.getByRole('button', { name: 'Search', exact: true });
  await search.focus();
  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: /Search main/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(search).toBeFocused();
});

for (const width of [320, 390]) {
  test(`navigation, search, and version selection fit a ${width}px screen`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('configuration/');
    await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(page.getByLabel('Documentation version').filter({ visible: true })).toBeVisible();
    await expect(page.locator('.sidebar-content').getByRole('link', { name: 'TAK Server', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`mobile-navigation-${width}.png`) });
  });
}
