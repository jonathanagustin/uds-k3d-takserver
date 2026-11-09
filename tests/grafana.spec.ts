/**
 * Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

// Slim CI runs every spec and does not install Grafana. tests/grafana-alerts.sh
// sets GRAFANA_URL on the full-core cluster.
const grafanaUrl = process.env.GRAFANA_URL || "";
const user = process.env.GRAFANA_USER || "";
const password = process.env.GRAFANA_PASSWORD || "";

test.describe("TAK Grafana dashboard", () => {
  test.skip(!grafanaUrl, "GRAFANA_URL is unset");
  // The port-forward goes straight to Grafana, and Grafana sends a browser
  // without a session to the Keycloak sign-in. Basic auth with the admin
  // Secret is what tests/grafana-alerts.sh already uses for the API, so the
  // page loads without a form. Only 127.0.0.1 is visited.
  if (user) {
    test.use({
      extraHTTPHeaders: {
        Authorization: `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`,
      },
    });
  }

  test("screenshot with live series", async ({ page }) => {
    await page.goto(grafanaUrl, { waitUntil: "domcontentloaded" });
    const userField = page.getByLabel("Username").or(page.locator("input[name='user']"));
    if (await userField.isVisible().catch(() => false)) {
      await userField.fill(user);
      await page.getByLabel("Password").or(page.locator("input[name='password']")).fill(password);
      await page.getByRole("button", { name: /^(log in|sign in)$/i }).click();
    }
    await expect(page.getByText("Container memory")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Postgres ready")).toBeVisible();
    await expect(page.getByText("Pod restarts")).toBeVisible();
    await page.screenshot({
      path: ".playwright/screenshots/tak-dashboard.png",
      fullPage: true,
    });
  });
});
