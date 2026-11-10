// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const path = process.argv[2] ?? new URL("./reports/mutation.json", import.meta.url);
const report = JSON.parse(readFileSync(path, "utf8"));
const files = Object.entries(report.files ?? {});
assert.equal(files.length, 1, "Mutation report must contain exactly the configured source target");
assert.equal(files[0][0], "scripts/webhook-scope.ts", "Unexpected mutation target");
assert.ok(files[0][1].mutants.some(mutant => ["Killed", "Survived", "Timeout"].includes(mutant.status)),
  "No executable mutations were tested; a dry run is not a mutation result");
