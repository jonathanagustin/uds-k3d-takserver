/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

// CloudTAK on map.<domain> with Keycloak sign-in. Opening the map sends the
// browser to the UDS Keycloak login, and the Keycloak user comes back to the
// map with a CloudTAK session and a TAK client certificate of their own.
// See docs/cloudtak.md.
const cloudtakUrl = process.env.CLOUDTAK_URL || "";
const keycloakUser = process.env.KEYCLOAK_USER || "doug";
const keycloakPassword = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";
const shots = process.env.CLOUDTAK_SCREENSHOTS || ".playwright/screenshots";

type Reply = { code: number; body: any };

test.describe("CloudTAK", () => {
  test.skip(!cloudtakUrl, "CLOUDTAK_URL is not set");

  test("map.<domain> -> Keycloak -> CloudTAK map with a TAK connection", async ({ browser }) => {
    test.setTimeout(240_000);
    // A new context has no Keycloak session, so the sign-in page has to appear.
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();

    await page.goto(cloudtakUrl);
    await page.waitForURL(/sso\.uds\.dev\/realms\/uds\/protocol\/openid-connect\/auth/, { timeout: 60_000 });
    const auth = new URL(page.url());
    expect(auth.searchParams.get("client_id")).toBe("uds-cloudtak");
    expect(auth.searchParams.get("redirect_uri")).toBe(`${new URL(cloudtakUrl).origin}/api/login/oidc/callback`);
    await expect(page.getByLabel("Username or email")).toBeVisible();
    await page.screenshot({ path: `${shots}/cloudtak-01-keycloak.png` });

    await page.getByLabel("Username or email").fill(keycloakUser);
    await page.getByLabel("Password").fill(keycloakPassword);
    await page.getByRole("button", { name: "Sign In" }).click();

    // No CloudTAK password form on the way back.
    await expect(page.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 120_000 });
    expect(new URL(page.url()).origin).toBe(new URL(cloudtakUrl).origin);
    expect(new URL(page.url()).pathname).not.toMatch(/^\/login/);

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

    // The CloudTAK session belongs to the Keycloak user.
    const login = await api("/api/login");
    console.log(`GET /api/login: ${login.code} ${JSON.stringify({ username: login.body.username, access: login.body.access })}`);
    expect(login.code).toBe(200);
    expect(login.body.username).toBe(keycloakUser);

    // TAK answers with the user's own certificate. CloudTAK calls TAK's
    // groups API with the certificate it enrolled at sign-in.
    const groups = await api("/api/marti/group");
    const names = (groups.body?.data || []).map((g: { name: string; direction: string }) => `${g.name}:${g.direction}`);
    console.log(`GET /api/marti/group: ${groups.code} ${JSON.stringify(names)}`);
    expect(groups.code).toBe(200);
    expect(names.length).toBeGreaterThan(0);

    // The admin connection (connection 0) to TAK's 8089 streaming port.
    const server = await api("/api/server");
    console.log(`GET /api/server: ${server.code} ${JSON.stringify({ status: server.body.status, connection_status: server.body.connection_status, url: server.body.url })}`);
    expect(server.code).toBe(200);
    expect(server.body.connection_status).toBe("live");

    // The map's own streaming connection: TAK lists the user as a
    // connected client.
    let seen: unknown[] = [];
    await expect
      .poll(
        async () => {
          const clients = await api("/api/marti/clients?secago=600");
          seen = (clients.body?.data || []).map((c: { username?: string; callsign?: string }) => `${c.username}/${c.callsign}`);
          return seen.some((s) => String(s).startsWith(`${keycloakUser}/`));
        },
        { timeout: 90_000, intervals: [5_000] },
      )
      .toBe(true);
    console.log(`TAK clients: ${JSON.stringify(seen)}`);

    // Let the first frame and the status bar settle.
    await page.waitForTimeout(3_000);
    await page.screenshot({ path: `${shots}/cloudtak-02-map.png` });

    // The local form is hidden: /login?sso=off shows only the Keycloak button.
    await page.goto(`${cloudtakUrl}/login?sso=off`);
    await expect(page.getByText("Sign in with UDS SSO")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByPlaceholder("Your password")).toHaveCount(0);
    await expect(page.getByText("Sign in with Passkey")).toHaveCount(0);
    await page.screenshot({ path: `${shots}/cloudtak-03-login-page.png` });

    await context.close();
  });
});
