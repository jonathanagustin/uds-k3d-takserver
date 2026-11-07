# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Diagnostic artifact uploads publish the sanitized directory or nothing.

A cancelled job and a sanitizer that did not finish must not upload the
original /tmp logs. This reads the workflow files; it does not start a run.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = (
    ".github/workflows/test.yaml",
    ".github/workflows/full-core.yaml",
    ".github/workflows/benchmark.yaml",
    ".github/workflows/atak-e2e.yaml",
    ".github/workflows/atak-vm.yaml",
    ".github/scripts/dump-memory.sh",
    ".github/scripts/runner-wedge-probe.sh",
    ".github/scripts/print-logs.sh",
    "tasks/test.yaml",
    "tests/upgrade.sh",
    "tests/backup-restore.sh",
    "tests/uptime-probes.sh",
    "tests/quic.sh",
    "tests/takclient.sh",
    "tests/oidc-render.sh",
    "atak/ci/viewer-smoke.sh",
    "atak/ci/e2e.sh",
    "atak/driver/drive.sh",
    "bench/run.py",
)
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

    def test_diagnostics_redact_before_they_truncate(self):
        for rel in DIAGNOSTICS:
            text = (ROOT / rel).read_text()
            self.assertNotIn("python3 .github/scripts/redact-then-filter.sh", text, rel)
            self.assertNotIn("python3 ${", text, rel)
            logical = []
            pending = ""
            start_line = 1
            for lineno, line in enumerate(text.splitlines(), 1):
                if pending:
                    pending = pending[:-1].rstrip() + " " + line.strip()
                else:
                    pending = line
                    start_line = lineno
                if pending.rstrip().endswith("\\"):
                    continue
                logical.append((start_line, pending))
                pending = ""
            if pending:
                logical.append((start_line, pending))
            for lineno, line in logical:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "python3" in line and "redact-then-filter.sh" in line:
                    self.fail(f"{rel}:{lineno} runs the shell redactor with python3")
                body = line.replace("--tail=-1", "")
                marks = [body.find(token) for token in ("redact", '"${filter}"', "${filter}")]
                marks = [pos for pos in marks if pos != -1]
                redact_at = min(marks) if marks else -1
                # --grep is the redactor's own flag. A bare grep is a filter.
                greps = [match.start() for match in re.finditer(r"(?<![\w-])grep\b", body)]
                tails = []
                for token in ("--tail", "| tail", "|tail"):
                    pos = body.find(token)
                    if pos != -1:
                        tails.append(pos)
                dumps_a_log = any(
                    token in body
                    for token in ("logs", "logcat", "describe", "dmesg", "docker logs", "/opt/tak/logs")
                )
                if not dumps_a_log:
                    continue
                if redact_at != -1:
                    early = [pos for pos in greps + tails if pos < redact_at]
                    if early:
                        self.fail(f"{rel}:{lineno} filters before redaction: {stripped}")
                elif greps and tails and min(greps) < min(tails):
                    self.fail(f"{rel}:{lineno} greps a log and then tails it: {stripped}")

    def test_raw_tmp_logs_are_not_an_upload_path(self):
        for path in WORKFLOWS:
            text = path.read_text()
            for window, body in upload_blocks(text):
                self.assertNotIn("path: /tmp/", body, path.name)
                self.assertNotIn("path: |\n            /tmp/", body)
