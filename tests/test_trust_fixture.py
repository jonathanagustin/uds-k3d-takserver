# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise the real private-PKI fixture without deploying a cluster."""

import base64
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("trust_fixture", Path(__file__).with_name("prepare-trust-fixture.py"))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class PrivateGatewayFixtureTests(unittest.TestCase):
    def test_private_chain_config_and_cleanup(self):
        saved_root = "existing-public-certificate-data\n"
        original = {"variables": {"takserver": {"DOMAIN": "uds.dev", "TAK_IMAGE_TAG": "pinned-image"},
                                  "core-base": {"CA_BUNDLE_CERTS": base64.b64encode(saved_root.encode()).decode()}}}
        masks = []
        with tempfile.TemporaryDirectory() as parent:
            result = fixture.prepare(original, parent, masks.append)
            directory = Path(result["directory"])
            config = json.loads(Path(result["config"]).read_text())
            core = config["variables"]["core-base"]
            self.assertEqual(original["variables"]["takserver"], config["variables"]["takserver"])
            self.assertNotIn("TENANT_TLS_KEY", original["variables"]["core-base"])
            self.assertEqual(core["DOMAIN"], "uds.dev")
            root = Path(result["ca"]).read_text()
            self.assertEqual(base64.b64decode(core["CA_BUNDLE_CERTS"]).decode(), saved_root + root)
            key = base64.b64decode(core["TENANT_TLS_KEY"]).decode()
            self.assertIn(core["TENANT_TLS_KEY"], masks)
            self.assertTrue(set(key.splitlines()).issubset(masks))
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for name in ("uds-config.yaml", "tenant.key"):
                self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
            self.assertFalse((directory / "ca.key").exists())
            cert = directory / "tenant.pem"
            args = ["openssl", "verify", "-verify_hostname", "sso.uds.dev"]
            subprocess.run(args + ["-CAfile", result["ca"], str(cert)], check=True, capture_output=True)
            public = subprocess.run(args + ["-CAfile", ssl.get_default_verify_paths().cafile, str(cert)], capture_output=True)
            self.assertNotEqual(public.returncode, 0)
            self.assertIn(root, Path(result["host-ca"]).read_text())
            self.assertNotIn(key, json.dumps(result))
            fixture.cleanup(directory, parent)
            self.assertFalse(directory.exists())

    def test_rejects_invalid_domains_before_creating_files(self):
        with tempfile.TemporaryDirectory() as parent:
            for domain in ("localhost", "bad/domain", "-bad.example", "example..test"):
                with self.subTest(domain=domain), self.assertRaises(ValueError):
                    fixture.prepare({"variables": {"takserver": {"DOMAIN": domain}}}, parent)
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_cleanup_rejects_unowned_directories_and_symlinks(self):
        with tempfile.TemporaryDirectory() as parent, tempfile.TemporaryDirectory() as other:
            for target in (parent, other):
                with self.assertRaises(ValueError):
                    fixture.cleanup(target, parent)
            link = Path(parent) / (fixture.PREFIX + "link")
            link.symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                fixture.cleanup(link, parent)
            self.assertTrue(Path(other).exists())

    def test_opt_in_workflow_and_config_plumbing(self):
        repo = Path(__file__).resolve().parents[1]
        workflow = (repo / ".github/workflows/test.yaml").read_text()
        self.assertIn("--set TEST_BUNDLE_CONFIG=", workflow)
        self.assertIn("&& !(github.event_name == 'workflow_dispatch' && inputs.trust_bundle)", workflow)
        self.assertIn("config: \"${TEST_BUNDLE_CONFIG}\"", (repo / "tasks.yaml").read_text())
        self.assertIn("sensitive: true", (repo / "bundle/uds-bundle.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
