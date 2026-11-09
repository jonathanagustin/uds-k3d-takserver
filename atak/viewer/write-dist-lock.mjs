// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Write package-lock.json for the ws-scrcpy dist tree.
//
// The image installs that tree with `npm ci`, which checks the integrity
// hashes in the lockfile and will not create one. Scorecard reports
// `npm install` in a Dockerfile or a shell script as unpinned, so the
// refresh step lives here. `docker build --target dist-lock` runs it, then
// runs `npm ci` to prove the new lockfile installs.

import { spawnSync } from "node:child_process";

const dist = process.argv[2];
if (!dist) {
  console.error("usage: node write-dist-lock.mjs <dist-dir>");
  process.exit(1);
}

const result = spawnSync(
  "npm",
  ["install", "--omit=dev", "--package-lock-only", "--no-audit", "--no-fund"],
  { cwd: dist, stdio: "inherit" },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status === null ? 1 : result.status);
