# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline boundaries: no compiler, dependencies, display or native libraries."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('contour_grid_build', HERE / 'build.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class ContourGridGuards(unittest.TestCase):
    def test_default_verifies_sources_without_starting_controls(self):
        with patch.object(B, 'controls', side_effect=AssertionError('must not launch')):
            B.main([])

    def test_source_tamper_or_acceptance_escalation_refuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'profile'
            shutil.copytree(HERE, root)
            source = root / B.SOURCES[0]
            source.write_bytes(source.read_bytes() + b'\n')
            with patch.object(B, 'HERE', root), self.assertRaisesRegex(ValueError, 'source bytes differ'):
                B.contract()
            shutil.copyfile(HERE / B.SOURCES[0], source)
            lock = root / 'inputs.lock.json'
            value = json.loads(lock.read_text())
            value['full_client_accepted'] = True
            lock.write_text(json.dumps(value))
            with patch.object(B, 'HERE', root), self.assertRaisesRegex(ValueError, 'cannot grant'):
                B.contract()

    def test_paths_require_explicit_controls_and_complete_arguments(self):
        for argv in (['--java-home', '/missing'], ['--phase', 'controls'],
                     ['--phase', 'controls', '--output', '/missing']):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                B.main(argv)

    def test_unqualified_jdk_and_overlapping_output_never_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            java = root / 'jdk'
            java.mkdir()
            output = root / 'result'
            with self.assertRaises(FileNotFoundError):
                B.main(['--phase', 'controls', '--java-home', str(java), '--output', str(output)])
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                B.main(['--phase', 'controls', '--java-home', str(java), '--output', str(java / 'result')])
            self.assertFalse((java / 'result').exists())


if __name__ == '__main__':
    unittest.main()
