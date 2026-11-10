# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guards for the standalone real-JNI TLS runner; no networking."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import traceback
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('tls_runner', Path(__file__).with_name('test-tls.py'))
TLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TLS)


class TlsRunnerGuards(unittest.TestCase):
    def test_exact_staged_source_and_change_missing_or_link_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected, actual = root / 'expected', root / 'actual'
            expected.mkdir(); actual.mkdir()
            (expected / 'source.cpp').write_text('actual source fixture')
            (actual / 'source.cpp').write_text('actual source fixture')
            self.assertEqual(set(TLS.verify_staged(expected, actual)), {'source.cpp'})
            (actual / 'source.cpp').write_text('changed source')
            with self.assertRaises(ValueError): TLS.verify_staged(expected, actual)
            (actual / 'source.cpp').unlink()
            with self.assertRaises(ValueError): TLS.verify_staged(expected, actual)
            (actual / 'source.cpp').symlink_to(expected / 'source.cpp')
            with self.assertRaises(ValueError): TLS.verify_staged(expected, actual)

    def test_timeout_launch_and_failure_do_not_serialize_password_or_output(self):
        sentinel = 'PRIVATE_PASSWORD_OR_KEY_SENTINEL'
        errors = [subprocess.TimeoutExpired(['openssl', sentinel], 1, output=sentinel, stderr=sentinel),
                  OSError(sentinel)]
        for error in errors:
            with self.subTest(error=type(error).__name__), mock.patch.object(TLS.subprocess, 'run', side_effect=error):
                try: TLS.run('credential operation', ['openssl', sentinel])
                except RuntimeError as failure:
                    self.assertNotIn(sentinel, str(failure) + traceback.format_exc())
                else: self.fail('launch failure was accepted')
        result = subprocess.CompletedProcess(['openssl', sentinel], 9, stdout=sentinel, stderr=sentinel)
        with mock.patch.object(TLS.subprocess, 'run', return_value=result):
            try: TLS.run('credential operation', ['openssl', sentinel])
            except RuntimeError as failure:
                self.assertEqual(str(failure), 'credential operation: exit 9')
                self.assertNotIn(sentinel, traceback.format_exc())
            else: self.fail('failed command was accepted')

    def test_mismatch_certificates_share_trusted_ca_and_use_distinct_san_types(self):
        calls = []
        extensions = {}
        def record(label, args, env=None, timeout=30):
            calls.append(args)
            if "-extfile" in args:
                extension = Path(args[args.index("-extfile") + 1])
                extensions[extension.stem] = extension.read_text()
            return ""
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(TLS, "run", side_effect=record):
            root = Path(temporary)
            TLS.credentials(root, {"TAKX_TLS_PASSWORD": "fixture-password"})
            signings = [args for args in calls if args[1:3] == ["x509", "-req"]]
            self.assertEqual(len(signings), 6)
            self.assertTrue(all(args[args.index("-CA") + 1] == str(root / "ca.crt") for args in signings))
        self.assertIn("subjectAltName=IP:127.0.0.1,DNS:localhost", extensions["server"])
        self.assertIn("subjectAltName=IP:127.0.0.1,DNS:wrong.example", extensions["wrong-dns"])
        self.assertIn("subjectAltName=IP:127.0.0.2,DNS:localhost", extensions["wrong-ip"])
        self.assertIn("subjectAltName=DNS:127.0.0.1", extensions["dns-ip"])
        self.assertNotIn("subjectAltName", extensions["cn-only"])
        self.assertTrue(all("extendedKeyUsage=serverAuth" in extensions[name]
                            for name in ("server", "wrong-dns", "wrong-ip", "dns-ip", "cn-only")))
        self.assertIn("extendedKeyUsage=clientAuth", extensions["client"])
        self.assertFalse(any("fixture-password" in arg for args in calls for arg in args))

    def test_success_preserves_actual_stdout_and_enforces_bounded_timeout(self):
        result = subprocess.CompletedProcess(['tool'], 0, stdout='actual output', stderr='')
        with mock.patch.object(TLS.subprocess, 'run', return_value=result) as command:
            self.assertEqual(TLS.run('bounded operation', ['tool'], timeout=7), 'actual output')
            self.assertEqual(command.call_args.kwargs['timeout'], 7)
            self.assertTrue(command.call_args.kwargs['capture_output'])


if __name__ == '__main__':
    unittest.main()
