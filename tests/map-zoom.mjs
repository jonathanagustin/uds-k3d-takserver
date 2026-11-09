// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// CloudTAK's desktop map exposes this control after map/profile loading.
// Locator.click waits for it to be visible and receive pointer events. Raw
// coordinates over a visible canvas do not establish that the map is usable.
export async function zoomMap(page, canvas) {
    await canvas.waitFor({ state: 'visible', timeout: 30_000 });
    await page.getByTitle('Zoom In Button', { exact: true }).click({ timeout: 30_000 });
}

// Callsign configuration lives on the server, while a browser permission
// dismissal lives in localStorage. A fresh browser can therefore show this
// dialog for a returning user without ever showing the welcome step.
export async function dismissMapPermissions(page) {
    await page.getByText('Welcome to CloudTAK', { exact: true }).waitFor({ state: 'hidden', timeout: 30_000 });
    await page.getByTitle('Zoom In Button', { exact: true }).waitFor({ state: 'visible', timeout: 30_000 });
    const disclosure = page.getByRole('dialog').filter({ has: page.getByText('Location access', { exact: true }) });
    if (await disclosure.isVisible()) {
        await disclosure.getByRole('button', { name: 'Not now', exact: true }).click();
        await disclosure.waitFor({ state: 'hidden', timeout: 30_000 });
    }
    const permissions = page.getByRole('dialog').filter({ has: page.getByText('Permissions', { exact: true }) });
    if (await permissions.isVisible()) {
        await permissions.getByRole('button', { name: 'Skip for now', exact: true }).click();
        await permissions.waitFor({ state: 'hidden', timeout: 30_000 });
    }
    // Unknown dialogs remain a failure; never click through or remove them.
    if (await page.getByRole('dialog').isVisible()) {
        throw new Error('Unexpected CloudTAK dialog blocks map interaction');
    }
}
