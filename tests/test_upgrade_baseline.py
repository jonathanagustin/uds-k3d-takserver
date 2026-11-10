# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Offline contracts for release selection and the first-release bootstrap."""

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SPEC = importlib.util.spec_from_file_location("upgrade_baseline", Path(__file__).with_name("upgrade-baseline.py"))
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def release(tag, **extra):
    return {"tag_name": tag, "published_at": "2026-01-01T00:00:00Z", **extra}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.git = patch.object(baseline, "git").start()
        self.run = patch.object(baseline.subprocess, "run").start()
        self.addCleanup(patch.stopall)
        self.git.return_value = ""

    def valid_git(self, command, *args):
        if command == "rev-parse":
            return "a" * 40
        if command == "show":
            tag = args[0].split(":")[0].split("/")[-1]
            return json.dumps({".": tag.removeprefix("v")})
        return ""

    def test_no_release_and_no_tags_is_explicit_bootstrap(self):
        self.assertIsNone(baseline.select_release([]))

    def test_tag_without_published_release_fails(self):
        self.git.return_value = "v0.1.0\n"
        with self.assertRaisesRegex(RuntimeError, "Stable Git tags exist"):
            baseline.select_release([])

    def test_latest_stable_semantic_version_not_api_order(self):
        self.git.side_effect = self.valid_git
        result = baseline.select_release([
            release("v1.9.0"), release("v1.10.0"), release("v2.0.0", draft=True),
            release("v3.0.0", prerelease=True), release("v4.0.0-rc.1"),
        ])
        self.assertEqual(result["tag"], "v1.10.0")
        self.assertEqual(result["package"], "oci://ghcr.io/jonathanagustin/uds-takserver/takserver:1.10.0-upstream")
        self.run.assert_called_once_with(
            ["git", "merge-base", "--is-ancestor", "a" * 40, "refs/remotes/origin/main"],
            check=True, capture_output=True,
        )

    def test_release_on_the_commit_under_test_uses_the_previous_release(self):
        commits = {"v1.0.0": "a" * 40, "v1.1.0": "b" * 40}

        def git(command, *args):
            if command == "rev-parse":
                return commits[args[1].split("/")[-1].removesuffix("^{commit}")]
            return self.valid_git(command, *args)

        self.git.side_effect = git
        result = baseline.select_release([release("v1.0.0"), release("v1.1.0")], head="b" * 40)
        self.assertEqual(result["tag"], "v1.0.0")
        self.assertEqual(result["commit"], "a" * 40)

    def test_pinned_tag_selects_that_release(self):
        self.git.side_effect = self.valid_git
        result = baseline.select_release(
            [release("v0.6.0"), release("v0.7.0"), release("v0.7.1")], pin="v0.6.0",
        )
        self.assertEqual(result["tag"], "v0.6.0")
        self.assertEqual(result["package"], "oci://ghcr.io/jonathanagustin/uds-takserver/takserver:0.6.0-upstream")

    def test_registry_namespace_uses_migrated_historical_packages(self):
        self.git.side_effect = self.valid_git
        for version, namespace in (("0.10.0", "uds-takserver"),
                                   ("0.11.0", "uds-takserver"),
                                   ("1.10.0", "uds-takserver")):
            with self.subTest(version=version):
                result = baseline.select_release([release("v" + version)])
                self.assertEqual(result["package"],
                                 f"oci://ghcr.io/jonathanagustin/{namespace}/takserver:{version}-upstream")

    def test_pinned_tag_must_be_published(self):
        self.git.side_effect = self.valid_git
        with self.assertRaisesRegex(RuntimeError, "Pinned baseline v0.6.0"):
            baseline.select_release([release("v0.6.0", draft=True), release("v0.7.1")], pin="v0.6.0")

    def test_first_release_on_the_commit_under_test_is_bootstrap(self):
        self.git.side_effect = self.valid_git
        self.assertIsNone(baseline.select_release([release("v1.0.0")], head="a" * 40))

    def test_other_head_keeps_the_latest_release(self):
        self.git.side_effect = self.valid_git
        result = baseline.select_release([release("v1.0.0"), release("v1.1.0")], head="c" * 40)
        self.assertEqual(result["tag"], "v1.1.0")

    def test_manifest_mismatch_fails_without_older_fallback(self):
        self.git.side_effect = ["a" * 40, '{".": "1.0.0"}']
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            baseline.select_release([release("v1.0.0"), release("v2.0.0")])

    def test_release_off_main_fails(self):
        self.git.side_effect = self.valid_git
        self.run.side_effect = subprocess.CalledProcessError(1, "git merge-base")
        with self.assertRaises(subprocess.CalledProcessError):
            baseline.select_release([release("v1.0.0")])

    def test_missing_tag_fails(self):
        self.git.side_effect = subprocess.CalledProcessError(128, "git rev-parse")
        with self.assertRaises(subprocess.CalledProcessError):
            baseline.select_release([release("v1.0.0")])

    def test_auth_failure_is_not_empty_releases(self):
        with patch.object(baseline.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("url", 403, "forbidden", {}, None)):
            with self.assertRaises(urllib.error.HTTPError):
                list(baseline.releases("owner/repo"))

    def test_network_failure_is_not_empty_releases(self):
        with patch.object(baseline.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(urllib.error.URLError):
                list(baseline.releases("owner/repo"))

    def test_no_baseline_writes_notice_summary_and_false_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(root / "output"),
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
            }), patch.object(baseline, "releases", return_value=[]), patch(
                "sys.argv", ["upgrade-baseline.py", "--output", str(root / "baseline.json")],
            ), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                # ::notice:: is a workflow command. The contract test must
                # capture it, or a passing run records "upgrade test not run"
                # on a job whose upgrade step still executes.
                baseline.main()
            self.assertEqual((root / "baseline.json").read_text(), "null\n")
            self.assertEqual((root / "output").read_text(), "available=false\n")
            self.assertEqual((root / "summary").read_text(), "no released baseline yet; upgrade test not run\n")
            self.assertEqual(
                stdout.getvalue(),
                "::notice::no released baseline yet; upgrade test not run\n",
            )


if __name__ == "__main__":
    unittest.main()
