# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The denied probe must pass the pod selector but differ in identity."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BasemapProbeTests(unittest.TestCase):
    def test_denied_pod_is_selector_equivalent_and_never_a_ready_endpoint(self):
        tasks = yaml.safe_load((ROOT / "tasks/test.yaml").read_text())["tasks"]
        task = next(task for task in tasks if task["name"] == "cloudtak")
        command = task["actions"][0]["cmd"]
        generator = re.search(
            r'IMAGE="\$\{image\}" HOST="\$\{host\}" python3 -c \'(.*?)\' > /tmp/basemap-denied.json',
            command, re.DOTALL,
        )
        self.assertIsNotNone(generator, "the denied-pod generator is missing")
        result = subprocess.run(
            [sys.executable, "-c", generator[1]],
            env={**os.environ, "IMAGE": "cloudtak:test", "HOST": "tiles.example"},
            text=True, capture_output=True, check=True,
        )
        pod = json.loads(result.stdout)
        self.assertEqual(pod["metadata"]["labels"]["app"], "cloudtak")
        self.assertEqual(pod["spec"]["serviceAccountName"], "basemap-denied")
        self.assertFalse(pod["spec"]["automountServiceAccountToken"])
        container = pod["spec"]["containers"][0]
        self.assertEqual(container["image"], "cloudtak:test")
        probe = container["readinessProbe"]["exec"]["command"]
        self.assertNotEqual(subprocess.run(probe, check=False).returncode, 0)
        self.assertEqual(pod["spec"]["restartPolicy"], "Never")
        self.assertFalse(any("secret" in volume for volume in pod["spec"]["volumes"]))


if __name__ == "__main__":
    unittest.main()
