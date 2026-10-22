/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// ATAK walkthrough for the demo video: atak.<domain> sends the browser to
// Keycloak, the Keycloak user lands on the phone view of the ATAK test
// device (ATAK-CIV in a KubeVirt VM), and a second tab shows the CloudTAK map
// on the same TAK Server, where TAK lists the device as a client.
// demo/record-web.sh runs it through demo/record-browser.sh after
// atak/ci/e2e.sh has deployed and connected the device.
import {
  caption,
  clickLikeAPerson,
  expect,
  expectSecure,
  mark,
  showCursor,
  start,
  test,
  typeLikeAPerson,
  watchSecurity,
} from "./browser";

const phoneUrl = process.env.ATAK_VIEWER_URL || "https://atak.uds.dev/phone.html";
const mapUrl = process.env.CLOUDTAK_URL || "https://map.uds.dev/";
const username = process.env.KEYCLOAK_USER || "takuser";
const password = process.env.KEYCLOAK_PASSWORD || "";
const device = process.env.ATAK_DEVICE_USER || "atak-device";
// The device's fixed test location (atak/ci/e2e.sh), National Mall, DC.
const testLocation = process.env.ATAK_TEST_LOCATION || "38.8895/-77.0353";

test("ATAK test device and CloudTAK through UDS Core SSO", async ({ page }) => {
  test.setTimeout(300_000);
  expect(password, "KEYCLOAK_PASSWORD is not set").not.toBe("");
  await watchSecurity(page);

  await page.goto(phoneUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await page.mouse.click(8, 200);
  start();
  await showCursor(page);
  await expectSecure(page);
  caption("The ATAK phone view redirects to Keycloak (UDS Core SSO)");
  await page.waitForTimeout(2_000);

  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await page.waitForTimeout(400);
  await clickLikeAPerson(page, page.getByLabel("Password"));
  await typeLikeAPerson(page, password);
  await page.waitForTimeout(500);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));

  await expect(page).toHaveURL(/phone\.html/, { timeout: 60_000 });
  await expect(page.locator(".screen iframe")).toBeVisible({ timeout: 30_000 });
  await showCursor(page);
  // ws-scrcpy needs a few seconds for the first frame.
  await page.waitForTimeout(8_000);
  await expectSecure(page);
  caption("ATAK-CIV built from source, on Android-x86 in a KubeVirt VM");
  await page.waitForTimeout(4_000);
  caption("Client certificate from a TAK data package, CoT on 8089 over mutual TLS");
  mark("zoom", "0.5,0.35,1.6");
  await page.waitForTimeout(5_000);

  // The same TAK Server from the browser map, in a second tab. Keycloak
  // already has a session, so there is no second sign-in.
  const map = await page.context().newPage();
  await watchSecurity(map);
  await map.goto(mapUrl);
  const canvas = map.locator("canvas.maplibregl-canvas");
  await expect(canvas).toBeVisible({ timeout: 120_000 });
  // CloudTAK opens its permissions prompt a moment after the map loads.
  await map
    .getByRole("button", { name: "Skip for now" })
    .waitFor({ state: "visible", timeout: 15_000 })
    .catch(() => undefined);
  for (let i = 0; i < 10; i++) {
    let open = false;
    for (const name of ["Not now", "Skip for now"]) {
      const skip = map.getByRole("button", { name });
      if (await skip.isVisible().catch(() => false)) {
        open = true;
        await clickLikeAPerson(map, skip).catch(() => undefined);
      }
    }
    if (!open) break;
    await map.waitForTimeout(800);
  }
  await expectSecure(map);
  caption("CloudTAK on the same TAK Server, signed in through the same Keycloak session");
  await expect
    .poll(
      async () =>
        await map.evaluate(async (user) => {
          const token = localStorage.getItem("CapacitorStorage.token");
          const res = await fetch("/api/marti/clients?secago=600", { headers: { Authorization: `Bearer ${token}` } });
          const body = res.ok ? await res.json() : { data: [] };
          return (body.data || []).some((c: { username?: string }) => c.username === user);
        }, device),
      { timeout: 90_000, intervals: [5_000] },
    )
    .toBe(true);
  caption("TAK lists the ATAK device as a connected client");
  await map.waitForTimeout(4_000);
  // CloudTAK replaces the URL hash with its own default view while it loads;
  // move the view to the test location afterwards (maplibre URL hash).
  await map.evaluate((loc) => {
    window.location.hash = `#15/${loc}`;
  }, testLocation);
  await map.waitForTimeout(3_000);
  caption("Its marker sits at a fixed TEST LOCATION on the National Mall, not a GPS fix");
  mark("zoom", "0.5,0.5,1.6");
  await map.waitForTimeout(6_000);

  await page.bringToFront();
  await showCursor(page);
  caption("Back on the phone: ATAK connected, self marker at the test location");
  await page.waitForTimeout(4_000);
});
