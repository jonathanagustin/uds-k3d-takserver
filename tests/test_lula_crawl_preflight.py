# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

import base64
import importlib.util
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preflight", ROOT / ".github/scripts/lula-crawl-preflight.py")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class CrawlPreflight(unittest.TestCase):
    def setUp(self):
        self.pr = {"state": "open", "draft": False, "changed_files": 30,
                   "head": {"repo": {"full_name": "owner/repo"}}}
        self.baseline = {"type": "file", "encoding": "base64", "content": base64.b64encode(
            (ROOT / "charts/takserver/files/config/CoreConfig.xml").read_bytes()).decode()}

    def test_comment_execution_requires_explicit_manual_authorization(self):
        auto = yaml.safe_load((ROOT / ".github/workflows/lula.yaml").read_text())
        manual = yaml.safe_load((ROOT / ".github/workflows/lula-crawl.yaml").read_text())
        self.assertEqual(set(auto["jobs"]), {"mappings"})
        trigger = manual.get("on", manual.get(True))
        self.assertEqual(set(trigger), {"workflow_dispatch"})
        self.assertFalse(trigger["workflow_dispatch"]["inputs"]["post_comments"]["default"])
        job = manual["jobs"]["crawl"]
        self.assertEqual(job["if"], "github.ref == 'refs/heads/main' && inputs.post_comments")
        checkout = job["steps"][0]
        self.assertNotIn("ref", checkout["with"])
        command = job["steps"][-1]["run"]
        self.assertIn("lula2@0.9.5 crawl --post-mode=comment", command)

    def test_supported_boundary_passes(self):
        PREFLIGHT.validate(self.pr, self.baseline, "owner/repo")

    def test_oversized_or_invalid_counts_fail_closed(self):
        for count in [31, 100, None, "30", True, -1]:
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "30 changed files"):
                PREFLIGHT.validate({**self.pr, "changed_files": count}, self.baseline, "owner/repo")

    def test_fork_draft_and_closed_fail(self):
        for change in [{"draft": True}, {"state": "closed"}, {"head": {"repo": {"full_name": "fork/repo"}}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                PREFLIGHT.validate({**self.pr, **change}, self.baseline, "owner/repo")

    def test_new_marker_foundation_cannot_prove_a_live_crawl(self):
        for baseline in [{}, {**self.baseline, "content": base64.b64encode(b"<Configuration/>").decode()}]:
            with self.assertRaisesRegex(ValueError, "existing mapped baseline"):
                PREFLIGHT.validate(self.pr, baseline, "owner/repo")


if __name__ == "__main__":
    unittest.main()
