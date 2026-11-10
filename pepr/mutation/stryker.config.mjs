// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  htmlReporter: { fileName: "mutation/reports/mutation.html" },
  jsonReporter: { fileName: "mutation/reports/mutation.json" },
  cleanTempDir: "always",
  tempDirName: "mutation/.stryker-tmp",
  mutate: ["scripts/webhook-scope.ts"],
  testRunner: "command",
  commandRunner: {
    command: "PEPR_MODE=build node --test capabilities/webhook-scope.test.ts",
  },
  coverageAnalysis: "off",
  concurrency: 2,
  timeoutMS: 5000,
  timeoutFactor: 2,
  reporters: ["clear-text", "progress", "html", "json"],
  thresholds: { high: 95, low: 95, break: 95 },
};
