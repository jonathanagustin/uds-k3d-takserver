// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Wheel events sent before the MapLibre canvas has a real layout are dropped.
// After a pod restart the canvas can be visible, and the first tiles can
// already be on screen, while it is still too small or unfocused to zoom.
// Click the center and wheel only once it is large enough.

export async function zoomMap(page, canvas) {
    await canvas.waitFor({ state: "visible", timeout: 30_000 });
    await page.waitForFunction(() => {
        const el = document.querySelector("canvas.maplibregl-canvas");
        if (!el) return false;
        const box = el.getBoundingClientRect();
        return box.width > 100 && box.height > 100;
    }, undefined, { timeout: 30_000 });
    const box = await canvas.boundingBox();
    if (!box || box.width <= 100 || box.height <= 100) {
        throw new Error("map canvas is not large enough to zoom");
    }
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.click(x, y);
    for (let i = 0; i < 4; i++) {
        await page.mouse.move(x, y);
        await page.mouse.wheel(0, -600);
        await page.waitForTimeout(200);
    }
}
