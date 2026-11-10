# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guards; genuine age proof is opt-in and keeps keys outside Git."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('staged_age', HERE / 'staged-encrypted-diagnostic.py')
AGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGE)
PUBLIC = 'age1' + 'q' * 58  # Format fixture; official age validates the checksum.


def fixture(root):
    private = root / 'staged-migrations/owner/PRIVATE-command-failure.txt'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private fixture bytes')
    private.chmod(0o600)
    output = root / 'github-output'
    output.touch()
    identity = {'sourceSHA': 'a' * 40, 'runID': '123', 'runAttempt': '1'}
    (private.parent / 'journal.json').write_text(json.dumps({'schema': 1, 'accepted': False,
        'cluster': identity, 'steps': [{'name': 'bootstrap-exemption', 'status': 'failed'}]}))
    return private, output, {'STAGED_AGE_RECIPIENT': PUBLIC, 'STAGED_TRIAL_OUTCOME': 'failure',
                             'RUNNER_TEMP': str(root), 'GITHUB_OUTPUT': str(output),
                             'GITHUB_SHA': identity['sourceSHA'], 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


class EncryptedDiagnosticGuards(unittest.TestCase):
    def test_default_empty_and_nonfailure_download_and_install_nothing(self):
        for env in ({}, {'STAGED_AGE_RECIPIENT': ''},
                    {'STAGED_AGE_RECIPIENT': PUBLIC, 'STAGED_TRIAL_OUTCOME': 'success'}):
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')), \
                    patch.object(AGE.tempfile, 'TemporaryDirectory', side_effect=AssertionError('install')):
                self.assertEqual(AGE.main(), 0)

    def test_recipient_and_fixed_private_file_guards_fail_before_download(self):
        for case in ('private-key', 'plugin', 'newline', 'missing', 'oversized', 'symlink', 'parent-link', 'fifo'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                private, output, env = fixture(root)
                if case == 'private-key':
                    env['STAGED_AGE_RECIPIENT'] = 'AGE-SECRET-KEY-DO_NOT_ECHO'
                elif case == 'plugin':
                    env['STAGED_AGE_RECIPIENT'] = 'age1plugin1DO_NOT_ECHO'
                elif case == 'newline':
                    env['STAGED_AGE_RECIPIENT'] += '\nDO_NOT_ECHO'
                elif case == 'oversized':
                    private.write_bytes(b'x' * 65537)
                elif case == 'symlink':
                    private.unlink(); private.symlink_to(root / 'foreign')
                elif case == 'parent-link':
                    private.unlink(); (private.parent / 'journal.json').unlink()
                    private.parent.rmdir(); private.parent.symlink_to(root)
                else:
                    private.unlink()
                    if case == 'fifo':
                        os.mkfifo(private)
                captured = io.StringIO()
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')), \
                        contextlib.redirect_stderr(captured):
                    self.assertEqual(AGE.main(), 1)
                self.assertEqual(output.read_bytes(), b'')
                self.assertFalse((root / AGE.OUTPUT_NAME).exists())
                self.assertNotIn('DO_NOT_ECHO', captured.getvalue())

    def test_stale_source_run_or_successful_owner_journal_cannot_encrypt(self):
        for field in ('sourceSHA', 'runID', 'runAttempt', 'accepted'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                private, output, env = fixture(root)
                journal = private.parent / 'journal.json'
                data = json.loads(journal.read_text())
                if field == 'accepted':
                    data['accepted'] = True
                else:
                    data['cluster'][field] = 'different'
                journal.write_text(json.dumps(data))
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')):
                    self.assertEqual(AGE.main(), 1)
                self.assertEqual(output.read_bytes(), b'')

    def test_identity_requires_same_repository_manual_main_actual_checkout(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=AGE.ROOT).decode().strip()
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_REPOSITORY': 'jonathanagustin/uds-takserver', 'GITHUB_SHA': head,
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        with patch.dict(os.environ, env, clear=True):
            AGE.context()
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/other'),
                           ('GITHUB_REPOSITORY', 'fork/repo'), ('GITHUB_SHA', '0' * 40),
                           ('GITHUB_RUN_ID', 'invalid'), ('GITHUB_RUN_ATTEMPT', '0')]:
            with self.subTest(key=key), patch.dict(os.environ, {**env, key: value}, clear=True), \
                    self.assertRaises(ValueError):
                AGE.context()

    def test_archive_checksum_and_nonregular_members_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                AGE.extract_age(b'corrupt', AGE.PINS['x86_64'], root)
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                member = tarfile.TarInfo('age/age')
                member.type = tarfile.SYMTYPE
                member.linkname = '/foreign'
                archive.addfile(member)
            raw = stream.getvalue()
            with self.assertRaises(ValueError):
                AGE.extract_age(raw, ('amd64', len(raw), AGE.digest(raw), 0, 'unused'), root)
            self.assertEqual(list(root.iterdir()), [])

    def test_optional_errors_preserve_existing_output_and_never_mark_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, env = fixture(root)
            destination = root / AGE.OUTPUT_NAME
            destination.mkdir()
            preserved = destination / 'first-failure.age'
            preserved.write_bytes(b'previous output')
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')):
                self.assertEqual(AGE.main(), 1)
            self.assertEqual(preserved.read_bytes(), b'previous output')
            preserved.unlink(); destination.rmdir()
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', side_effect=RuntimeError('DO_NOT_ECHO')), \
                    patch.object(AGE, 'bounded_process', side_effect=AssertionError('host-tool fallback')) as child:
                self.assertEqual(AGE.main(), 1)
            child.assert_not_called()
            self.assertEqual(output.read_bytes(), b'')
            self.assertFalse(destination.exists())

    def test_encryption_failure_and_partial_output_are_not_uploadable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, env = fixture(root)
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', return_value=(root / 'age', AGE.PINS['x86_64'])), \
                    patch.object(AGE, 'encrypt_private', side_effect=RuntimeError('DO_NOT_ECHO')):
                self.assertEqual(AGE.main(), 1)
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', return_value=(root / 'age', AGE.PINS['x86_64'])), \
                    patch.object(AGE, 'encrypt_private', return_value=b'age-encryption.org/v1\nfixture-cipher'), \
                    patch.object(AGE.os, 'write', return_value=0):
                self.assertEqual(AGE.main(), 1)
            self.assertEqual(output.read_bytes(), b'')
            self.assertFalse((root / AGE.OUTPUT_NAME).exists())

    def test_real_process_output_stderr_and_lifetime_are_bounded(self):
        for code, limit, seconds in [('print("x"*10000)', 100, 2),
                                     ('import sys;sys.stderr.write("x"*5000)', 100, 2),
                                     ('import time;time.sleep(30)', 100, 0.1)]:
            started = time.monotonic()
            with self.assertRaises(ValueError):
                AGE.bounded_process([sys.executable, '-c', code], limit=limit, seconds=seconds)
            self.assertLess(time.monotonic() - started, 5)

    def test_workflow_only_uploads_ciphertext_after_failed_trial_successful_encryption(self):
        # String checks keep this Unit step stdlib-only.
        workflow = (AGE.ROOT / '.github/workflows/staged-migrations.yaml').read_text()
        self.assertIn('diagnostic_recipient:', workflow)
        self.assertIn('default: ""', workflow.split('diagnostic_recipient:', 1)[1].split('permissions:', 1)[0])
        encrypt = workflow.split('- name: Encrypt optional first failure diagnostic', 1)[1]
        self.assertIn("steps.staged-trial.outcome == 'failure' && inputs.diagnostic_recipient != ''", encrypt)
        self.assertIn('STAGED_AGE_RECIPIENT: ${{ inputs.diagnostic_recipient }}', encrypt)
        upload = encrypt.split('- name: Upload only encrypted first failure diagnostic', 1)[1].split('  summary:', 1)[0]
        self.assertIn("steps.encrypt-first-failure.outcome == 'success'", upload)
        self.assertIn("steps.encrypt-first-failure.outputs.ready == 'true'", upload)
        self.assertIn('path: ${{ runner.temp }}/staged-encrypted-diagnostic/first-failure.age', upload)
        self.assertNotIn('PRIVATE-command-failure.txt', upload)
        self.assertNotIn('**', upload)


@unittest.skipUnless(os.environ.get('STAGED_AGE_ARCHIVE') and os.environ.get('STAGED_AGE_KEYGEN'),
                     'opt-in official age archive/keygen required for genuine roundtrip')
class GenuineAgeProof(unittest.TestCase):
    def test_real_official_keygen_encrypt_decrypt_wrong_key_and_integrity(self):
        pin = AGE.PINS['x86_64']
        archive = Path(os.environ['STAGED_AGE_ARCHIVE']).read_bytes()
        keygen = Path(os.environ['STAGED_AGE_KEYGEN'])
        self.assertEqual(AGE.digest(keygen.read_bytes()),
                         '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899')
        with tempfile.TemporaryDirectory(prefix='staged-age-proof-') as temporary:
            root = Path(temporary)
            self.assertNotIn(AGE.ROOT, root.parents)
            private, output, env = fixture(root)
            plain = (b'fixture private failure\x00' * 3000)[:AGE.INPUT_LIMIT]
            private.write_bytes(plain)
            for name in ('correct', 'wrong'):
                key = root / (name + '.key')
                subprocess.run([str(keygen), '-o', str(key)], capture_output=True, timeout=10, check=True)
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            recipient = subprocess.run([str(keygen), '-y', str(root / 'correct.key')],
                                       capture_output=True, timeout=10, check=True).stdout.decode().strip()
            self.assertTrue(AGE.RECIPIENT.fullmatch(recipient))
            env['STAGED_AGE_RECIPIENT'] = recipient
            env.update(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
                       GITHUB_REPOSITORY='jonathanagustin/uds-takserver',
                       GITHUB_SHA=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=AGE.ROOT).decode().strip())
            journal = private.parent / 'journal.json'
            metadata = json.loads(journal.read_text())
            metadata['cluster']['sourceSHA'] = env['GITHUB_SHA']
            journal.write_text(json.dumps(metadata))
            def acquire(directory):
                return AGE.extract_age(archive, pin, directory), pin
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(AGE, 'acquire_age', side_effect=acquire):
                self.assertEqual(AGE.main(), 0)
            cipher = root / AGE.OUTPUT_NAME / 'first-failure.age'
            self.assertEqual(output.read_bytes(), b'ready=true\n')
            self.assertEqual(cipher.stat().st_mode & 0o777, 0o600)
            self.assertLessEqual(cipher.stat().st_size, AGE.CIPHER_LIMIT)
            self.assertEqual(private.read_bytes(), plain)
            self.assertEqual([p.name for p in cipher.parent.iterdir()], ['first-failure.age'])
            tools = root / 'decrypt-tools'; tools.mkdir()
            binary = AGE.extract_age(archive, pin, tools)
            decrypted = subprocess.run([str(binary), '--decrypt', '-i', str(root / 'correct.key'), str(cipher)],
                                       capture_output=True, timeout=10, check=True)
            self.assertTrue(decrypted.stdout == plain)
            wrong = subprocess.run([str(binary), '--decrypt', '-i', str(root / 'wrong.key'), str(cipher)],
                                   capture_output=True, timeout=10)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertEqual(wrong.stdout, b'')
            self.assertEqual(AGE.digest(keygen.read_bytes()),
                             '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899')
            changed = bytearray(binary.read_bytes()); changed[-1] ^= 1
            binary.write_bytes(changed)
            fd = AGE.regular_descriptor(private, AGE.INPUT_LIMIT)
            try:
                with self.assertRaises(ValueError), patch.object(AGE, 'bounded_process', side_effect=AssertionError('execute')):
                    AGE.encrypt_private(binary, pin, fd, recipient, tools)
            finally:
                os.close(fd)


if __name__ == '__main__':
    unittest.main()
