/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

import { expect, test } from "@playwright/test";

// k3d publishes the passthrough gateway on 443. SNI selects the Service port.
const targets = [
  {
    name: "8446",
    url: process.env.TAK_HTTPS_URL || "https://takserver.uds.dev/",
  },
  {
    name: "8443",
    url: process.env.TAK_CERT_URL || "https://takserver-api.uds.dev/",
  },
];

for (const target of targets) {
  test(`TLS handshake and HTTP status on ${target.name}`, async ({ request }) => {
    const response = await request.get(target.url);
    expect(response.status(), `${target.url} returned no HTTP status`).toBeGreaterThan(0);
    expect(response.status()).toBeLessThan(500);
  });
}
