// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// CloudTAK's desktop map exposes this control after map/profile loading.
// Locator.click waits for it to be visible and receive pointer events. Raw
// coordinates over a visible canvas do not establish that the map is usable.
export async function zoomMap(page, canvas) {
    await canvas.waitFor({ state: 'visible', timeout: 30_000 });
    await page.getByTitle('Zoom In Button', { exact: true }).click({ timeout: 30_000 });
}
