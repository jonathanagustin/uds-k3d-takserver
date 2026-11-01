/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test, type Page } from "@playwright/test";

// A user in no Keycloak group. Both clients set groups.anyOf to
// /UDS Core/Admin, so this sign-in must stop on Keycloak's denial.
test.use({ storageState: { cookies: [], origins: [] } });

const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const cloudtakUrl = process.env.CLOUDTAK_URL || "";
const username = process.env.KEYCLOAK_OUTSIDER || "outsider";
const password = process.env.KEYCLOAK_OUTSIDER_PASSWORD || "outsider123!@#UN";

async function signIn(page: Page, url: string) {
  await page.goto(url);
  await page.waitForURL(/sso\.uds\.dev/, { timeout: 60_000 });
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
}

async function expectDenied(page: Page) {
  await expect
    .poll(async () => `${page.url()}\n${await page.locator("body").innerText()}`, { timeout: 45_000 })
    .toMatch(/access.denied|not authorized|required group|do not have|don't have|permission/i);
  expect(page.url()).not.toMatch(/\/Marti\//);
  await expect(page.locator("canvas.maplibregl-canvas")).toHaveCount(0);
}

test("a user outside the allowed group is denied for TAK", async ({ page }) => {
  test.skip(process.env.SKIP_SSO_SETUP === "1", "Keycloak is not reachable");
  test.setTimeout(180_000);
  await signIn(page, takUrl);
  await expectDenied(page);
});

test("a user outside the allowed group is denied for CloudTAK", async ({ page }) => {
  test.skip(process.env.SKIP_SSO_SETUP === "1", "Keycloak is not reachable");
  test.skip(!cloudtakUrl, "CLOUDTAK_URL is not set");
  test.setTimeout(180_000);
  await signIn(page, cloudtakUrl);
  await expectDenied(page);
});
