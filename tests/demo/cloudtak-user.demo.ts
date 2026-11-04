/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// A regular user signs in to CloudTAK, and the TAK Server web UI still says
// no. demo/record-web.sh creates the user with DEMO_KEYCLOAK_GROUPS
// "/CloudTAK/Users,/TAK/Operators_READ": CloudTAK's Keycloak client lets
// /CloudTAK/Users in, and TAK's client allows only /UDS Core/Admin (see
// docs/cloudtak.md#who-can-sign-in). The password is generated for the run
// and the login form masks it.
import {
  caption,
  clickLikeAPerson,
  cloudtakReady,
  expect,
  expectSecure,
  mark,
  showCursor,
  start,
  still,
  test,
  typeLikeAPerson,
  watchSecurity,
} from "./browser";

const mapUrl = process.env.CLOUDTAK_URL || "https://map.uds.dev/";
const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const username = process.env.KEYCLOAK_USER || "mapdemo";
const password = process.env.KEYCLOAK_PASSWORD || "";

test("A regular user signs in to CloudTAK, not to TAK's admin UI", async ({ page }) => {
  test.setTimeout(300_000);
  expect(password, "KEYCLOAK_PASSWORD is not set").not.toBe("");
  await watchSecurity(page);

  await page.goto(mapUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await page.mouse.click(8, 200);
  start();
  await showCursor(page);
  await expectSecure(page);
  caption("A regular user, in /CloudTAK/Users and not an admin, opens CloudTAK");
  await page.waitForTimeout(1_500);
  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await clickLikeAPerson(page, page.getByLabel("Password"));
  await typeLikeAPerson(page, password);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));

  await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 120_000 });
  await cloudtakReady(page, "MAP-USER");
  await expectSecure(page);
  const access = await page.evaluate(async () => {
    const token = localStorage.getItem("CapacitorStorage.token");
    const res = await fetch("/api/login", { headers: { Authorization: `Bearer ${token}` } });
    return res.ok ? ((await res.json()).access as string) : "";
  });
  expect(access, "CloudTAK access level").toBe("user");
  caption("Signed in to CloudTAK with user access: the map and chat, no server settings");
  mark("zoom", "0.5,0.5,1.3");
  await page.waitForTimeout(5_000);

  // Keycloak already has a session, so TAK's sign-in goes straight to the
  // group check and stops there.
  await page.goto(takUrl);
  await expect
    .poll(async () => `${page.url()}\n${await page.locator("body").innerText()}`, { timeout: 45_000 })
    .toMatch(/access.denied|not authorized|required group|do not have|don't have|permission/i);
  expect(page.url()).not.toMatch(/\/Marti\//);
  await showCursor(page);
  caption("The same account at TAK's admin web UI: Keycloak refuses it");
  await page.waitForTimeout(1_000);
  await still(page, "tak-admin-refused");
  await page.waitForTimeout(3_500);
});
