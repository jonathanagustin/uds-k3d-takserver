# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Classifier for the ATAK viewer probe_success series. No cluster required."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def load():
    path = Path(__file__).resolve().parents[1] / "tests" / "atak_probe.py"
    spec = importlib.util.spec_from_file_location("atak_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load()


class AtakProbeTests(unittest.TestCase):
    def test_the_phone_page_series_is_kept(self):
        payload = {
            "data": {
                "result": [
                    {"metric": {"instance": "https://takserver.uds.dev/"}, "value": [1, "1"]},
                    {"metric": {"instance": "https://atak.uds.dev/phone.html"}, "value": [1, "1"]},
                    {"metric": {"instance": "https://map.uds.dev/login"}, "value": [1, "0"]},
                ]
            }
        }
        self.assertEqual(
            probe.viewer_series(payload),
            [("1", "https://atak.uds.dev/phone.html")],
        )

    def test_a_response_without_the_viewer_is_empty(self):
        payload = {"data": {"result": [{"metric": {"instance": "https://atak.uds.dev/"}, "value": [1, "1"]}]}}
        self.assertEqual(probe.viewer_series(payload), [])

    def test_main_prints_the_series(self):
        payload = {
            "data": {
                "result": [
                    {"metric": {"instance": "https://atak.uds.dev/phone.html"}, "value": [1, "1"]},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = probe.main(["atak_probe.py", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue(), "1 https://atak.uds.dev/phone.html\n")

    def test_main_returns_2_when_the_viewer_is_absent(self):
        payload = {"data": {"result": [{"metric": {"instance": "https://atak.uds.dev/"}, "value": [1, "1"]}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code = probe.main(["atak_probe.py", str(path)])
        self.assertEqual(code, 2)

    def test_all_prints_every_series(self):
        payload = {
            "data": {
                "result": [
                    {"metric": {"instance": "https://takserver.uds.dev/"}, "value": [1, "1"]},
                    {"metric": {"instance": "https://atak.uds.dev/phone.html"}, "value": [1, "0"]},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = probe.main(["atak_probe.py", "--all", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("1 https://takserver.uds.dev/", buffer.getvalue())
        self.assertIn("0 https://atak.uds.dev/phone.html", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
