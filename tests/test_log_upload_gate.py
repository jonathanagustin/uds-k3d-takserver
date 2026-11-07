# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Diagnostic artifact uploads publish the sanitized directory or nothing.

A cancelled job and a sanitizer that did not finish must not upload the
original /tmp logs. This reads the workflow files; it does not start a run.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "test.yaml",
    ROOT / ".github" / "workflows" / "full-core.yaml",
    ROOT / ".github" / "workflows" / "benchmark.yaml",
)


def upload_blocks(text):
    """Yield (step_text, path_text) for each upload-artifact use."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/upload-artifact@" not in line:
            continue
        window = "\n".join(lines[max(0, index - 4):index + 8])
        body = "\n".join(lines[index:index + 20])
        yield window, body


class LogUploadGateTests(unittest.TestCase):
    def test_log_uploads_require_a_finished_sanitizer_and_are_not_cancelled(self):
        for path in WORKFLOWS:
            text = path.read_text()
            gated = 0
            for window, body in upload_blocks(text):
                if "payload/" not in body:
                    continue
                gated += 1
                self.assertIn("!cancelled()", window, path.name)
                self.assertIn("steps.sanitize.outputs.ok == 'true'", window, path.name)
                self.assertNotIn("/tmp/zarf-", body)
                self.assertNotIn("/tmp/uds-", body)
            self.assertGreater(gated, 0, path.name)

    def test_k3s_and_container_logs_are_redacted_before_they_are_filtered(self):
        dump = (ROOT / ".github" / "scripts" / "dump-memory.sh").read_text()
        k3s = dump.split("k3s starts, errors, and shutdown lines", 1)[1].split("done", 1)[0]
        self.assertIn("redact-then-filter.sh", k3s)
        self.assertNotIn("| grep", k3s)
        self.assertNotIn("--tail=", k3s)
        test = (ROOT / ".github" / "workflows" / "test.yaml").read_text()
        cloudtak = test.split("CloudTAK pod details", 1)[1].split("Node memory", 1)[0]
        self.assertIn("redact-then-filter.sh", cloudtak)
        self.assertNotIn("--tail=", cloudtak)
        self.assertNotIn("playwright", cloudtak.lower())

    def test_raw_tmp_logs_are_not_an_upload_path(self):
        for path in WORKFLOWS:
            text = path.read_text()
            for window, body in upload_blocks(text):
                self.assertNotIn("path: /tmp/", body, path.name)
                self.assertNotIn("path: |\n            /tmp/", body)
