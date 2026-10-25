/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test, type Page } from "@playwright/test";

// Slim CI runs every spec and does not install core-portal. The full-core
// task sets PORTAL_URL. My Account is the portal's own link, not a Package
// tile. core-monitoring exposes Grafana, which is not one of the two titles
// this check accepts.
const portalUrl = process.env.PORTAL_URL || "";
const adminUser = process.env.KEYCLOAK_USER || "doug";
const adminPassword = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";
const outsider = process.env.KEYCLOAK_OUTSIDER || "outsider";
const outsiderPassword = process.env.KEYCLOAK_OUTSIDER_PASSWORD || "outsider123!@#UN";
const shots = ".playwright/screenshots";

// The portal's left navigation is made of links too: My Account is its own
// link, and the Your Apps and Admin Apps sections are links in the sidebar.
const sidebar = new Set(["My Account", "Your Apps", "Admin Apps"]);

const hidden = ["takserver-api", "takserver-stream", "8443", "8446", "8089"];

// A user with no groups still signs in at Keycloak, but the portal renders no
// Your Apps page for that account (a blank page at /auth). allowEmpty accepts
// that: the account has to come back to the portal origin, and the caller then
// checks that no tile is shown.
async function signIn(page: Page, username: string, password: string, allowEmpty = false) {
  const heading = page.getByRole("heading", { name: "Your Apps" });
  const userField = page.getByLabel("Username or email");
  await expect(heading.or(userField)).toBeVisible({ timeout: 60_000 });
  if (await userField.isVisible()) {
    await userField.fill(username);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign In" }).click();
  }
  try {
    if (allowEmpty) {
      await page.waitForURL(`${portalUrl}/**`, { timeout: 90_000 });
      await heading.waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
      return;
    }
    await expect(heading).toBeVisible({ timeout: 90_000 });
  } catch {
    const text = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    await page.screenshot({ path: `${shots}/portal-${username}-signin.png`, fullPage: true }).catch(() => {});
    throw new Error(`${username} did not reach Your Apps at ${page.url()}: ${text.slice(0, 500)}`);
  }
}

async function packageTiles(page: Page): Promise<string[]> {
  const names = (await page.getByRole("link").allInnerTexts())
    .map((name) => name.replace(/\s+/g, " ").trim())
    .filter((name) => name.length > 0 && !sidebar.has(name));
  return [...new Set(names)].sort();
}

test.describe("portal tiles", () => {
  test.skip(!portalUrl, "PORTAL_URL is not set");

  test("the admin sees the TAK Server and CloudTAK tiles", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto(portalUrl);
    await signIn(page, adminUser, adminPassword);
    const names = await packageTiles(page);
    await page.screenshot({ path: `${shots}/portal-admin.png`, fullPage: true });
    expect(names, "Package tiles besides My Account").toEqual(["CloudTAK", "TAK Server"]);
    for (const marker of hidden) {
      expect(names.join("\n"), marker).not.toContain(marker);
    }
  });

  test("a user outside the admin group sees neither tile", async ({ browser }) => {
    test.setTimeout(180_000);
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      storageState: { cookies: [], origins: [] },
    });
    const page = await context.newPage();
    await page.goto(portalUrl);
    await signIn(page, outsider, outsiderPassword, true);
    const names = await packageTiles(page);
    await page.screenshot({ path: `${shots}/portal-outsider.png`, fullPage: true });
    expect(names).not.toContain("TAK Server");
    expect(names).not.toContain("CloudTAK");
    for (const marker of hidden) {
      expect(names.join("\n"), marker).not.toContain(marker);
    }
    await context.close();
  });
});
