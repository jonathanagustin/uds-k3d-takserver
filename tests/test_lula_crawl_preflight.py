# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preflight", ROOT / ".github/scripts/lula-crawl-preflight.py")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class CrawlPreflight(unittest.TestCase):
    def setUp(self):
        self.pr = {"state": "open", "draft": False, "changed_files": 30,
                   "base": {"ref": "main", "sha": "b" * 40},
                   "head": {"sha": "a" * 40, "repo": {"full_name": "owner/repo"}}}
        self.baseline = {"type": "file", "encoding": "base64",
                         "path": "charts/takserver/files/config/CoreConfig.xml", "content": base64.b64encode(
            (ROOT / "charts/takserver/files/config/CoreConfig.xml").read_bytes()).decode()}

    def test_comment_execution_requires_explicit_manual_authorization(self):
        auto = yaml.safe_load((ROOT / ".github/workflows/lula.yaml").read_text())
        manual = yaml.safe_load((ROOT / ".github/workflows/lula-crawl.yaml").read_text())
        self.assertEqual(set(auto["jobs"]), {"mappings"})
        trigger = manual.get("on", manual.get(True))
        self.assertEqual(set(trigger), {"workflow_dispatch", "pull_request_target"})
        self.assertEqual(trigger["pull_request_target"]["branches"], ["main"])
        self.assertFalse(trigger["workflow_dispatch"]["inputs"]["post_comments"]["default"])
        job = manual["jobs"]["crawl"]
        for guard in ["github.ref == 'refs/heads/main'", "inputs.post_comments",
                      "github.event.pull_request.base.ref == 'main'",
                      "github.event.pull_request.state == 'open'", "!github.event.pull_request.draft",
                      "github.event.pull_request.head.repo.full_name == github.repository"]:
            self.assertIn(guard, job["if"])
        checkout = job["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "${{ github.sha }}")
        self.assertFalse(checkout["with"]["persist-credentials"])
        command = job["steps"][-1]["run"]
        self.assertIn("index.safe.mjs\" crawl --post-mode=comment", command)
        self.assertNotIn("npx", command)
        self.assertEqual(manual["permissions"], {"contents": "read"})
        self.assertEqual(job["permissions"], {"contents": "read", "pull-requests": "write"})
        self.assertIn("github.event.pull_request.number || inputs.pull_number", manual["concurrency"]["group"])
        self.assertFalse(manual["concurrency"]["cancel-in-progress"])
        for step in job["steps"]:
            self.assertNotIn("${{", step.get("run", ""))
            self.assertNotIn("continue-on-error", step)
        prepare = next(s for s in job["steps"] if "without credentials" in s["name"])
        self.assertNotIn("GITHUB_TOKEN", prepare.get("env", {}))
        self.assertIn("--ignore-scripts", prepare["run"])
        self.assertIn("module.verify_archive", prepare["run"])
        self.assertLess(prepare["run"].index("module.verify_archive"), prepare["run"].index("npm install"))
        preflight = next(s for s in job["steps"] if "existing mapped baseline" in s["name"])
        self.assertIn(".github/scripts/lula-crawl-preflight.py", preflight["run"])
        self.assertIn("--automatic", preflight["run"])
        for step in job["steps"][job["steps"].index(preflight)+1:]:
            self.assertEqual(step["if"], "steps.preflight.outputs.ready == 'true'")

    def test_supported_boundary_passes(self):
        PREFLIGHT.validate(self.pr, self.baseline, "owner/repo")

    def test_oversized_or_invalid_counts_fail_closed(self):
        for count in [31, 100, None, "30", True, -1]:
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "30 changed files"):
                PREFLIGHT.validate({**self.pr, "changed_files": count}, self.baseline, "owner/repo")

    def test_fork_draft_and_closed_fail(self):
        for change in [{"draft": True}, {"draft": None}, {"state": "closed"},
                       {"base": {"ref": "other"}}, {"head": {"repo": {"full_name": "fork/repo"}}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                PREFLIGHT.validate({**self.pr, **change}, self.baseline, "owner/repo")

    def test_snapshot_requires_exact_sources(self):
        self.assertEqual(PREFLIGHT.snapshot(self.pr, "owner/repo"), {
            "repository": "owner/repo", "baseSHA": "b" * 40, "headSHA": "a" * 40, "changedFiles": 30})
        for sha in [None, "main", "a" * 39, "$(command)"]:
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                PREFLIGHT.snapshot({**self.pr, "base": {"sha": sha}}, "owner/repo")

    def test_only_known_automatic_oversize_is_a_skip(self):
        oversized = {**self.pr, "changed_files": 31}
        self.assertIsNone(PREFLIGHT.evaluate(oversized, self.baseline, "owner/repo", automatic=True))
        with self.assertRaises(PREFLIGHT.UnsupportedFileCount):
            PREFLIGHT.evaluate(oversized, self.baseline, "owner/repo")
        for pr, baseline in [
            ({**oversized, "changed_files": "31"}, self.baseline),
            ({**oversized, "draft": True}, self.baseline),
            ({**oversized, "head": {"sha": "not-a-commit"}}, self.baseline),
            (oversized, {**self.baseline, "path": "wrong.xml"}),
            (oversized, {**self.baseline, "content": "not-base64"}),
        ]:
            with self.subTest(pr=pr, baseline=baseline), self.assertRaises(ValueError):
                PREFLIGHT.evaluate(pr, baseline, "owner/repo", automatic=True)

    def test_actual_cli_skip_and_failures_write_no_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pr, baseline, binding, output = [root / name for name in ["pr.json", "baseline.json", "binding.json", "output"]]
            baseline.write_text(json.dumps(self.baseline))
            pr.write_text(json.dumps({**self.pr, "changed_files": 31}))
            command = [sys.executable, str(ROOT / ".github/scripts/lula-crawl-preflight.py"),
                       str(pr), str(baseline), "owner/repo", str(binding)]
            result = subprocess.run(command + ["--automatic", "--github-output", str(output)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "Lula automatic crawl skipped: unsupported_changed_file_count")
            self.assertEqual(output.read_text(), "ready=false\n")
            self.assertFalse(binding.exists())
            output.unlink()
            result = subprocess.run(command + ["--github-output", str(output)], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(binding.exists())
            pr.write_text(json.dumps(self.pr))
            result = subprocess.run(command + ["--automatic", "--github-output", str(output)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "ready=true\n")
            self.assertEqual(json.loads(binding.read_text()), PREFLIGHT.snapshot(self.pr, "owner/repo"))
            output.unlink()
            binding.unlink()
            pr.write_text("invalid JSON")
            result = subprocess.run(command + ["--automatic", "--github-output", str(output)], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertFalse(binding.exists())

    def test_new_marker_foundation_cannot_prove_a_live_crawl(self):
        for baseline in [{}, {**self.baseline, "content": base64.b64encode(b"<Configuration/>").decode()}]:
            with self.assertRaisesRegex(ValueError, "existing mapped baseline"):
                PREFLIGHT.validate(self.pr, baseline, "owner/repo")

    def test_existing_baseline_requires_real_ordered_comment_blocks(self):
        identifier = "0ba6e9e4-4061-5ff4-9c29-69bffbd3a489"
        start = f"<!-- @lulaStart {identifier} -->\n"
        end = f"<!-- @lulaEnd {identifier} -->\n"
        for content in [end + start, start + start + end, start + end + end,
                        start + end + start, f'<value>@lulaStart {identifier} @lulaEnd {identifier}</value>']:
            baseline = {**self.baseline, "content": base64.b64encode(content.encode()).decode()}
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "existing mapped baseline"):
                PREFLIGHT.validate(self.pr, baseline, "owner/repo")
        # CoreConfig actually contains separate TLS blocks sharing this UUID.
        content = start + "<Connector/>\n" + end + start + "<Connector/>\n" + end
        PREFLIGHT.validate(self.pr, {**self.baseline, "content": base64.b64encode(content.encode()).decode()}, "owner/repo")

    def test_markers_from_a_different_api_file_cannot_supply_the_baseline(self):
        for path in [None, "other.xml", "../charts/takserver/files/config/CoreConfig.xml"]:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "existing mapped baseline"):
                PREFLIGHT.validate(self.pr, {**self.baseline, "path": path}, "owner/repo")


if __name__ == "__main__":
    unittest.main()
