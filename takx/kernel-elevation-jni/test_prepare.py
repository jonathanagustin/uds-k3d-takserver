# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Source scope and no-launch boundaries; no native or Java execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('elevation_prepare', HERE / 'prepare.py')
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


class SourceGuards(unittest.TestCase):
    def test_default_never_prepares_or_launches(self):
        with patch.object(P, 'prepare', side_effect=AssertionError('must not prepare')):
            P.main([])
        for argv in (['--source', '/missing'], ['--phase', 'prepare']):
            with self.assertRaises(ValueError):
                P.main(argv)

    def test_contract_refuses_scope_change_and_acceptance_escalation(self):
        for field, value in (('files', {'../foreign.cpp': {}}), ('strict_elevation_accepted', True)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'profile'
                shutil.copytree(HERE, root)
                path = root / 'inputs.lock.json'
                lock = json.loads(path.read_text())
                lock[field] = value
                path.write_text(json.dumps(lock))
                with patch.object(P, 'HERE', root), self.assertRaises(ValueError):
                    P.contract()

    def test_wrong_source_refuses_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            for name in P.FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unreviewed source')
            output = root / 'output'
            with self.assertRaisesRegex(ValueError, 'official source bytes'):
                P.prepare(source, output)
            self.assertFalse(output.exists())

    def test_symlink_and_overlapping_outputs_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            alias = root / 'alias'
            alias.symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                P.prepare(alias, root / 'output')
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                P.prepare(source, source / 'output')
            self.assertFalse((source / 'output').exists())


if __name__ == '__main__':
    unittest.main()
