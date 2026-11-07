# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""An unrelated, stale, redirecting, or unauthenticated probe cannot pass."""

import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("atak_uptime", ROOT / "atak/ci/uptime-probe.py")
uptime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uptime)
TARGET = "https://atak.uds.dev/phone.html"
NOW = 1_800_000_000


def vector():
    return {
        "status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"__name__": name, "instance": TARGET}, "value": [NOW, value]}
            for name, value in uptime.METRICS.items()
        ]},
    }


class AtakUptimeTests(unittest.TestCase):
    def test_authenticated_probe_targets_the_viewer_page(self):
        probe = {"spec": {"module": uptime.MODULE, "targets": {"staticConfig": {"static": [TARGET]}}}}
        uptime.validate_probe(probe, TARGET)
        for module in ("http_2xx", "http_200x_sso_cloudtak_other-client", None):
            changed = copy.deepcopy(probe)
            changed["spec"]["module"] = module
            with self.subTest(module=module), self.assertRaises(ValueError):
                uptime.validate_probe(changed, TARGET)
        probe["spec"]["targets"]["staticConfig"]["static"] = ["https://sso.uds.dev/"]
        with self.assertRaises(ValueError):
            uptime.validate_probe(probe, TARGET)

    def test_fresh_metrics_require_all_three_success_conditions(self):
        self.assertEqual(len(uptime.validate_metrics(vector(), TARGET, NOW)), 3)
        for name, bad in (("probe_success", "0"), ("probe_http_status_code", "302"), ("probe_http_redirects", "1")):
            response = vector()
            next(row for row in response["data"]["result"] if row["metric"]["__name__"] == name)["value"][1] = bad
            with self.subTest(metric=name), self.assertRaises(ValueError):
                uptime.validate_metrics(response, TARGET, NOW)

    def test_missing_wrong_target_stale_and_failed_queries_are_rejected(self):
        responses = [
            {"status": "error", "data": {}},
            {"status": "success", "data": {"resultType": "matrix", "result": []}},
            {"status": "success", "data": {"resultType": "vector", "result": []}},
        ]
        for mutate in (
            lambda row: row["metric"].update(instance="https://sso.uds.dev/"),
            lambda row: row.update(value=[NOW - 121, "1"]),
            lambda row: row.update(value=[NOW + 1, "1"]),
        ):
            response = vector()
            mutate(response["data"]["result"][0])
            responses.append(response)
        for response in responses:
            with self.subTest(response=response), self.assertRaises(ValueError):
                uptime.validate_metrics(response, TARGET, NOW)


if __name__ == "__main__":
    unittest.main()
