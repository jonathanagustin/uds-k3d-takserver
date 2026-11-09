// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { expect, test } from '@playwright/test';

test('desktop search opens above the fold and centered in the viewport after scrolling', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('configuration/');
  await page.evaluate(() => window.scrollTo(0, 900));
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThan(0);
  expect(Math.abs(box.x + box.width / 2 - 720)).toBeLessThan(2);
  expect(box.y).toBeGreaterThan(0);
  expect(box.y).toBeLessThan(300);
  expect(box.y + box.height).toBeLessThanOrEqual(900);
  await page.screenshot({ path: testInfo.outputPath('desktop-search-position.png') });
  // Panel padding is not the backdrop.
  await page.mouse.click(box.x + box.width / 2, box.y + 2);
  await expect(dialog).toBeVisible();
  await page.mouse.click(box.x - 10, box.y + 10);
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeFocused();
});

for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
  test(`search stays usable with long results at ${viewport.width}×${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('configuration/');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('textbox').fill('backup');
    await expect(dialog.locator('.pagefind-ui__result').first()).toBeVisible();
    await expect(dialog.getByRole('checkbox')).toHaveCount(0);
    const box = (await dialog.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    if (viewport.width < 800) {
      expect(box.x).toBe(0);
      expect(box.y).toBe(0);
      expect(box.width).toBe(viewport.width);
      expect(box.height).toBe(viewport.height);
    }
    const results = dialog.locator('.search-results');
    expect(await results.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
    await results.evaluate((element) => { element.scrollTop = element.scrollHeight; });
    await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath('search-results-scroll.png') });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(dialog).not.toBeVisible();
  });
}
