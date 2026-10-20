/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test as setup } from "@playwright/test";
import { authFile } from "./playwright.config";

// setup:keycloak-user creates this account in the UDS realm.
// This session is the Keycloak account console. The TAK OAuth spec signs in
// through TAK's own redirect and does not reuse these cookies.
const username = process.env.KEYCLOAK_USER || "doug";
const password = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";

setup("authenticate", async ({ page, context }) => {
  await page.goto("https://sso.uds.dev/realms/uds/account/");

  await page.getByLabel("Username or email").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();

  await page.waitForURL(/sso\.uds\.dev/);

  const cookies = await context.cookies();
  const keycloakCookie = cookies.find((cookie) => cookie.name === "KEYCLOAK_SESSION");

  expect(keycloakCookie).toBeDefined();
  expect(keycloakCookie?.value).not.toBe("");
  expect(keycloakCookie?.domain).toContain("sso.");

  await page.context().storageState({ path: authFile });
});
