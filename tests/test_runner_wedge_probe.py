# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Runner routing probes report timeouts without blocking later cleanup."""

import json
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

    def test_deadline_with_healthy_route_does_not_claim_a_routing_stall(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, body in {"ip": "exit 0", "sudo": "sleep 30", "timeout": "shift 2\nexec \"$@\""}.items():
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
            self.assertEqual(output.read_text().strip(), "network-stalled=false")

    def test_install_and_full_core_agent_capture_is_failure_only_after_wedge(self):
        cases = [('.github/workflows/test.yaml', 'validate-install', 'install',
                  "failure() && env.TEST_TYPE == 'install' && steps.runner-wedge.outputs.network-stalled != 'true'"),
                 ('.github/workflows/full-core.yaml', 'validate-full-core', 'full-core',
                  "failure() && steps.runner-wedge.outputs.network-stalled != 'true'")]
        for file, job, phase, condition in cases:
            steps = yaml.safe_load((ROOT / file).read_text())['jobs'][job]['steps']
            wedge = next(index for index, step in enumerate(steps) if step.get('id') == 'runner-wedge')
            selected = [index for index, step in enumerate(steps)
                        if 'upgrade-agent-diagnostics.sh' in step.get('run', '')]
            self.assertEqual(selected, [wedge + 1])
            capture = steps[selected[0]]
            self.assertEqual(capture['if'], condition)
            self.assertEqual(capture['run'], './tests/upgrade-agent-diagnostics.sh ' + phase)
            self.assertEqual(capture['timeout-minutes'], 2)
            self.assertIs(capture['continue-on-error'], True)
        test = yaml.safe_load((ROOT / '.github/workflows/test.yaml').read_text())['jobs']
        # Shared upgrade steps must not duplicate their existing boundary capture.
        for job in ('validate-upgrade', 'validate-upgrade-pg15'):
            captures = [step for step in test[job]['steps']
                        if 'upgrade-agent-diagnostics.sh' in step.get('run', '')]
            self.assertEqual(len(captures), 1)
            self.assertIn("env.TEST_TYPE == 'install'", captures[0]['if'])

    def test_cluster_runner_fallback_keeps_overrides_and_native_arm(self):
        test = yaml.safe_load((ROOT / ".github/workflows/test.yaml").read_text())["jobs"]
        full = yaml.safe_load((ROOT / ".github/workflows/full-core.yaml").read_text())["jobs"]
        bench = yaml.safe_load((ROOT / ".github/workflows/benchmark.yaml").read_text())["jobs"]
        expected = "${{ vars.TEST_RUNNER || 'ubuntu-22.04' }}"
        planner = next(step for step in test["check-flavor"]["steps"]
                       if "TEST_RUNNER" in step.get("env", {}))
        self.assertEqual(planner["env"]["TEST_RUNNER"], expected)
        # Test's upgrade matrices are planned at runtime. Exercise that actual
        # planner, retaining the runner override and native ARM contracts.
        for runner in ("", "custom-amd64-runner"):
            env = {**os.environ, "EVENT_NAME": "push", "TRUST_BUNDLE": "false",
                   "DIAGNOSTIC_CASE": "none", "TEST_RUNNER": runner}
            env.pop("GITHUB_OUTPUT", None)
            result = subprocess.run(
                ["python3", str(ROOT / ".github/scripts/test-validation-mode.py"), "plan"],
                env=env, capture_output=True, text=True, check=True)
            outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
            for name, key in (("validate-upgrade", "upgrade-matrix"),
                              ("validate-upgrade-pg15", "pg15-matrix")):
                with self.subTest(runner=runner, job=name):
                    job = test[name]
                    self.assertEqual(job["strategy"]["matrix"],
                                     "${{ fromJSON(needs.check-flavor.outputs." + key + ") }}")
                    self.assertIn("check-flavor", job["needs"])
                    rows = json.loads(outputs[key])["include"]
                    self.assertEqual([(row["arch"], row["runner"]) for row in rows],
                                     [("amd64", runner or "ubuntu-22.04"),
                                      ("arm64", "ubuntu-22.04-arm")])
                    self.assertEqual(job["runs-on"], "${{ matrix.runner }}")
        for job in (full["validate-full-core"], bench["benchmark"]):
            rows = job["strategy"]["matrix"]["include"]
            self.assertEqual([(row["arch"], row["runner"]) for row in rows],
                             [("amd64", expected), ("arm64", "ubuntu-22.04-arm")])
            self.assertEqual(job["runs-on"], "${{ matrix.runner }}")
        # Explicit hosted22 override still receives disk/swap preparation.
        for job in (test["validate-install"], full["validate-full-core"], bench["benchmark"]):
            guarded = [step for step in job["steps"]
                       if "TEST_RUNNER" in str(step.get("if", ""))]
            self.assertTrue(guarded)
            for step in guarded:
                self.assertIn("vars.TEST_RUNNER == 'ubuntu-22.04'", step["if"])
        self.assertEqual(test["check-flavor"]["runs-on"], "ubuntu-24.04")
        # Native image producers retain their existing 24.04 labels.
        for name in ("cloudtak-image", "postgis-image"):
            rows = test[name]["strategy"]["matrix"]["include"]
            self.assertEqual([row["runner"] for row in rows], ["ubuntu-24.04", "ubuntu-24.04-arm"])

    def test_cluster_python_is_explicit_and_checked_before_work(self):
        pin = "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0"
        cases = (("test", ("validate-install", "validate-upgrade", "validate-upgrade-pg15")),
                 ("full-core", ("validate-full-core",)), ("benchmark", ("benchmark",)))
        for workflow, names in cases:
            jobs = yaml.safe_load((ROOT / f".github/workflows/{workflow}.yaml").read_text())["jobs"]
            for name in names:
                with self.subTest(workflow=workflow, job=name):
                    steps = jobs[name]["steps"]
                    setups = [i for i, step in enumerate(steps) if step.get("uses") == pin]
                    self.assertEqual(len(setups), 1)
                    setup = setups[0]
                    self.assertEqual(steps[setup]["with"]["python-version"], "3.12")
                    self.assertIs(steps[setup]["with"]["check-latest"], False)
                    checks = [i for i, step in enumerate(steps)
                              if step.get("name") == "Verify test Python before cluster work"]
                    self.assertEqual(checks, [setup + 1])
                    self.assertIn("sys.version_info[:2] == (3, 12)", steps[checks[0]]["run"])
                    for i, step in enumerate(steps):
                        if "venv" in step.get("run", "") or "deploy" in step.get("run", ""):
                            self.assertLess(checks[0], i)
                    environment = next(i for i, step in enumerate(steps)
                                       if step.get("name") == "Environment setup")
                    self.assertLess(checks[0], environment)

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
