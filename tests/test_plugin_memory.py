# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The plugins patch reads memory from Helm values. No cluster required."""

import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_patch():
    path = ROOT / "charts/takserver/files/scripts/patch-oidc-pods.py"
    spec = importlib.util.spec_from_file_location("patch_oidc_pods", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patch = load_patch()


class PluginMemoryTests(unittest.TestCase):
    def test_missing_memory_uses_the_measured_default(self):
        request, limit = patch.parse_plugin_memory({"takserver": {"plugins": {"resources": {"requests": {"cpu": "25m"}}}}})
        self.assertEqual(request, "320Mi")
        self.assertEqual(limit, "512Mi")

    def test_a_profile_overrides_the_memory(self):
        payload = {
            "takserver": {
                "plugins": {
                    "resources": {
                        "requests": {"cpu": "25m", "memory": "256Mi"},
                        "limits": {"cpu": "250m", "memory": "384Mi"},
                    }
                }
            }
        }
        self.assertEqual(patch.parse_plugin_memory(payload), ("256Mi", "384Mi"))

    def test_a_bad_size_is_refused(self):
        with self.assertRaises(SystemExit):
            patch.parse_plugin_memory({
                "takserver": {"plugins": {"resources": {"limits": {"memory": "512Mi; rm"}}}},
            })

    def test_empty_and_null_payloads_use_the_default(self):
        self.assertEqual(patch.parse_plugin_memory({}), ("320Mi", "512Mi"))
        self.assertEqual(patch.parse_plugin_memory(None), ("320Mi", "512Mi"))

    def test_shipped_values_are_sizes_the_patch_accepts(self):
        for relative in ("values/common-values.yaml", "bundle/test-values.yaml"):
            with open(ROOT / relative, encoding="utf-8") as handle:
                body = yaml.safe_load(handle)
            request, limit = patch.parse_plugin_memory(body)
            self.assertEqual(request, "320Mi", relative)
            self.assertEqual(limit, "512Mi", relative)

    def test_helm_command_prefers_a_real_helm(self):
        original = patch.shutil_which

        def which(name):
            if name == "helm":
                return "/usr/bin/helm"
            return None

        patch.shutil_which = which
        try:
            self.assertEqual(patch.helm_cmd(), ["helm"])
        finally:
            patch.shutil_which = original

    def test_helm_command_uses_uds_when_helm_is_absent(self):
        original = patch.shutil_which

        def which(name):
            if name == "uds":
                return "/usr/bin/uds"
            return None

        patch.shutil_which = which
        try:
            self.assertEqual(patch.helm_cmd(), ["uds", "zarf", "tools", "helm"])
        finally:
            patch.shutil_which = original


if __name__ == "__main__":
    unittest.main()
