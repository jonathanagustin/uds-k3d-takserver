/**
 * Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test, type Page } from "@playwright/test";

// A non-admin user in /CloudTAK/Users and /TAK/Operators_READ, created by
// tests/ensure-map-user.py. The CloudTAK client lets that group sign in.
// The TAK Server web UI client allows only /UDS Core/Admin, so Keycloak must
// refuse the same user there. See docs/cloudtak.md#who-can-sign-in.
test.use({ storageState: { cookies: [], origins: [] } });

const cloudtakUrl = process.env.CLOUDTAK_URL || "";
const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const username = process.env.KEYCLOAK_MAP_USER || "mapuser";
const password = process.env.KEYCLOAK_MAP_USER_PASSWORD || "mapuser123!@#UN";
const shots = process.env.CLOUDTAK_SCREENSHOTS || ".playwright/screenshots";

type Reply = { code: number; body: any };

async function signIn(page: Page, url: string) {
  await page.goto(url);
  await page.waitForURL(/sso\.uds\.dev\/realms\/uds\/protocol\/openid-connect\/auth/, { timeout: 60_000 });
  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
}

test.describe("CloudTAK user group", () => {
  test.skip(process.env.SKIP_SSO_SETUP === "1", "Keycloak is not reachable");
  test.skip(!cloudtakUrl, "CLOUDTAK_URL is not set");

  test("a /CloudTAK/Users member opens the map as a regular CloudTAK user", async ({ page }) => {
    test.setTimeout(240_000);
    await signIn(page, cloudtakUrl);
    await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 120_000 });
    expect(new URL(page.url()).origin).toBe(new URL(cloudtakUrl).origin);

    const api = async (path: string): Promise<Reply> =>
      await page.evaluate(async (p) => {
        const token = localStorage.getItem("CapacitorStorage.token");
        const res = await fetch(p, { headers: { Authorization: `Bearer ${token}` } });
        const text = await res.text();
        let body: unknown = text;
        try {
          body = JSON.parse(text);
        } catch {
          // Not JSON. Keep the text for the log.
        }
        return { code: res.status, body };
      }, path);

    // sso.mjs sets system_admin only for sso.adminGroup. CloudTAK's
    // accessFor() then reports "user".
    const me = await api("/api/login");
    console.log(`GET /api/login: ${me.code} ${JSON.stringify({ email: me.body.email, access: me.body.access })}`);
    expect(me.code).toBe(200);
    expect(me.body.email).toBe(username);
    expect(me.body.access).toBe("user");

    // TAK enrolled a certificate for this user and maps /TAK/Operators_READ.
    const groups = await api("/api/marti/group");
    const names = (groups.body?.data || []).map((g: { name: string; direction: string }) => `${g.name}:${g.direction}`);
    console.log(`GET /api/marti/group: ${groups.code} ${JSON.stringify(names)}`);
    expect(groups.code).toBe(200);
    expect(names.some((n: string) => n.startsWith("Operators:"))).toBe(true);

    // An admin-only CloudTAK route refuses this session.
    const injector = await api("/api/server/injector");
    console.log(`GET /api/server/injector: ${injector.code}`);
    expect([401, 403]).toContain(injector.code);
    await page.screenshot({ path: `${shots}/cloudtak-user-map.png` });
  });

  test("the same user is refused at the TAK Server web UI", async ({ page }) => {
    test.setTimeout(180_000);
    await signIn(page, takUrl);
    await expect
      .poll(async () => `${page.url()}\n${await page.locator("body").innerText()}`, { timeout: 45_000 })
      .toMatch(/access.denied|not authorized|required group|do not have|don't have|permission/i);
    expect(page.url()).not.toMatch(/\/Marti\//);
    expect(new URL(page.url()).hostname).not.toBe(new URL(takUrl).hostname);
    await page.screenshot({ path: `${shots}/cloudtak-user-tak-denied.png` });
  });
});
