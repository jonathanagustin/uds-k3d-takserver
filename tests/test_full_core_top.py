# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Parser fixtures for the full-core top check. These are not cluster measurements."""

import importlib.util
import json
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "full_core_top",
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "full-core-top.py",
)
top = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(top)


def pod(name, memory_limit, phase="Running", ready=True):
    return {
        "metadata": {"name": name},
        "spec": {"containers": [{"name": "app", "resources": {"limits": {"memory": memory_limit}}}]},
        "status": {
            "phase": phase,
            "containerStatuses": [{"name": "app", "ready": ready}],
        },
    }


class FullCoreTopTests(unittest.TestCase):
    def test_parse_top_accepts_millicores_and_mebibytes(self):
        rows, errors = top.parse_top("pod-a   10m   100Mi\n")
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["cpu"], "10m")
        self.assertEqual(rows[0]["memory_bytes"], 100 * 2**20)

    def test_parse_top_skips_comments_and_headers(self):
        rows, errors = top.parse_top("# kubectl top pods -n demo\nNAME  CPU  MEMORY\npod-a  1m  1Mi\n")
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)

    def test_parse_top_rejects_a_blank_measurement(self):
        rows, errors = top.parse_top("pod-a   <unknown>   <unknown>\n")
        self.assertEqual(rows, [])
        self.assertTrue(errors)

    def test_ready_pods_ignores_succeeded_jobs(self):
        body = {"items": [pod("job-a", "32Mi", phase="Succeeded"), pod("app-a", "32Mi")]}
        count, problems = top.ready_pods(body)
        self.assertEqual(count, 1)
        self.assertEqual(problems, [])

    def test_ready_pods_fails_when_nothing_is_ready(self):
        count, problems = top.ready_pods({"items": [pod("app-a", "32Mi", ready=False)]})
        self.assertEqual(count, 0)
        self.assertTrue(problems)

    def test_usage_over_the_limit_fails(self):
        pods = {"demo": {"items": [pod("pod-a", "64Mi")]}}
        lines, errors = top.check_top("pod-a   5m   128Mi\n", pods)
        self.assertTrue(lines)
        self.assertTrue(any("over the sum" in error for error in errors))

    def test_usage_under_the_limit_passes(self):
        pods = {"demo": {"items": [pod("pod-a", "256Mi")]}}
        _lines, errors = top.check_top("pod-a   5m   64Mi\n", pods)
        self.assertEqual(errors, [])

    def test_asserted_resources_must_match_the_startup_task(self):
        body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"resources": {"limits": {"memory": "1Mi"}, "requests": {"memory": "1Mi"}}}
                        ]
                    }
                }
            }
        }
        workloads = {
            ("statefulset", "takserver-ignite"): body,
            ("deployment", "takserver-plugins"): body,
            ("deployment", "takserver-config"): body,
        }
        _lines, errors = top.check_asserted(workloads)
        self.assertEqual(len(errors), 4)
        encoded = json.dumps(top.ASSERTED)
        self.assertIn("1536Mi", encoded)
        self.assertIn("512Mi", encoded)
        self.assertIn("384Mi", encoded)


if __name__ == "__main__":
    unittest.main()
