// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Prints a Markdown table from an lcov file: line, branch and function
// coverage per source file and in total. CI appends it to the job summary.
// Node reports only files a test imported, so a capability with no test at
// all would be missing rather than at 0%. Every non-test .ts file in
// capabilities/ must appear, or this exits 1.
// Usage: node scripts/coverage-summary.mjs coverage/lcov.info

import { readdirSync, readFileSync } from "node:fs";
import { relative } from "node:path";

const file = process.argv[2] ?? "coverage/lcov.info";
const rows = [];
let current;
for (const line of readFileSync(file, "utf8").split("\n")) {
  const [key, value = ""] = line.split(/:(.*)/s);
  if (key === "SF") {
    current = { file: relative(process.cwd(), value), LF: 0, LH: 0, BRF: 0, BRH: 0, FNF: 0, FNH: 0 };
  } else if (current && key in current && key !== "file") {
    current[key] = Number(value);
  } else if (key === "end_of_record" && current) {
    rows.push(current);
    current = undefined;
  }
}
if (rows.length === 0) {
  console.error(`${file} has no records`);
  process.exit(1);
}

const missing = readdirSync("capabilities")
  .filter(name => name.endsWith(".ts") && !name.endsWith(".test.ts"))
  .map(name => `capabilities/${name}`)
  .filter(name => !rows.some(r => r.file === name));
if (missing.length > 0) {
  console.error(`No test loads ${missing.join(", ")}, so it has no coverage`);
  process.exit(1);
}

const pct = (hit, found) => (found === 0 ? "n/a" : `${((100 * hit) / found).toFixed(1)}%`);
const cell = (hit, found) => `${pct(hit, found)} (${hit}/${found})`;
const total = rows.reduce(
  (sum, r) => ({ LF: sum.LF + r.LF, LH: sum.LH + r.LH, BRF: sum.BRF + r.BRF, BRH: sum.BRH + r.BRH, FNF: sum.FNF + r.FNF, FNH: sum.FNH + r.FNH }),
  { LF: 0, LH: 0, BRF: 0, BRH: 0, FNF: 0, FNH: 0 },
);

console.log("| File | Lines | Branches | Functions |");
console.log("|---|---|---|---|");
for (const r of rows) {
  console.log(`| \`${r.file}\` | ${cell(r.LH, r.LF)} | ${cell(r.BRH, r.BRF)} | ${cell(r.FNH, r.FNF)} |`);
}
console.log(`| **Total** | **${cell(total.LH, total.LF)}** | **${cell(total.BRH, total.BRF)}** | **${cell(total.FNH, total.FNF)}** |`);
