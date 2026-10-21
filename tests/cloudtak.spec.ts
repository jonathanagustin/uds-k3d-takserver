/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

// CloudTAK on map.<domain>. Authservice sends the browser to Keycloak first.
// After the Keycloak sign-in, CloudTAK shows its own sign-in page, which
// takes the TAK account the bootstrap container created. See docs/cloudtak.md.
const cloudtakUrl = process.env.CLOUDTAK_URL || "";
const keycloakUser = process.env.KEYCLOAK_USER || "doug";
const keycloakPassword = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";
const takUser = process.env.CLOUDTAK_USERNAME || "";
const takPassword = process.env.CLOUDTAK_PASSWORD || "";
const shots = process.env.CLOUDTAK_SCREENSHOTS || ".playwright/screenshots";

test.describe("CloudTAK", () => {
  test.skip(!cloudtakUrl || !takUser || !takPassword, "CLOUDTAK_URL and the CloudTAK account are not set");

  test("Keycloak sign-in, CloudTAK sign-in, then the map", async ({ browser }) => {
    test.setTimeout(180_000);
    // A new context has no Keycloak session, so the sign-in page has to appear.
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    await page.goto(cloudtakUrl);
    await page.waitForURL(/sso\.uds\.dev\/realms\/uds\/protocol\/openid-connect\/auth/);
    await expect(page.getByLabel("Username or email")).toBeVisible();
    await page.screenshot({ path: `${shots}/cloudtak-01-keycloak.png` });

    await page.getByLabel("Username or email").fill(keycloakUser);
    await page.getByLabel("Password").fill(keycloakPassword);
    await page.getByRole("button", { name: "Sign In" }).click();

    await page.waitForURL((url) => url.origin === new URL(cloudtakUrl).origin, { timeout: 60_000 });
    const username = page.getByPlaceholder("your@email.com");
    await expect(username).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: `${shots}/cloudtak-02-login.png` });

    await username.fill(takUser);
    await page.getByPlaceholder("Your password").fill(takPassword);
    await page.getByRole("button", { name: "Sign In" }).click();

    await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 90_000 });
    // Let the first frame and the connection status settle.
    await page.waitForTimeout(5_000);
    await page.screenshot({ path: `${shots}/cloudtak-03-map.png` });

    // The same API the map uses. connection_status is the admin connection
    // (connection 0) to TAK's 8089 streaming port.
    // Through the gateway with the Authservice session, as the map does.
    const status = await page.evaluate(async ({ username, password }) => {
      const login = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const { token } = await login.json();
      const res = await fetch("/api/server", { headers: { Authorization: `Bearer ${token}` } });
      return { code: res.status, body: await res.json() };
    }, { username: takUser, password: takPassword });
    console.log(`GET /api/server: ${status.code} ${JSON.stringify({ status: status.body.status, connection_status: status.body.connection_status, url: status.body.url })}`);
    expect(status.code).toBe(200);
    expect(status.body.status).toBe("configured");
    expect(status.body.connection_status).toBe("live");

    await context.close();
  });
});
