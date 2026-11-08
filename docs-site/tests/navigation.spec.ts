// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { expect, test } from '@playwright/test';

test('the active guide remains visible while unrelated sections start collapsed', async ({ page }) => {
  await page.goto('configuration/');
  const sidebar = page.locator('.sidebar-content');
  await expect(sidebar.getByRole('link', { name: 'TAK Server', exact: true })).toBeVisible();
  const operations = sidebar.locator('details').filter({
    has: page.locator('summary').filter({ hasText: /^Operations$/ }),
  });
  await expect.poll(() => operations.evaluate((element) => element.hasAttribute('open'))).toBe(false);
  await operations.locator('summary').click();
  await sidebar.getByRole('link', { name: 'CI workflows', exact: true }).click();
  await expect(page).toHaveURL(/\/main\/ci\/$/);
  await expect(sidebar.getByRole('link', { name: 'CI workflows', exact: true })).toBeVisible();
  await expect.poll(() => operations.evaluate((element) => element.hasAttribute('open'))).toBe(true);
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
