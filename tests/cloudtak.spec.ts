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
    // The config's storageState holds the setup project's Keycloak session.
    // An empty one makes the Keycloak sign-in page appear.
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 },
      storageState: { cookies: [], origins: [] },
    });
    const page = await context.newPage();

    // Basemap tiles the map loads through CloudTAK's tile proxy.
    const tiles: { z: number; cache: string }[] = [];
    page.on("response", (res) => {
      const m = /\/uds-basemap\/tiles\/(\d+)\/\d+\/\d+(\?|$)/.exec(res.url());
      if (m && res.status() === 200 && (res.headers()["content-type"] || "").startsWith("image/")) {
        tiles.push({ z: Number(m[1]), cache: res.headers()["x-cache-status"] || "" });
      }
    });

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

    // First sign-in: CloudTAK asks for a callsign before the map is usable.
    // Answer it as a user would, then skip the browser permission step.
    const welcome = page.getByText("Welcome to CloudTAK");
    const firstRun = await welcome
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (firstRun) {
      await page.getByPlaceholder("Enter your callsign").fill(keycloakUser);
      await page.getByRole("button", { name: "Get Started" }).click();
      // The permission step may follow. Skip it until no step is left.
      const steps = [
        welcome,
        page.getByRole("button", { name: "Not now" }),
        page.getByRole("button", { name: "Skip for now" }),
      ];
      await expect
        .poll(
          async () => {
            for (const skip of steps.slice(1)) {
              if (await skip.isVisible().catch(() => false)) await skip.click().catch(() => {});
            }
            for (const step of steps) {
              if (await step.isVisible().catch(() => false)) return false;
            }
            return true;
          },
          { timeout: 30_000, intervals: [1_000] },
        )
        .toBe(true);
    }
    console.log(`first-run dialog: ${firstRun ? "answered" : "not shown"}`);
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
    const me = await api("/api/login");
    console.log(`GET /api/login: ${me.code} ${JSON.stringify({ email: me.body.email, access: me.body.access })}`);
    expect(me.code).toBe(200);
    // CloudTAK names the account `email`; here it is the Keycloak username.
    expect(me.body.email).toBe(keycloakUser);

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

    // Default basemap: a server basemap the bootstrap container created,
    // with its attribution on the map, and tiles from the tile host.
    const basemaps = await api("/api/basemap?scope=server");
    const osm = (basemaps.body?.items || []).find((b: { url: string }) => b.url.includes("/uds-basemap/tiles/"));
    console.log(`server basemap: ${JSON.stringify(osm && { id: osm.id, name: osm.name, url: osm.url, attribution: osm.attribution })}`);
    expect(osm).toBeTruthy();
    await expect.poll(() => tiles.length, { timeout: 60_000, intervals: [1_000] }).toBeGreaterThan(3);
    await expect(page.locator(".maplibregl-ctrl-attrib-inner")).toContainText("OpenStreetMap", { timeout: 30_000 });
    // Without the session token the proxy refuses the tile.
    const anon = await page.evaluate(async () => (await fetch("/uds-basemap/tiles/0/0/0", { credentials: "omit" })).status);
    expect(anon).toBe(401);

    // Let the first frame and the status bar settle.
    await page.waitForTimeout(3_000);
    await page.screenshot({ path: `${shots}/cloudtak-02-map.png` });

    // Zoom in as a user would. The map asks for tiles at the new zoom.
    const before = Math.max(...tiles.map((t) => t.z));
    const canvas = page.locator("canvas.maplibregl-canvas");
    const box = await canvas.boundingBox();
    if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (let i = 0; i < 4; i++) {
      await page.mouse.wheel(0, -600);
      await page.waitForTimeout(400);
    }
    await expect.poll(() => Math.max(...tiles.map((t) => t.z)), { timeout: 60_000, intervals: [1_000] }).toBeGreaterThan(before);
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    await page.waitForTimeout(3_000);
    const zooms = [...new Set(tiles.map((t) => t.z))].sort((a, b) => a - b);
    const cache = tiles.reduce((acc: Record<string, number>, t) => ({ ...acc, [t.cache || "-"]: (acc[t.cache || "-"] || 0) + 1 }), {});
    console.log(`basemap tiles: ${tiles.length} at zoom ${JSON.stringify(zooms)}, cache ${JSON.stringify(cache)}`);
    await page.screenshot({ path: `${shots}/cloudtak-04-basemap.png` });

    // The local form is hidden. A signed-out browser on /login?sso=off
    // (no auto-redirect) shows only the Keycloak button.
    const signedOut = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 },
      storageState: { cookies: [], origins: [] },
    });
    const login = await signedOut.newPage();
    await login.goto(`${cloudtakUrl}/login?sso=off`);
    await expect(login.getByText("Sign in with UDS SSO")).toBeVisible({ timeout: 30_000 });
    await expect(login.getByPlaceholder("Your password")).toHaveCount(0);
    await expect(login.getByText("Sign in with Passkey")).toHaveCount(0);
    await login.screenshot({ path: `${shots}/cloudtak-03-login-page.png` });
    await signedOut.close();

    await context.close();
  });
});
