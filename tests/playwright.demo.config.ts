/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Records the web UI walkthrough for the demo video. Separate from
// playwright.config.ts so `playwright test` never picks it up.
import { defineConfig, devices } from "@playwright/test";

const size = { width: 1280, height: 720 };

export default defineConfig({
  testDir: "./demo",
  testMatch: /.*\.demo\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: ".playwright/demo",
  use: {
    ...devices["Desktop Chrome"],
    viewport: size,
    deviceScaleFactor: 1,
    ignoreHTTPSErrors: true,
    video: { mode: "on", size },
    screenshot: "on",
  },
});
