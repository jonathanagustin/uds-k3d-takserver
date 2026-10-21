/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Web UI walkthrough for the demo video: Keycloak SSO through UDS Core,
// then the TAK admin pages, in a real Chrome window. The waits and mouse
// paths are for the viewer. demo/record-web.sh runs it through
// demo/record-browser.sh.
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
  visit,
  watchSecurity,
} from "./browser";

const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
// demo/record-web.sh creates takuser and passes a password generated for
// the run. There is no default password.
const username = process.env.KEYCLOAK_USER || "takuser";
const password = process.env.KEYCLOAK_PASSWORD || "";

test("TAK web UI through UDS Core SSO", async ({ page }) => {
  test.setTimeout(300_000);
  expect(password, "KEYCLOAK_PASSWORD is not set").not.toBe("");
  await watchSecurity(page);

  // The video starts on the Keycloak page TAK redirects to, not on the
  // empty first tab.
  await page.goto(takUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  start();
  await showCursor(page);
  await expectSecure(page);
  caption("TAK redirects to Keycloak (UDS Core SSO)");
  await page.waitForTimeout(2_000);
  caption("Sign in with a demo Keycloak account");

  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await page.waitForTimeout(400);
  const passwordField = page.getByLabel("Password");
  await clickLikeAPerson(page, passwordField);
  await typeLikeAPerson(page, password);
  await page.waitForTimeout(500);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));

  // /UDS Core/Admin maps to ROLE_ADMIN, so TAK opens the Marti admin UI.
  // The landing page keeps polling metrics, so networkidle never settles.
  await page.waitForURL(/\/Marti\//, { timeout: 90_000 });
  await page.waitForLoadState("load");
  await page.waitForTimeout(1_500);
  await showCursor(page);
  await expectSecure(page);
  caption("Signed in to TAK with a Keycloak account: server monitor");
  mark("zoom", "0.5,0.35,1.3");
  await page.waitForTimeout(4_000);

  await visit(page, new URL("/Marti/inputs/index.html", takUrl).toString(), "Inputs and data feeds");
  await visit(page, new URL("/Marti/security/index.html", takUrl).toString(), "Security and authentication");
});
