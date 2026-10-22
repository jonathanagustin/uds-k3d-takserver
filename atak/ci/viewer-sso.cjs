// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
//
// Opens the phone view through the tenant gateway, signs in on Keycloak,
// waits for the device stream and saves a screenshot. Fails when the screen
// area is blank.
const { chromium } = require("playwright");

(async () => {

const [url, user, pass, out] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ ignoreHTTPSErrors: true, viewport: { width: 560, height: 1000 } });
await page.goto(url, { waitUntil: "domcontentloaded" });
if (await page.locator("#username").count()) {
  await page.fill("#username", user);
  await page.fill("#password", pass);
  await Promise.all([page.waitForURL(/phone\.html/, { timeout: 60000 }), page.click("#kc-login")]);
}
await page.waitForTimeout(30000);
await page.screenshot({ path: out });
const shot = await page.locator(".screen").screenshot();
// A blank screen compresses to almost nothing; a live frame does not.
await browser.close();
if (shot.length < 20000) {
  console.error(`screen area looks blank (${shot.length} bytes)`);
  process.exit(1);
}
console.log(`viewer screenshot ${out}, screen area ${shot.length} bytes`);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
