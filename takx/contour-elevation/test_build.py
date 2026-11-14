# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""No native launch without explicit reviewed-producer and source inputs."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('contour_elevation_builder', HERE / 'build.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class ProviderGuards(unittest.TestCase):
    def test_default_never_imports_executor_or_starts_native_controls(self):
        with patch.object(B, 'module', side_effect=AssertionError('must not execute')):
            B.main([])
            for argv in (['--native', '/missing'], ['--phase', 'controls']):
                with self.assertRaises(ValueError):
                    B.main(argv)

    def test_owned_source_and_acceptance_changes_refuse(self):
        for change in (*B.SOURCES, 'experiments/ContourDrawProbe.java', 'acceptance'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'profile'
                shutil.copytree(HERE, root)
                if change != 'acceptance':
                    path = root / change
                    path.write_bytes(path.read_bytes() + b'\n// changed\n')
                else:
                    path = root / 'inputs.lock.json'
                    lock = json.loads(path.read_text())
                    lock['full_client_accepted'] = True
                    path.write_text(json.dumps(lock))
                with patch.object(B, 'HERE', root), self.assertRaises(ValueError):
                    B.contract()

    def test_unreviewed_dependency_refuses_before_output_or_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / 'dependency'
            profile.mkdir()
            (profile / 'controls.py').write_text('raise AssertionError("must not import")')
            output = root / 'output'
            args = SimpleNamespace(native=root / 'native', java=root / 'java', jdk=root / 'jdk',
                                   elevation_profile=profile, output=output)
            with patch.object(B, 'module', side_effect=AssertionError('must not import')):
                with self.assertRaisesRegex(ValueError, 'reviewed elevation consumer'):
                    B.controls(args)
            self.assertFalse(output.exists())

    def test_overlap_and_symlink_outputs_refuse_before_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            alias = root / 'alias'
            alias.symlink_to(source, target_is_directory=True)
            for output in (source / 'output', alias / 'output'):
                args = SimpleNamespace(native=source, java=root / 'java', jdk=root / 'jdk',
                                       elevation_profile=root / 'dependency', output=output)
                with self.subTest(output=output), self.assertRaises(ValueError):
                    B.controls(args)
            self.assertFalse((source / 'output').exists())
