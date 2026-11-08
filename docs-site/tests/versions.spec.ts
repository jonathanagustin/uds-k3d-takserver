// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { expect, test } from '@playwright/test';
import versions from '../src/generated/versions.json' with { type: 'json' };

const base = '/uds-takserver/';

test('released root and unreleased main show the correct sources and retain the selected page', async ({ page }, testInfo) => {
  await page.goto(`${base}data/`);
  await expect(page.locator('[data-docs-version]')).toHaveAttribute('data-docs-version', versions[0].id);
  await expect(page.getByText('You are reading unreleased main documentation.', { exact: false })).toHaveCount(0);
  await expect(page.locator(`a[href$="blob/${versions[0].ref}/docs/data.md"]`)).toBeVisible();
  await page.getByLabel('Documentation version').first().selectOption(`${base}main/data/`);
  await expect(page).toHaveURL(`${base}main/data/`);
  await expect(page.locator('.sl-banner')).toContainText('unreleased main documentation');
  await expect(page.locator('a[href$="edit/main/docs/data.md"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('versioned-docs-main.png') });
});

test('the version selector remains reachable in the mobile menu', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}main/data/`);
  await page.getByRole('button', { name: 'Menu', exact: true }).click();
  const selector = page.getByLabel('Documentation version').filter({ visible: true });
  await expect(selector).toBeVisible();
  await selector.selectOption(`${base}data/`);
  await expect(page).toHaveURL(`${base}data/`);
});

test('a page absent from a release falls back to that release home', async ({ page }) => {
  const missing = versions.find((version) => version.id !== 'main' && !version.pages.includes('how-to/backup-and-restore'));
  test.skip(!missing, 'All retained releases already contain this guide. Unit tests still cover absent-page fallback.');
  const target = `${base}${missing!.prefix ? missing!.prefix + '/' : ''}`;
  await page.goto(`${base}main/how-to/backup-and-restore/`);
  const selector = page.getByLabel('Documentation version').first();
  await selector.selectOption(target);
  await expect(page).toHaveURL(new RegExp(`${target}$`));
  await expect(page.getByRole('heading', { level: 1, name: 'TAK Server on UDS' })).toBeVisible();
});

for (const version of versions) {
  test(`search stays within ${version.label}`, async ({ page }) => {
    const prefix = `${base}${version.prefix ? version.prefix + '/' : ''}`;
    await page.goto(`${prefix}data/`);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const search = dialog.getByRole('textbox');
    await search.fill('Postgres');
    const results = dialog.locator('.pagefind-ui__result-link');
    await expect(results.first()).toBeVisible({ timeout: 15_000 });
    const links = await results.evaluateAll((elements) => elements.map((element) => (element as HTMLAnchorElement).pathname));
    expect(links.length).toBeGreaterThan(0);
    for (const href of links) {
      if (version.prefix) expect(href).toMatch(new RegExp(`^${prefix}`));
      else expect(href).not.toMatch(new RegExp(`^${base}(?:main|v\\d+-\\d+)/`));
    }
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
  });
}
