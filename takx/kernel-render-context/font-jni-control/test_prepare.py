# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Source-only guards; no compiler, Java VM or source download."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('font_source_control', Path(__file__).with_name('prepare.py'))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class FontSourceGuards(unittest.TestCase):
    def test_default_verify_has_no_process_or_runtime_acceptance(self):
        with patch.object(P.subprocess, 'run', side_effect=AssertionError('no process')), \
                patch('sys.argv', ['prepare.py']):
            P.main()
        lock, _ = P.contract()
        self.assertEqual(len(lock['files']), 3)
        self.assertFalse(lock['runtime_accepted'])
        self.assertFalse(lock['stock_source_binary_equivalence'])

    def test_unqualified_flags_membership_or_digest_are_refused(self):
        original = P.regular
        lock, _ = P.contract()
        for change in ('accepted', 'binary-equivalence', 'source', 'patch'):
            value = copy.deepcopy(lock)
            if change == 'accepted':
                value['runtime_accepted'] = True
            elif change == 'binary-equivalence':
                value['stock_source_binary_equivalence'] = True
            elif change == 'source':
                value['files'].pop(next(iter(value['files'])))
            else:
                value['patch_sha256'] = '0' * 64
            def read(path):
                return json.dumps(value).encode() if path.name == 'inputs.lock.json' else original(path)
            with self.subTest(change=change), patch.object(P, 'regular', side_effect=read), self.assertRaises(ValueError):
                P.contract()

    def test_source_drift_creates_no_output_or_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'source', root / 'output'
            for name in P.FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'wrong official source')
            with patch.object(P.subprocess, 'run', side_effect=AssertionError('no process')), self.assertRaises(ValueError):
                P.prepare(source, output)
            self.assertFalse(output.exists())

    def test_symlinks_existing_outputs_and_source_overlap_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            alias = root / 'alias'
            alias.symlink_to(source, target_is_directory=True)
            for before, after in ((alias, root / 'out'), (source, source / 'out'), (source, P.HERE / 'out')):
                with self.subTest(before=before, after=after), self.assertRaises(ValueError):
                    P.prepare(before, after)
            existing = root / 'existing'
            existing.mkdir()
            with self.assertRaises(ValueError):
                P.prepare(source, existing)
