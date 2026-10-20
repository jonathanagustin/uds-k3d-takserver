/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { defineConfig, devices } from "@playwright/test";

export const playwrightDir = ".playwright";
export const authFile = `${playwrightDir}/auth/user.json`;

function clientCertificates() {
  const certPath = process.env.TAK_CLIENT_CERT;
  const keyPath = process.env.TAK_CLIENT_KEY;
  if (!certPath || !keyPath) {
    return [];
  }
  const origins = [process.env.BASE_URL, process.env.TAK_CERT_URL]
    .filter((value): value is string => Boolean(value))
    .map((value) => new URL(value).origin);
  const passphrase = process.env.TAK_CLIENT_KEY_PASSPHRASE;
  return [...new Set(origins)].map((origin) => ({
    origin,
    certPath,
    keyPath,
    ...(passphrase ? { passphrase } : {}),
  }));
}

const skipSsoSetup = process.env.SKIP_SSO_SETUP === "1";

export default defineConfig({
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ["html", { outputFolder: `${playwrightDir}/reports`, open: "never" }],
    ["list"],
  ],
  outputDir: `${playwrightDir}/output`,
  use: {
    baseURL: process.env.BASE_URL || "https://takserver.uds.dev",
    ignoreHTTPSErrors: true,
    trace: "on-first-retry",
    clientCertificates: clientCertificates(),
  },
  projects: skipSsoSetup
    ? [
        {
          name: "chromium",
          use: { ...devices["Desktop Chrome"] },
        },
      ]
    : [
        { name: "setup", testMatch: /.*\.setup\.ts/ },
        {
          name: "chromium",
          dependencies: ["setup"],
          use: {
            ...devices["Desktop Chrome"],
            storageState: authFile,
          },
        },
      ],
});
