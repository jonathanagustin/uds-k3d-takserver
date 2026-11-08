# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Runner routing probes report timeouts without blocking later cleanup."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class RunnerWedgeProbeTests(unittest.TestCase):
    def probe(self, route, kernel=""):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            scripts = {
                "ip": route,
                "sudo": 'test "$1" = -n || exit 2\nshift\nexec "$@"',
                "dmesg": 'printf "%s\\n" "$TEST_KERNEL_LINES"',
                # Exercise real TERM/KILL behavior quickly while recording the
                # production budgets supplied by the caller.
                "timeout": 'printf "%s\\n" "$*" >> "$TEST_TIMEOUT_LOG"\n'
                           'test "$1" = --kill-after=1s || exit 2\nshift\nshift\n'
                           'exec /usr/bin/timeout --kill-after=0.1s 0.1s "$@"',
            }
            for name, body in scripts.items():
                path = directory / name
                path.write_text("#!/usr/bin/env bash\n" + body + "\n")
                path.chmod(0o755)
            output = directory / "outputs"
            log = directory / "timeouts"
            result = subprocess.run(
                ["bash", str(ROOT / ".github/scripts/runner-wedge-probe.sh")],
                capture_output=True, text=True, timeout=4,
                env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                     "GITHUB_OUTPUT": str(output), "TEST_TIMEOUT_LOG": str(log),
                     "TEST_KERNEL_LINES": kernel},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--kill-after=1s 5s ip -4 route", log.read_text())
            self.assertIn("--kill-after=1s 10s dmesg -T", log.read_text())
            return result.stdout, output.read_text()

    def test_healthy_route_does_not_suppress_diagnostics(self):
        text, output = self.probe("exit 0")
        self.assertIn("network-stalled=false", output)
        self.assertIn("No sign", text)

    def test_term_resistant_route_is_killed_and_suppresses_network_diagnostics(self):
        text, output = self.probe("trap '' TERM\nwhile :; do sleep 1; done")
        self.assertIn("network-stalled=true", output)
        self.assertIn("did not answer", text)

    def test_missing_route_tool_is_inconclusive(self):
        text, output = self.probe("exit 127")
        self.assertIn("network-stalled=false", output)
        self.assertIn("inconclusive (exit 127)", text)

    def test_hung_task_warning_alone_does_not_suppress_network_diagnostics(self):
        text, output = self.probe("exit 0", "INFO: task kworker blocked for more than 120 seconds")
        self.assertIn("network-stalled=false", output)
        self.assertIn("Kernel hung-task lines", text)

    def test_deadline_exits_zero_when_the_probe_does_not_return(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            scripts = {
                "ip": "sleep 30",
                "sudo": "sleep 30",
                "dmesg": "sleep 30",
                # Drop the budget flags and run the command. No kill.
                "timeout": "shift 2\nexec \"$@\"",
            }
            for name, body in scripts.items():
                path = directory / name
                path.write_text("#!/usr/bin/env bash\n" + body + "\n")
                path.chmod(0o755)
            output = directory / "outputs"
            result = subprocess.run(
                ["bash", str(ROOT / ".github/scripts/runner-wedge-probe.sh")],
                capture_output=True, text=True, timeout=8,
                env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                     "GITHUB_OUTPUT": str(output), "WEDGE_PROBE_DEADLINE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("did not finish within 1s", result.stdout)
            self.assertIn("network-stalled=true", output.read_text())

    def test_both_workflows_probe_before_network_diagnostics(self):
        for workflow, job in (("test", "validate-install"), ("full-core", "validate-full-core")):
            with self.subTest(workflow=workflow):
                data = yaml.safe_load((ROOT / f".github/workflows/{workflow}.yaml").read_text())
                steps = data["jobs"][job]["steps"]
                probe = next(i for i, step in enumerate(steps) if step.get("id") == "runner-wedge")
                names = {"Disk use after the test", "Debug Output", "Node memory", "Save logs"}
                if workflow == "test":
                    names.add("CloudTAK pod details")
                else:
                    names.add("Collect Falco events when the test did not")
                for index, step in enumerate(steps):
                    if step.get("name") in names:
                        self.assertGreater(index, probe)
                        self.assertIn("steps.runner-wedge.outputs.network-stalled != 'true'", step["if"])


if __name__ == "__main__":
    unittest.main()
