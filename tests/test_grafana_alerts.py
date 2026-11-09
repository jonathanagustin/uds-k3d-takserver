# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise alert recovery with a CloudTAK dependency on ready messaging."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

CLI_STUB = r'''
import json
import os
from pathlib import Path
import signal
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_file = Path(os.environ["ALERT_TEST_STATE"])

if name == "docker":
    raise SystemExit(0)
if name == "sleep":
    # Exercise the retry contract without spending ten minutes in the test.
    raise SystemExit(0)
if name == "curl":
    url = next(arg for arg in args if arg.startswith("http://"))
    if "/api/search" in url:
        body = [{"title": "TAK Server"}]
    elif "/api/v1/rules" in url:
        body = ["TAKAPITargetDown", "TAKMessagingTargetDown", "TAKJVMHeapHigh",
                "TAKPodRestartLoop", "TAKDeploymentUnavailable", "CloudTAKTargetDown",
                "CloudTAKDeploymentUnavailable", "CloudTAKPostGISTargetDown",
                "CloudTAKPostGISUnavailable", "CloudTAKPodRestartLoop",
                "TAKCertificateExpiryWarning", "TAKCertificateExpiryCritical",
                "TAKCertificateReadFailed"]
    elif "/api/v1/targets" in url:
        body = {"data": {"activeTargets": [
            {"health": "up", "labels": {"namespace": ns, "pod": pod},
             "scrapeUrl": "http://fixture/metrics", "scrapePool": pool}
            for ns, pod, pool in (("takserver", "takserver-api-1", ""),
                                  ("takserver", "takserver-messaging-1", ""),
                                  ("pepr-system", "pepr-1", "/takserver-oidc/"))]}}
    elif "/api/v1/query" in url:
        result = [{"value": [0, "1"]}]
        if "tak_certificate_not_after_seconds" in " ".join(args):
            result = [{"metric": {"certificate": cert}, "value": [0, "1900000000"]}
                      for cert in ("ca", "server")]
        body = {"data": {"result": result}}
    elif "/api/v2/alerts" in url:
        state = json.loads(state_file.read_text())
        assert state["messaging"] == state["cloudtak"] == 0
        if os.environ.get("ALERT_TEST_ALERTS_FAIL") == "1":
            raise SystemExit(23)
        body = [{"labels": {"alertname": alert}, "status": {"state": "active"}}
                for alert in ("TAKMessagingTargetDown", "CloudTAKTargetDown")]
    else:
        body = {}
    if "-o" in args:
        Path(args[args.index("-o") + 1]).write_text(json.dumps(body))
    print("200")
    raise SystemExit(0)

assert name == "uds" and args[:3] == ["zarf", "tools", "kubectl"], args
args = args[3:]
if args[0] == "port-forward":
    signal.pause()
elif args[0] == "api-resources":
    print("prometheusrules monitoring.coreos.com/v1 true PrometheusRule")
elif args[0] == "get":
    if args[1] == "secret":
        print('{"items": []}')
    elif any("jsonpath=" in arg for arg in args):
        print("80" if "ports" in " ".join(args) else "grafana")
    else:
        print("{}")
elif args[0] in ("scale", "rollout"):
    state = json.loads(state_file.read_text())
    target = args[1] if args[0] == "scale" else args[2]
    app = "messaging" if "takserver-messaging" in target else "cloudtak"
    if args[0] == "scale":
        replicas = int(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--replicas=")))
        state[app] = replicas
        if app == "messaging" and replicas == 0:
            state["messaging_ready"] = False
        if app == "cloudtak" and replicas == 1 and not state["messaging_ready"]:
            state["premature_cloudtak_restore"] = True
        state["events"].append(["scale", app, replicas])
    else:
        if app == "cloudtak" and not state["messaging_ready"]:
            print("CloudTAK cannot become Ready while messaging is unavailable", file=sys.stderr)
            raise SystemExit(1)
        state[app + "_ready"] = True
        state["events"].append(["ready", app])
    state_file.write_text(json.dumps(state))
else:
    raise AssertionError(args)
'''


class GrafanaAlertsTests(unittest.TestCase):
    def run_script(self, alert_failure=False, script_text=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests, binary = root / "tests", root / "bin"
            tests.mkdir()
            binary.mkdir()
            script = tests / "grafana-alerts.sh"
            script.write_text(script_text or (ROOT / "tests/grafana-alerts.sh").read_text())
            router = binary / "router"
            router.write_text(f"#!{sys.executable}\n" + CLI_STUB)
            router.chmod(0o755)
            for name in ("uds", "curl", "docker", "sleep"):
                (binary / name).symlink_to(router)
            state_file = root / "state.json"
            state_file.write_text(json.dumps({
                "messaging": 1, "cloudtak": 1, "messaging_ready": True,
                "premature_cloudtak_restore": False, "events": [],
            }))
            process = subprocess.Popen(["bash", str(script)], cwd=root, env={
                **os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                "ALERT_TEST_STATE": str(state_file),
                "ALERT_TEST_ALERTS_FAIL": "1" if alert_failure else "0",
            }, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=20)
                return process.returncode, stdout + stderr, json.loads(state_file.read_text())
            finally:
                # Background mock port-forwards belong to this test's session.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.communicate(timeout=5)

    def test_messaging_is_ready_before_cloudtak_is_restored(self):
        code, output, state = self.run_script()
        self.assertEqual(code, 0, output)
        self.assertEqual((state["messaging"], state["cloudtak"]), (1, 1))
        self.assertTrue(state["messaging_ready"])
        self.assertTrue(state["cloudtak_ready"])
        self.assertFalse(state["premature_cloudtak_restore"])
        self.assertIn("TAKMessagingTargetDown and CloudTAKTargetDown are firing", output)

    def test_unavailable_alertmanager_restores_both_replica_counts(self):
        code, output, state = self.run_script(alert_failure=True)
        self.assertNotEqual(code, 0, output)
        self.assertEqual((state["messaging"], state["cloudtak"]), (1, 1))
        self.assertIn("did not both reach active in Alertmanager", output)


if __name__ == "__main__":
    unittest.main()
