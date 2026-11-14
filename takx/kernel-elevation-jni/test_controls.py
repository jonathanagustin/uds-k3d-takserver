# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""No-launch and failed-input guards for the explicit frozen-build consumer."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('elevation_control_runner', HERE / 'controls.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class ConsumerGuards(unittest.TestCase):
    def test_default_verifies_profile_without_starting_a_process(self):
        with patch.object(C.subprocess, 'Popen', side_effect=AssertionError('must not launch')):
            C.main([])
            for args in (['--native', '/missing'], ['--phase', 'run']):
                with self.assertRaises(ValueError):
                    C.main(args)

    def test_unreviewed_receipt_refuses_before_output_or_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native, java, jdk = [root / name for name in ('native', 'java', 'jdk')]
            for path in (native, java, jdk):
                path.mkdir()
            (native / 'experiment-complete.json').write_text('{"accepted":true}')
            output = root / 'output'
            with patch.object(C.subprocess, 'Popen', side_effect=AssertionError('must not launch')):
                with self.assertRaisesRegex(ValueError, 'reviewed input bytes'):
                    C.run(native, java, jdk, output)
            self.assertFalse(output.exists())

    def test_existing_symlink_and_overlapping_outputs_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            alias = root / 'alias'
            alias.symlink_to(source, target_is_directory=True)
            for output in (source, source / 'output', alias / 'output'):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    C.fresh_output(output, (source,))
            self.assertFalse((source / 'output').exists())
