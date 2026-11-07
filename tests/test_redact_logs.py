# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Rendered TAK config must not survive the log redactor."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "redact_logs",
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py",
)
redact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(redact)

# Distinctive stand-ins. They are not real credentials.
OIDC = "oidc-sentinel-value"
KEYSTORE = "keystore-sentinel-value"
TRUST = "trust-sentinel-value"
DB = "db-sentinel-value"
FORM = "form-sentinel-value"


def rendered_coreconfig():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Configuration>
  <network>
    <connector port="8447" clientAuth="false" keystore="JKS" keystoreFile="certs/files/takserver-web.jks" keystorePass="{KEYSTORE}" _name="web_https"/>
  </network>
  <repository>
    <connection url="jdbc:postgresql://takserver-postgresql:5432/cot" username="postgres" password="{DB}" />
  </repository>
  <auth>
    <oauth>
      <openIdDiscoveryConfiguration name="UDS SSO" clientId="uds-takserver" secret="{OIDC}" redirectUri="https://takserver.uds.dev/login/redirect" configurationUri="https://sso.uds.dev/realms/uds/.well-known/openid-configuration"/>
    </oauth>
  </auth>
  <security>
    <tls context="TLSv1.3"
      keymanager="SunX509"
      keystore="JKS" keystoreFile="certs/files/takserver.jks" keystorePass="{KEYSTORE}"
      truststore="JKS" truststoreFile="certs/files/truststore-root.jks" truststorePass="{TRUST}">
    </tls>
    <tls context="TLSv1.2" keystorePass='{KEYSTORE}' truststorePass='{TRUST}'/>
  </security>
</Configuration>
client_secret={FORM}&grant_type=authorization_code
"""


class RedactLogsTests(unittest.TestCase):
    def test_xml_secret_forms_are_removed_and_the_rest_stays(self):
        text, count = redact.redact_text(rendered_coreconfig())
        self.assertGreaterEqual(count, 7)
        for secret in (OIDC, KEYSTORE, TRUST, DB, FORM):
            self.assertNotIn(secret, text)
        self.assertIn('clientId="uds-takserver"', text)
        self.assertIn('context="TLSv1.3"', text)
        self.assertIn("jdbc:postgresql://takserver-postgresql:5432/cot", text)
        self.assertIn('secret="[REDACTED]"', text)
        self.assertIn("keystorePass='[REDACTED]'", text)
        self.assertIn("client_secret=[REDACTED]", text)

    def test_second_pass_does_not_nest_the_mask(self):
        once, _ = redact.redact_text(rendered_coreconfig())
        twice, count = redact.redact_text(once)
        self.assertEqual(twice, once)
        self.assertEqual(count, 0)
        self.assertNotIn("[REDACTED][REDACTED]", twice)

    def test_storepass_flags_still_redact(self):
        text, count = redact.redact_text("keytool -storepass s3cret -keypass other\n")
        self.assertGreaterEqual(count, 2)
        self.assertNotIn("s3cret", text)
        self.assertNotIn("other", text)
        self.assertIn("-storepass [REDACTED]", text)

    def test_attribute_value_with_xml_escapes_is_one_value(self):
        raw = 'secret="a&amp;b&quot;c"'
        text, count = redact.redact_text(raw)
        self.assertEqual(count, 1)
        self.assertEqual(text, 'secret="[REDACTED]"')
        self.assertNotIn("a&amp;b", text)
