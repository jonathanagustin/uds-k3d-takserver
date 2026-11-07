# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The CoreConfig summary reports shape, never the secret values."""

import base64
import hashlib
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "summarize_coreconfig",
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "summarize-coreconfig.py",
)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)

OIDC = "oidc-sentinel-value"
KEYSTORE = "keystore-sentinel-value"
DB = "db-sentinel-value"

XML = f"""<Configuration>
  <tls context="TLSv1.3"
    keystorePass="{KEYSTORE}" truststorePass="trust-sentinel">
  </tls>
  <openIdDiscoveryConfiguration name="UDS SSO" clientId="uds-takserver" secret="{OIDC}"/>
  <connection url="jdbc:postgresql://db/cot" username="postgres" password="{DB}"/>
</Configuration>
"""


def sha8(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


class SummarizeCoreconfigTests(unittest.TestCase):
    def test_report_omits_every_secret_value(self):
        text = summary.summarize(XML)
        for secret in (OIDC, KEYSTORE, DB, "trust-sentinel"):
            self.assertNotIn(secret, text)
        self.assertIn("tls context=TLSv1.3", text)
        self.assertIn("openIdDiscovery=present", text)
        self.assertIn(f"secret=set length={len(OIDC)} sha8={sha8(OIDC)} placeholder=no", text)
        self.assertIn(f"keystorePass=set length={len(KEYSTORE)} sha8={sha8(KEYSTORE)} placeholder=no", text)
        self.assertIn(f"password=set length={len(DB)} sha8={sha8(DB)} placeholder=no", text)
        self.assertNotIn("uds-takserver", text)
        self.assertNotIn("jdbc:", text)

    def test_placeholder_is_labeled_and_not_printed(self):
        text = summary.summarize('<openIdDiscoveryConfiguration secret="${TAK_OIDC_CLIENT_SECRET}"/>')
        self.assertIn("placeholder=yes", text)
        self.assertNotIn("${TAK_OIDC_CLIENT_SECRET}", text)

    def test_non_xml_is_not_echoed(self):
        raw = "error: secret=" + OIDC
        text = summary.summarize(raw)
        self.assertEqual(text, "coreconfig: unreadable\n")
        self.assertNotIn(OIDC, text)

    def test_b64_secret_is_not_echoed(self):
        encoded = base64.b64encode(OIDC.encode("utf-8")).decode("ascii")
        text = summary.summarize_b64(encoded + "\n")
        self.assertEqual(text, f"cluster-secret length={len(OIDC)} sha8={sha8(OIDC)}\n")
        self.assertNotIn(OIDC, text)
        self.assertNotIn(encoded, text)

    def test_bad_b64_is_not_echoed(self):
        text = summary.summarize_b64("@@@not-base64@@@")
        self.assertEqual(text, "cluster-secret: unreadable\n")
        self.assertNotIn("@@@", text)
