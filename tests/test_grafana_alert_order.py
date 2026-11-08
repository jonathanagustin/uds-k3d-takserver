# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Messaging is Ready before CloudTAK returns, including failure cleanup."""

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tests" / "grafana-alerts.sh"


def functions():
    text = SCRIPT.read_text()
    start = text.index("restore_messaging()")
    end = text.index("trap cleanup EXIT")
    return text[start:end]


class GrafanaAlertOrderTests(unittest.TestCase):
    def test_messaging_is_ready_before_cloudtak_returns(self):
        text = SCRIPT.read_text()
        start = text.index("are firing in Alertmanager")
        rest = text[start:]
        self.assertLess(rest.index("restore_messaging"), rest.index("restore_cloudtak"))
        self.assertNotIn("replicas=1 || true", text)

    def _run(self, body, fail_on=""):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "k.log"
            program = "\n".join([
                "set -u",
                f"log={str(log)!r}",
                f"needle={fail_on!r}",
                "messaging_scaled=1",
                "cloudtak_scaled=1",
                "pids=()",
                "work=$(mktemp -d)",
                "k() {",
                "  printf '%s\\n' \"$*\" >> \"$log\"",
                "  if [[ -n \"$needle\" && \"$*\" == \"$needle\"* ]]; then return 1; fi",
                "  return 0",
                "}",
                functions(),
                body,
            ])
            result = subprocess.run(
                ["bash", "-c", program],
                capture_output=True,
                text=True,
                check=False,
            )
            recorded = log.read_text() if log.exists() else ""
            return result, recorded

    def test_cleanup_does_not_scale_cloudtak_when_messaging_scale_fails(self):
        result, recorded = self._run(
            "restore_messaging; echo rc:$?; echo messaging_scaled:$messaging_scaled; echo cloudtak_scaled:$cloudtak_scaled",
            fail_on="scale deploy/takserver-messaging",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rc:1", result.stdout)
        self.assertIn("messaging_scaled:1", result.stdout)
        self.assertIn("cloudtak_scaled:1", result.stdout)
        self.assertIn("scale deploy/takserver-messaging", recorded)
        self.assertNotIn("rollout status", recorded)
        self.assertNotIn("deploy/cloudtak", recorded)

    def test_cleanup_keeps_the_flag_when_messaging_does_not_become_ready(self):
        result, recorded = self._run(
            "restore_messaging; echo rc:$?; echo messaging_scaled:$messaging_scaled",
            fail_on="rollout status deploy/takserver-messaging",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rc:1", result.stdout)
        self.assertIn("messaging_scaled:1", result.stdout)
        self.assertLess(
            recorded.index("scale deploy/takserver-messaging"),
            recorded.index("rollout status deploy/takserver-messaging"),
        )
        self.assertNotIn("deploy/cloudtak", recorded)

    def test_failure_trap_keeps_the_original_status_and_orders_restores(self):
        result, recorded = self._run(
            "trap cleanup EXIT\nexit 9\n",
        )
        self.assertEqual(result.returncode, 9, result.stderr)
        messaging = recorded.index("scale deploy/takserver-messaging")
        ready = recorded.index("rollout status deploy/takserver-messaging")
        cloudtak = recorded.index("scale deploy/cloudtak")
        self.assertLess(messaging, ready)
        self.assertLess(ready, cloudtak)

    def test_cleanup_failure_is_not_reported_as_success(self):
        result, recorded = self._run(
            "trap cleanup EXIT\nexit 0\n",
            fail_on="rollout status deploy/cloudtak",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("scale deploy/cloudtak", recorded)
        self.assertIn("rollout status deploy/cloudtak", recorded)
