/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// CloudTAK walkthrough for the demo video: map.<domain> sends the browser to
// Keycloak, and the Keycloak user lands on the CloudTAK map with the
// OpenStreetMap basemap and a live TAK connection. demo/record-web.sh runs
// it through demo/record-browser.sh.
import {
  caption,
  clickLikeAPerson,
  expect,
  expectSecure,
  glideTo,
  mark,
  showCursor,
  start,
  test,
  typeLikeAPerson,
  watchSecurity,
} from "./browser";

const mapUrl = process.env.CLOUDTAK_URL || "https://map.uds.dev/";
// demo/record-web.sh creates takuser and passes a password generated for
// the run. There is no default password.
const username = process.env.KEYCLOAK_USER || "takuser";
const password = process.env.KEYCLOAK_PASSWORD || "";

test("CloudTAK map through UDS Core SSO", async ({ page }) => {
  test.setTimeout(300_000);
  expect(password, "KEYCLOAK_PASSWORD is not set").not.toBe("");
  await watchSecurity(page);

  let tiles = 0;
  page.on("response", (res) => {
    if (res.url().includes("/uds-basemap/tiles/") && res.status() === 200) tiles++;
  });

  await page.goto(mapUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await page.mouse.click(8, 200);
  start();
  await showCursor(page);
  await expectSecure(page);
  caption("The CloudTAK map redirects to Keycloak (UDS Core SSO)");
  await page.waitForTimeout(2_000);

  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await page.waitForTimeout(400);
  const passwordField = page.getByLabel("Password");
  await clickLikeAPerson(page, passwordField);
  await typeLikeAPerson(page, password);
  await page.waitForTimeout(500);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));

  const canvas = page.locator("canvas.maplibregl-canvas");
  await expect(canvas).toBeVisible({ timeout: 120_000 });
  await showCursor(page);

  // First sign-in: CloudTAK asks for a callsign.
  const welcome = page.getByText("Welcome to CloudTAK");
  if (await welcome.waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false)) {
    caption("First sign-in: pick a callsign");
    const callsign = page.getByPlaceholder("Enter your callsign");
    await clickLikeAPerson(page, callsign);
    await typeLikeAPerson(page, username);
    await page.waitForTimeout(500);
    await clickLikeAPerson(page, page.getByRole("button", { name: "Get Started" }));
    for (let i = 0; i < 10; i++) {
      let open = false;
      for (const name of ["Not now", "Skip for now"]) {
        const skip = page.getByRole("button", { name });
        if (await skip.isVisible().catch(() => false)) {
          open = true;
          await clickLikeAPerson(page, skip).catch(() => undefined);
        }
      }
      if (!open && !(await welcome.isVisible().catch(() => false))) break;
      await page.waitForTimeout(800);
    }
  }

  await expect.poll(() => tiles, { timeout: 60_000 }).toBeGreaterThan(3);
  await page.waitForTimeout(2_500);
  await expectSecure(page);
  caption("Signed in with Keycloak: CloudTAK with an OpenStreetMap basemap");
  await page.waitForTimeout(3_000);
  // The attribution, bottom right.
  mark("zoom", "0.88,0.95,1.8");
  await page.waitForTimeout(3_000);

  // Zoom in with the wheel, as a user would. Tiles come through the tile
  // proxy in the CloudTAK pod.
  caption("Tiles through a caching proxy in the pod, egress to one tile host");
  await glideTo(page, canvas);
  for (let i = 0; i < 5; i++) {
    await page.mouse.wheel(0, -400);
    await page.waitForTimeout(700);
  }
  await page.waitForTimeout(4_000);

  // TAK lists the map's own streaming connection as a client.
  await expect
    .poll(
      async () =>
        await page.evaluate(async (user) => {
          const token = localStorage.getItem("CapacitorStorage.token");
          const res = await fetch("/api/marti/clients?secago=600", { headers: { Authorization: `Bearer ${token}` } });
          const body = res.ok ? await res.json() : { data: [] };
          return (body.data || []).some((c: { username?: string }) => c.username === user);
        }, username),
      { timeout: 90_000, intervals: [5_000] },
    )
    .toBe(true);
  caption("Connected to TAK Server as the Keycloak user");
  await page.waitForTimeout(4_000);
});
