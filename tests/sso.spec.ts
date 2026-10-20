/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, request as playwrightRequest, test } from "@playwright/test";

// The setup project stores a Keycloak account-console session. This test
// starts signed out and follows TAK's own redirect to the realm.
test.use({ storageState: { cookies: [], origins: [] } });

const ssoOrigin = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";

test("Keycloak user reaches Marti and the mapped TAK group", async ({ page }) => {
  test.skip(process.env.SKIP_SSO_SETUP === "1", "Keycloak is not reachable");
  test.setTimeout(180_000);

  const username = process.env.KEYCLOAK_USER || "doug";
  const password = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";

  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(ssoOrigin);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });

  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await userField.fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();

  // /UDS Core/Admin is ROLE_ADMIN, so HomeApi opens Marti.
  await page.waitForURL(/\/Marti\//, { timeout: 90_000 });
  await expect(page).not.toHaveURL(/sso\.uds\.dev/);

  const groupsUrl = new URL("/Marti/api/groups/all", ssoOrigin).toString();
  await expect
    .poll(
      async () => {
        const response = await page.request.get(groupsUrl);
        if (!response.ok()) {
          return "";
        }
        return response.text();
      },
      { timeout: 30_000 },
    )
    .toContain("Operators");

  // TAK has no route named whoami. /util/user/roles is the authenticated
  // authority list, and /groups/all is the mapped group list.
  const rolesUrl = new URL("/Marti/api/util/user/roles", ssoOrigin).toString();
  const roles = await page.request.get(rolesUrl);
  expect(roles.ok()).toBeTruthy();
  expect(await roles.text()).toContain("ROLE_ADMIN");

  const adminUrl = new URL("/Marti/api/util/isAdmin", ssoOrigin).toString();
  const admin = await page.request.get(adminUrl);
  expect(admin.ok()).toBeTruthy();
  expect((await admin.text()).trim()).toBe("true");

  const cookies = await page.context().cookies();
  const token = cookies
    .filter((cookie) => cookie.name.startsWith("access_token_"))
    .sort((left, right) =>
      left.name.localeCompare(right.name, undefined, { numeric: true }),
    )
    .map((cookie) => cookie.value)
    .join("");
  expect(token.length).toBeGreaterThan(20);

  const dir = mkdtempSync(join(tmpdir(), "tak-enroll-"));
  execFileSync("openssl", [
    "req",
    "-new",
    "-newkey",
    "rsa:2048",
    "-nodes",
    "-keyout",
    join(dir, "client.key"),
    "-out",
    join(dir, "client.csr"),
    "-subj",
    "/CN=doug/O=TAK/OU=UDS",
  ]);
  const csr = readFileSync(join(dir, "client.csr"));
  const enrollBase = process.env.TAK_HTTPS_URL || "https://takserver.uds.dev:18443/";
  const enrollUrl = new URL(
    "/Marti/api/tls/signClient/v2?clientUid=doug&version=1",
    enrollBase,
  ).toString();
  // A fresh context sends no client certificate. 8446 must accept the bearer.
  const enrollCtx = await playwrightRequest.newContext({ ignoreHTTPSErrors: true });
  try {
    const enrolled = await enrollCtx.post(enrollUrl, {
      data: csr,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
        "Content-Type": "text/plain",
      },
      timeout: 30_000,
    });
    const body = await enrolled.text();
    expect(enrolled.ok(), body).toBeTruthy();
    expect(body).toContain("signedCert");
  } finally {
    await enrollCtx.dispose();
  }
});

test("8443 and 8089 still require a client certificate", async () => {
  const certUrl = process.env.TAK_CERT_URL || "https://takserver-api.uds.dev/";
  const streamUrl = process.env.TAK_STREAM_URL || "https://takserver-stream.uds.dev/";
  // playwright.config.ts attaches the admin certificate to these origins for
  // every context. An empty list is what makes this request anonymous.
  const ctx = await playwrightRequest.newContext({ ignoreHTTPSErrors: true, clientCertificates: [] });
  try {
    await expect(ctx.get(certUrl, { timeout: 20_000 })).rejects.toThrow();
    await expect(ctx.get(streamUrl, { timeout: 20_000 })).rejects.toThrow();
  } finally {
    await ctx.dispose();
  }
});
