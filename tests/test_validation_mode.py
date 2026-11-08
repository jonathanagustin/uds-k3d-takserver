# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise cluster matrix planning and the actual Test result verifier."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/test-validation-mode.py"
SPEC = importlib.util.spec_from_file_location("test_mode", SCRIPT)
MODE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODE)


class TestValidationMode(unittest.TestCase):
    def test_only_explicit_trust_dispatch_uses_two_native_installs(self):
        for event in ("pull_request", "push", "workflow_dispatch"):
            for requested in ("true", "false", ""):
                with self.subTest(event=event, requested=requested):
                    matrix = MODE.install_matrix(event, requested, "custom-amd64-runner")["include"]
                    focused = event == "workflow_dispatch" and requested == "true"
                    self.assertEqual(len(matrix), 2 if focused else 3)
                    self.assertEqual([item["arch"] for item in matrix[:2]], ["amd64", "arm64"])
                    self.assertEqual(matrix[0]["runner"], "custom-amd64-runner")
                    self.assertEqual(matrix[1]["runner"], "ubuntu-22.04-arm")
                    self.assertEqual(sum(item.get("airgap", False) for item in matrix), 0 if focused else 1)

    def test_cli_default_and_override_keep_both_architectures_and_airgap(self):
        for runner in ("", "custom-amd64-runner"):
            with self.subTest(runner=runner):
                env = {**os.environ, "EVENT_NAME": "pull_request", "TRUST_BUNDLE": "false", "TEST_RUNNER": runner}
                env.pop("GITHUB_OUTPUT", None)
                result = subprocess.run(["python3", str(SCRIPT), "plan"], env=env,
                                        capture_output=True, text=True, check=True)
                rows = json.loads(result.stdout.split("=", 1)[1])["include"]
                self.assertEqual([(row["arch"], row.get("airgap", False)) for row in rows],
                                 [("amd64", False), ("arm64", False), ("amd64", True)])
                self.assertEqual([row["runner"] for row in rows],
                                 [runner or "ubuntu-22.04", "ubuntu-22.04-arm", runner or "ubuntu-22.04"])

    def test_normal_runs_reject_a_skipped_upgrade_even_if_input_was_set(self):
        for event, requested in (("pull_request", "true"), ("push", "true"), ("workflow_dispatch", "false")):
            MODE.verify(event, requested, "success", "success", "skipped")
            with self.assertRaisesRegex(ValueError, "expected success"):
                MODE.verify(event, requested, "success", "skipped", "skipped")

    def test_trust_trial_accepts_only_its_intentional_skips(self):
        MODE.verify("workflow_dispatch", "true", "success", "skipped", "skipped")
        for install in ("failure", "skipped", "cancelled", ""):
            with self.assertRaisesRegex(ValueError, "Install did not pass"):
                MODE.verify("workflow_dispatch", "true", install, "skipped", "skipped")
        for upgrade in ("failure", "cancelled", "success", ""):
            with self.assertRaisesRegex(ValueError, "expected skipped"):
                MODE.verify("workflow_dispatch", "true", "success", upgrade, "skipped")
        for pg15 in ("failure", "cancelled", "success", ""):
            with self.assertRaisesRegex(ValueError, "PostgreSQL 15"):
                MODE.verify("workflow_dispatch", "true", "success", "skipped", pg15)

    def test_cli_writes_a_runner_output_and_fails_a_false_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output"
            env = {**os.environ, "EVENT_NAME": "workflow_dispatch", "TRUST_BUNDLE": "true", "GITHUB_OUTPUT": str(output)}
            result = subprocess.run(["python3", str(SCRIPT), "plan"], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, "")
            matrix = json.loads(output.read_text().split("=", 1)[1])
            self.assertEqual(len(matrix["include"]), 2)
            env.update(INSTALL_RESULT="success", UPGRADE_RESULT="failure", PG15_RESULT="skipped")
            result = subprocess.run(["python3", str(SCRIPT), "verify"], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()
