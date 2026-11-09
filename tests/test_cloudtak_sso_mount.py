# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The rendered SSO container must see the live Core bundle and the TAK CA."""

from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class CloudTakSsoMountTests(unittest.TestCase):
    def test_rendered_sso_container_mounts_the_live_bundle_and_tak_ca(self):
        rendered = subprocess.check_output(
            ["helm", "template", "cloudtak", "charts/cloudtak", "--namespace", "cloudtak"],
            cwd=ROOT, text=True)
        deployment = next(
            doc for doc in yaml.safe_load_all(rendered)
            if doc and doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "cloudtak")
        pod = deployment["spec"]["template"]["spec"]
        sso = next(container for container in pod["containers"] if container["name"] == "sso")
        mounts = {mount["name"]: mount for mount in sso["volumeMounts"]}
        self.assertEqual(mounts["uds-trust"]["mountPath"], "/var/run/uds-trust")
        self.assertIs(mounts["uds-trust"]["readOnly"], True)
        self.assertEqual(mounts["tak-ca"]["mountPath"], "/var/run/tak-ca")
        self.assertIs(mounts["tak-ca"]["readOnly"], True)
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        bundle = volumes["uds-trust"]["configMap"]
        self.assertEqual(bundle["name"], "uds-trust-bundle")
        self.assertIs(bundle["optional"], True)
        tak = volumes["tak-ca"]["secret"]
        self.assertEqual(tak["secretName"], "cloudtak-tak-admin")
        self.assertEqual(tak["items"], [{"key": "ca.pem", "path": "ca.pem"}])


if __name__ == "__main__":
    unittest.main()
