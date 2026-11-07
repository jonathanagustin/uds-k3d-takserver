# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Rendered TAK config must not survive the log redactor."""

import gzip
import importlib.util
import os
import stat
import subprocess
import tempfile
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

    def test_escaped_quotes_match_values_that_cross_lines(self):
        half1, half2 = OIDC[:8], OIDC[8:]
        forms = (
            f'secret=&quot;{half1}\n{half2}&quot;\n',
            f"secret=&apos;{half1}\n{half2}&apos;\n",
            f'secret=\\"{half1}\n{half2}\\"\n',
        )
        for raw in forms:
            text, count = redact.redact_text(raw)
            self.assertGreaterEqual(count, 1, raw)
            self.assertNotIn(OIDC, text)
            self.assertNotIn(half1, text)
            self.assertNotIn(half2, text)
            self.assertIn("[REDACTED]", text)

    def test_html_escaped_and_backslash_quotes(self):
        raw = (
            f'secret=&quot;{OIDC}&quot;\n'
            f'secret=\\"{OIDC}\\"\n'
            f'secret=&apos;{OIDC}&apos;\n'
        )
        text, _count = redact.redact_text(raw)
        self.assertNotIn(OIDC, text)
        self.assertIn("&quot;[REDACTED]&quot;", text)
        self.assertIn('\\"[REDACTED]\\"', text)
        self.assertIn("&apos;[REDACTED]&apos;", text)

    def test_unquoted_env_and_jvm_credentials(self):
        raw = (
            f"TAK_OIDC_CLIENT_SECRET={OIDC}\n"
            f"OIDC_CLIENT_SECRET={OIDC}\n"
            f"CAPASS={KEYSTORE}\n"
            f"-Djavax.net.ssl.keyStorePassword={KEYSTORE}\n"
            f"clientId=uds-takserver\n"
        )
        text, _count = redact.redact_text(raw)
        self.assertNotIn(OIDC, text)
        self.assertNotIn(KEYSTORE, text)
        self.assertIn("TAK_OIDC_CLIENT_SECRET=[REDACTED]", text)
        self.assertIn("-Djavax.net.ssl.keyStorePassword=[REDACTED]", text)
        self.assertIn("clientId=uds-takserver", text)

    def test_stdout_nul_does_not_pass_the_secret_through(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py"
        blob = f'secret="{OIDC}"\n'.encode("utf-8") + b"\0" + OIDC.encode("utf-8")
        result = subprocess.run(
            ["python3", str(script), "-"],
            input=blob,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(OIDC.encode("utf-8"), result.stdout)
        self.assertNotIn(b"\0", result.stdout)

    def test_rewrite_replaces_nul_file_and_exits_nonzero(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py"
        folder = Path(__file__).resolve().parents[1] / "tests"
        target = folder / ".redact-nul-fixture.log"
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        target.write_bytes(f'secret="{OIDC}"'.encode("utf-8") + b"\0")
        result = subprocess.run(
            ["python3", str(script), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        body = target.read_bytes()
        self.assertNotIn(OIDC.encode("utf-8"), body)
        self.assertNotIn(b"\0", body)

    def test_multiline_secret_is_removed_before_a_tail_could_split_it(self):
        raw = f'level=error secret="{OIDC[:8]}\n{OIDC[8:]}"\nkept\n'
        text, count = redact.redact_text(raw)
        self.assertGreaterEqual(count, 1)
        self.assertNotIn(OIDC, text)
        self.assertNotIn(OIDC[:8], text)
        self.assertNotIn(OIDC[8:], text)
        self.assertIn('secret="[REDACTED]"', text)
        self.assertIn("kept", text)

    def test_archive_bytes_are_not_left_in_place(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "api.log.gz"
            target.write_bytes(gzip.compress(f'secret="{OIDC}"\n'.encode("utf-8")))
            result = subprocess.run(
                ["python3", str(script), str(target)],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            body = target.read_bytes()
            self.assertNotIn(OIDC.encode("utf-8"), body)
            self.assertIn(b"omitted: unsanitizable file", body)

    def test_symlink_target_outside_the_tree_is_not_read_or_modified(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            secret = outside / "hid.log"
            secret.write_text(f'secret="{OIDC}"\n', encoding="utf-8")
            link = root / "link.log"
            link.symlink_to(secret)
            nested = root / "nested"
            nested.mkdir()
            (nested / "via-dir").symlink_to(outside, target_is_directory=True)
            result = subprocess.run(
                ["python3", str(script), str(link), str(nested)],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(secret.read_text(encoding="utf-8"), f'secret="{OIDC}"\n')
            self.assertFalse(link.is_symlink())
            self.assertNotIn(OIDC, link.read_text(encoding="utf-8"))
            self.assertFalse((nested / "via-dir").is_symlink())
            self.assertNotIn(OIDC, (nested / "via-dir").read_text(encoding="utf-8"))

    def test_fifo_is_not_opened(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-logs.py"
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "pipe.log"
            os.mkfifo(fifo)
            result = subprocess.run(
                ["timeout", "5", "python3", str(script), str(fifo)],
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 124)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(OIDC.encode("utf-8"), result.stdout)
            self.assertFalse(stat.S_ISFIFO(os.lstat(fifo).st_mode))
            self.assertIn(b"omitted: unsanitizable file", fifo.read_bytes())

    def test_directory_listing_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "a.log"
            secret.write_text(f'secret="{OIDC}"\n', encoding="utf-8")
            real = redact.os.walk

            def boom(path, topdown=True, onerror=None, followlinks=False):
                if onerror is not None:
                    onerror(OSError(13, "denied", str(path)))
                return iter(())

            redact.os.walk = boom
            try:
                code = redact.main([str(root)])
            finally:
                redact.os.walk = real
            self.assertEqual(code, 1)
            self.assertEqual(secret.read_text(encoding="utf-8"), f'secret="{OIDC}"\n')

    def test_shell_filter_is_not_run_with_python(self):
        script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "redact-then-filter.sh"
        raw = f'secret="{OIDC}"\n'.encode("utf-8")
        as_python = subprocess.run(
            ["python3", str(script)],
            input=raw,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(as_python.returncode, 0)
        self.assertNotIn(OIDC.encode("utf-8"), as_python.stdout)
        as_shell = subprocess.run(
            ["bash", str(script)],
            input=raw,
            capture_output=True,
            check=False,
        )
        self.assertEqual(as_shell.returncode, 0)
        self.assertNotIn(OIDC.encode("utf-8"), as_shell.stdout)
        self.assertIn(b"[REDACTED]", as_shell.stdout)
