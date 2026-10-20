/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Web UI walkthrough for the demo video: Keycloak SSO through UDS Core,
// then the TAK admin pages. The waits are for the viewer, not the app.
import { expect, type Page, test } from "@playwright/test";

const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const username = process.env.KEYCLOAK_USER || "doug";
const password = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";

// A small caption in the corner so the viewer knows where they are.
async function caption(page: Page, text: string) {
  await page.evaluate((label) => {
    const id = "demo-caption";
    document.getElementById(id)?.remove();
    const el = document.createElement("div");
    el.id = id;
    el.textContent = label;
    Object.assign(el.style, {
      position: "fixed",
      left: "24px",
      bottom: "24px",
      zIndex: "2147483647",
      padding: "10px 16px",
      borderRadius: "8px",
      background: "rgba(17, 17, 27, 0.88)",
      color: "#cdd6f4",
      font: "600 18px/1.3 system-ui, sans-serif",
      boxShadow: "0 4px 16px rgba(0, 0, 0, 0.35)",
      pointerEvents: "none",
    });
    document.body.appendChild(el);
  }, text);
}

async function visit(page: Page, path: string, label: string, hold = 4_000) {
  const response = await page.goto(new URL(path, takUrl).toString(), {
    waitUntil: "networkidle",
    timeout: 60_000,
  });
  expect(response?.status() ?? 0, `${path} status`).toBeLessThan(400);
  await caption(page, label);
  await page.waitForTimeout(hold);
}

test("TAK web UI through UDS Core SSO", async ({ page }) => {
  test.setTimeout(300_000);
  page.on("dialog", (dialog) => dialog.accept());

  await page.goto(takUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await caption(page, "TAK redirects to Keycloak (UDS Core SSO)");
  await page.waitForTimeout(2_500);

  await userField.pressSequentially(username, { delay: 90 });
  await page.getByLabel("Password").pressSequentially(password, { delay: 40 });
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Sign In" }).click();

  // /UDS Core/Admin maps to ROLE_ADMIN, so TAK opens the Marti admin UI.
  await page.waitForURL(/\/Marti\//, { timeout: 90_000 });
  await page.waitForLoadState("networkidle");
  await caption(page, "Signed in: Keycloak group mapped to TAK admin");
  await page.waitForTimeout(4_000);

  await visit(page, "/Marti/metrics/index.html", "TAK server monitor");
  await visit(page, "/Marti/inputs/index.html", "Inputs and data feeds");
  await visit(page, "/Marti/security/index.html", "Security and authentication");
});
