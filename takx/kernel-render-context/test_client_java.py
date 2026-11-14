# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('client_java_composition', Path(__file__).with_name('client_java.py'))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class Guards(unittest.TestCase):
    def test_default_does_not_execute_commands(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no process')), patch('sys.argv', ['client_java.py']):
            P.main()

    def test_paths_require_explicit_phase(self):
        with patch('sys.argv', ['client_java.py', '--output', '/not-created']), self.assertRaises(ValueError):
            P.main()

    def test_source_paths_refuse_traversal_and_other_payloads(self):
        for name in ('/source.java', '../source.java', 'a/../source.java', 'source.class', 'a\\source.java'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                P.relative(name)

    def test_syntax_cannot_overwrite_native_objects_or_dependency_files(self):
        native = Path('/native')
        row = {'arguments': ['/compiler/g++', '-DREAL=1', '-I/native/java/jni-headers', '-MD', '-MF',
                             '/native/dependency.d', '-o', '/native/object.o', '-c', '/native/source.cpp']}
        actual = P.syntax_arguments(row, native, Path('/fresh/headers'))
        self.assertEqual(actual, ['/compiler/g++', '-DREAL=1', '-I/fresh/headers', '/native/source.cpp', '-fsyntax-only'])
        with self.assertRaises(ValueError):
            P.syntax_arguments({'arguments': ['/compiler/g++', '-o']}, native, Path('/fresh/headers'))
