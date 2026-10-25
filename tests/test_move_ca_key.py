# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The CA key field can be removed from a ConfigMap body without a cluster."""

import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "charts" / "takserver" / "files" / "scripts" / "move-ca-key.sh"


def strip_json(body: str) -> str:
    completed = subprocess.run(
        ["bash", "-c", 'MOVE_CA_KEY_SOURCE_ONLY=1; source "$1"; printf %s "$2" | strip_ca_key_json', "bash", str(SCRIPT), body],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


class MoveCaKeyTests(unittest.TestCase):
    def test_middle_field_is_removed(self):
        body = '{"binaryData":{"ca.pem":"YQ==","ca-do-not-share.key":"Yg==","admin.pem":"Yw=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn("ca.pem", got)
        self.assertIn("admin.pem", got)

    def test_first_field_is_removed(self):
        body = '{"binaryData":{"ca-do-not-share.key":"Yg==","ca.pem":"YQ=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn('"ca.pem":"YQ=="', got)

    def test_last_field_is_removed(self):
        body = '{"binaryData":{"ca.pem":"YQ==","ca-do-not-share.key":"Yg=="}}'
        got = strip_json(body)
        self.assertNotIn("ca-do-not-share.key", got)
        self.assertIn('"ca.pem":"YQ=="', got)


if __name__ == "__main__":
    unittest.main()
