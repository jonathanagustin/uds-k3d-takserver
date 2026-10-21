/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Records demo walkthroughs in a headed Chrome window (see demo/browser.ts
// and demo/record-browser.sh). Separate from playwright.config.ts so
// `playwright test` never picks them up.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./demo",
  testMatch: /.*\.demo\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: ".playwright/demo",
});
