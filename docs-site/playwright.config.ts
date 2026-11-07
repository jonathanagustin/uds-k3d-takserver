// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import { defineConfig, devices } from '@playwright/test';

const base = '/uds-k3d-takserver/';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:4321${base}`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4321',
    url: `http://127.0.0.1:4321${base}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
