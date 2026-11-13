<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Actual import dialog fixture

Exact redacted failure XML from run `43357969353`, job `131664469002`, artifact `14008358281`. No passed scenario phases. Screenshot visibly labels the first tile Local SD, while XML exposes no tile text. XML SHA-256: `c37ce4f3dc5647bf534dd62d73ccad2bea632c486d1ade3f9a6783c5b503d622`.

Pinned official source `9f6893dd657feacc35ec5de03dad721c2e44170e`: ImportManagerView.java adds Local SD first and handles index zero as importLocalFile; TileButtonDialog.java preserves insertion order when adding tiles to horizontal rows. The selector requires the actual five-tile single-row hierarchy and derives tap bounds from the live first tile. This is regression coverage, not device acceptance.
