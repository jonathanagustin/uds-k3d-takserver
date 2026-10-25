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

const hidden = ["takserver-api", "takserver-stream", "8443", "8446", "8089"];

async function signIn(page: Page, username: string, password: string) {
  const heading = page.getByRole("heading", { name: "Your Apps" });
  const userField = page.getByLabel("Username or email");
  await expect(heading.or(userField)).toBeVisible({ timeout: 60_000 });
  if (await userField.isVisible()) {
    await userField.fill(username);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign In" }).click();
  }
  await expect(heading).toBeVisible({ timeout: 90_000 });
}

async function packageTiles(page: Page): Promise<string[]> {
  const names = (await page.getByRole("link").allInnerTexts())
    .map((name) => name.replace(/\s+/g, " ").trim())
    .filter((name) => name.length > 0 && name !== "My Account");
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
    await signIn(page, outsider, outsiderPassword);
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
