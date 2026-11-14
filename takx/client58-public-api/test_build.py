# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline profile guards; real Java controls are explicit and separately bound."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('vehicle_profile', Path(__file__).with_name('build.py'))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class Guards(unittest.TestCase):
    def test_default_verification_cannot_start_a_process(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no process')), patch('sys.argv', ['build.py']):
            P.main()
        self.assertFalse(P.contract()['full_client_accepted'])

    def test_acceptance_and_foreign_source_membership_are_refused(self):
        for mutation in ('acceptance', 'membership', 'source'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for name in [*P.contract()['owned'], 'inputs.lock.json']:
                    dest = root / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(P.HERE / name, dest)
                lock = json.loads((root / 'inputs.lock.json').read_text())
                if mutation == 'acceptance':
                    lock['full_client_accepted'] = True
                elif mutation == 'membership':
                    lock['owned']['foreign.java'] = '0' * 64
                else:
                    (root / P.SOURCE).write_text('unreviewed source')
                (root / 'inputs.lock.json').write_text(json.dumps(lock))
                with patch.object(P, 'HERE', root), self.assertRaises(ValueError):
                    P.contract()

    def test_changed_or_symlinked_java_proof_is_refused_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'receipt.json').write_text('{}')
            args = SimpleNamespace(java_proof=root, java_proof_sha256='0' * 64,
                                   java_home=root / 'missing-jdk', output=root / 'output')
            with patch('subprocess.Popen', side_effect=AssertionError('no process')), self.assertRaises(ValueError):
                P.controls(args)
            self.assertFalse(args.output.exists())
            alias = root / 'alias'
            alias.symlink_to(root, target_is_directory=True)
            args.java_proof = alias
            with self.assertRaises(ValueError):
                P.controls(args)

    def test_path_digest_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'real').write_bytes(b'input')
            (root / 'link').symlink_to(root / 'real')
            with self.assertRaises(ValueError):
                P.sha(root / 'link')
