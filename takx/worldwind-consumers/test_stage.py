# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline integrity guards; no compiler, downloads, native code or GUI."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("consumer_stage", HERE / "stage.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StagingGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.path = "Platform/Example.java"
        p = self.repo / self.path
        p.parent.mkdir()
        p.write_bytes(b"old\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        MODULE.git(self.repo, "add", ".")
        MODULE.git(self.repo, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                   "commit", "-qm", "fixture")
        revision = MODULE.git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.patch = self.root / "change.patch"
        self.patch.write_text("--- a/Platform/Example.java\n+++ b/Platform/Example.java\n@@ -1 +1 @@\n-old\n+new\n")
        self.lock = {"patch_sha256": MODULE.digest(self.patch.read_bytes()), "profiles": {
            "fixture": {"revision": revision, "sources": [{"path": self.path,
                "sha256": MODULE.digest(b"old\n"), "staged_sha256": MODULE.digest(b"new\n")}]} }}
        self.output = self.root / "output"

    def run_stage(self):
        return MODULE.stage(self.repo, self.output, self.lock, self.patch)

    def test_stages_patch_without_changing_checkout_or_rejecting_unrelated_files(self):
        (self.repo / "unrelated.java").write_text("untracked unrelated input")
        receipt = self.run_stage()
        self.assertEqual((self.output / self.path).read_bytes(), b"new\n")
        self.assertEqual((self.repo / self.path).read_bytes(), b"old\n")
        self.assertEqual(receipt["sources"], self.lock["profiles"]["fixture"]["sources"])

    def test_actual_git_calls_are_bounded_and_cannot_lazy_fetch(self):
        original_env = os.environ.get("GIT_NO_LAZY_FETCH")
        with patch.dict(os.environ, {"GIT_NO_LAZY_FETCH": "0"}):
            with patch.object(MODULE.subprocess, "check_output",
                              wraps=subprocess.check_output) as reads:
                with patch.object(MODULE.subprocess, "run", wraps=subprocess.run) as runs:
                    self.run_stage()
            self.assertGreaterEqual(len(reads.call_args_list), 2)
            self.assertGreaterEqual(len(runs.call_args_list), 2)
            for call in [*reads.call_args_list, *runs.call_args_list]:
                self.assertEqual(call.kwargs["timeout"], 30)
                self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(os.environ["GIT_NO_LAZY_FETCH"], "0")
        self.assertEqual(os.environ.get("GIT_NO_LAZY_FETCH"), original_env)
        self.assertEqual((self.output / self.path).read_bytes(), b"new\n")

    def test_modified_consumed_source_rejected(self):
        (self.repo / self.path).write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "source bytes"):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_symlinked_consumed_source_rejected(self):
        p = self.repo / self.path
        p.unlink()
        other = self.root / "other"
        other.write_bytes(b"old\n")
        p.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_stage()

    def test_wrong_revision_rejected(self):
        self.lock["profiles"]["fixture"]["revision"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "revision"):
            self.run_stage()

    def test_changed_patch_rejected(self):
        self.patch.write_text(self.patch.read_text().replace("+new", "+different"))
        with self.assertRaisesRegex(ValueError, "patch hash"):
            self.run_stage()

    def test_mismatching_output_pin_does_not_publish_partial_stage(self):
        self.lock["profiles"]["fixture"]["sources"][0]["staged_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "patched source"):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_existing_output_untouched(self):
        self.output.mkdir()
        (self.output / "sentinel").write_text("preserved")
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.run_stage()
        self.assertEqual((self.output / "sentinel").read_text(), "preserved")

    def test_failed_patch_does_not_publish_partial_stage(self):
        self.patch.write_text(self.patch.read_text().replace("-old", "-absent"))
        self.lock["patch_sha256"] = MODULE.digest(self.patch.read_bytes())
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_stage()
        self.assertFalse(self.output.exists())

    def test_checked_in_patch_has_one_pinned_import_change(self):
        lock = json.loads((HERE / "sources.lock.json").read_text())
        patch = (HERE.parent / "patches" / lock["patch"]).read_bytes()
        self.assertEqual(MODULE.digest(patch), lock["patch_sha256"])
        lines = patch.decode().splitlines()
        self.assertEqual([s for s in lines if s.startswith("-") and not s.startswith("---")],
                         ["-import com.jogamp.opengl.util.awt.TextRenderer;"])
        self.assertEqual([s for s in lines if s.startswith("+") and not s.startswith("+++")],
                         ["+import gov.nasa.worldwind.render.TextRenderer;"])
        for profile in lock["profiles"].values():
            changed = [s["path"] for s in profile["sources"] if s["sha256"] != s["staged_sha256"]]
            self.assertEqual(changed, [lock["patched_path"]])


@unittest.skipUnless(os.environ.get("TAKX_SOURCE_DIR"), "set TAKX_SOURCE_DIR for exact official-source staging")
class OfficialSource(unittest.TestCase):
    def test_exact_revision_and_all_staged_sources(self):
        lock = json.loads((HERE / "sources.lock.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            receipt = MODULE.stage(Path(os.environ["TAKX_SOURCE_DIR"]), Path(temp) / "out",
                                   lock, HERE.parent / "patches" / lock["patch"])
            self.assertIn(receipt["profile"], lock["profiles"])


if __name__ == "__main__":
    unittest.main()
