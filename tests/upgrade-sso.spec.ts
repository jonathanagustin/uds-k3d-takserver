/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } });

// This contract is run explicitly before and after an upgrade.
test("upgrade preserves SSO access to the dashboard", async ({ page }) => {
  test.skip(process.env.UPGRADE_TEST !== "1", "Run by the upgrade test only");
  test.setTimeout(180_000);
  page.on("dialog", (dialog) => dialog.accept());
  const origin = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
  await page.goto(origin);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  await page
    .getByLabel("Username or email")
    .fill(process.env.KEYCLOAK_USER || "doug");
  await page
    .getByLabel("Password")
    .fill(process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.waitForURL(/\/Marti\//, { timeout: 90_000 });
  expect(new URL(page.url()).origin).toBe(new URL(origin).origin);
  await expect(page.getByRole("link", { name: "Documentation" })).toBeVisible();
  const response = await page.request.get(
    new URL("/Marti/api/util/isAdmin", origin).toString(),
  );
  expect(response.ok()).toBeTruthy();
  expect((await response.text()).trim()).toBe("true");
});
