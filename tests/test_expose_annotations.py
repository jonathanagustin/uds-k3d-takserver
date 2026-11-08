# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Render Portal defaults and bundle overrides without an upstream chart."""

import base64
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("helm"), "helm CLI is not installed")
class ExposeAnnotationsTests(unittest.TestCase):
    def render(self, chart, overrides=None):
        result = subprocess.run(
            ["helm", "template", chart, str(ROOT / "charts" / chart), "-f", "-"],
            input=yaml.safe_dump({"exposeAnnotations": overrides or {}}),
            text=True, capture_output=True, check=True,
        )
        package = next(doc for doc in yaml.safe_load_all(result.stdout)
                       if doc and doc.get("kind") == "Package")
        return {entry["description"]: entry.get("annotations", {})
                for entry in package["spec"]["network"]["expose"]}

    def test_defaults_include_distinct_cloudtak_icon(self):
        self.assertEqual(self.render("takserver")["tak-web-http"],
                         {"uds.dev/title": "TAK Server"})
        annotations = self.render("cloudtak")["cloudtak-map"]
        self.assertEqual(annotations["uds.dev/title"], "CloudTAK")
        prefix, encoded = annotations["uds.dev/icon"].split(",", 1)
        self.assertEqual(prefix, "data:image/svg+xml;base64")
        self.assertEqual(base64.b64decode(encoded),
                         (ROOT / "charts/cloudtak/files/icon.svg").read_bytes())

    def test_overrides_merge_defaults_and_preserve_hidden_entries(self):
        overrides = {"uds.dev/title": "Operations", "portal.uds.dev/test": "example"}
        for chart, browser in (("takserver", "tak-web-http"), ("cloudtak", "cloudtak-map")):
            with self.subTest(chart=chart):
                entries = self.render(chart, overrides)
                for key, value in overrides.items():
                    self.assertEqual(entries[browser][key], value)
                for name, annotations in entries.items():
                    if name != browser:
                        self.assertEqual(annotations, {"uds.dev/visible": "false"})
                if chart == "cloudtak":
                    self.assertTrue(entries[browser]["uds.dev/icon"].startswith("data:image/svg+xml;base64,"))

    def test_icon_can_be_replaced(self):
        annotations = self.render("cloudtak", {"uds.dev/icon": "https://example.com/map.svg"})
        self.assertEqual(annotations["cloudtak-map"]["uds.dev/icon"], "https://example.com/map.svg")


if __name__ == "__main__":
    unittest.main()
