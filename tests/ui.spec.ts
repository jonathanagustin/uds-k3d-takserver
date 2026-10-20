/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

test("Marti admin UI is served through the passthrough gateway", async ({ page }) => {
  // 8443 requires the admin client certificate. A trusted cert skips the
  // login form and opens the Marti admin shell.
  const url = process.env.TAK_CERT_URL || "https://takserver-api.uds.dev/";
  page.once("dialog", (dialog) => dialog.accept());
  const response = await page.goto(url);
  expect(response, "no response from the TAK web host").not.toBeNull();
  expect(response!.status()).toBeLessThan(500);
  await expect(page).toHaveURL(/\/Marti\//);
  await expect(page.getByRole("link", { name: "Documentation" })).toBeVisible();
});
