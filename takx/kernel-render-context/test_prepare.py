# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guards only: no compiler, source download, JVM or native execution."""
import importlib.util
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('context_prepare', Path(__file__).with_name('prepare.py'))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class SourceGuards(unittest.TestCase):
    def test_owned_contract_and_exact_order(self):
        lock, data = p.load_contract()
        self.assertEqual(p.digest(data), lock['context_patch_sha256'])
        self.assertEqual(lock['stage_order'], ['official', 'baseline', 'texture', 'context', 'client_jni'])
        self.assertEqual(len(lock['stages']['official']), 54)
        self.assertFalse(lock['native_builder_integration'])
        self.assertFalse(lock['gpu_qualified'])

    def test_stage_before_and_after_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'takkernel/engine/src/main/cpp/example.cpp'
            target = root/name
            target.parent.mkdir(parents=True)
            target.write_bytes(b'before')
            p.verify_stage(root, {name: p.digest(b'before')})
            with self.assertRaises(ValueError):
                p.verify_stage(root, {name: p.digest(b'after')})
            target.write_bytes(b'after')
            p.verify_stage(root, {name: p.digest(b'after')})
            with self.assertRaises(ValueError):
                p.verify_stage(root, {name: p.digest(b'before')})

    def test_new_source_must_not_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'takkernel/engine/src/new.h'
            p.verify_stage(root, {name: None})
            target = root/name
            target.parent.mkdir(parents=True)
            target.write_bytes(b'not absent')
            with self.assertRaises(ValueError):
                p.verify_stage(root, {name: None})

    def test_traversal_and_other_components_refused(self):
        for name in ['../x', '/takkernel/engine/src/x', 'takkernel/engine/src/../../x',
                     'commoncommo/src/x', 'takkernel\\engine\\src\\x']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.relative(name)

    def test_symlink_file_and_parent_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root/'outside'
            outside.write_bytes(b'outside')
            target = root/'takkernel/engine/src/file.cpp'
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)
            with self.assertRaises(ValueError):
                p.verify_stage(root, {'takkernel/engine/src/file.cpp': p.digest(b'outside')})
            target.unlink()
            target.parent.rmdir()
            target.parent.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                p.target(root, 'takkernel/engine/src/file.cpp')

    def test_client_selection_excludes_unconsumed_java(self):
        java = b'--- a/unrelated.java\n+++ b/unrelated.java\n@@ -1 +1 @@\n-old\n+new\n'
        native = b'--- a/takkernel/engine/src/main/jni/a.cpp\n+++ b/takkernel/engine/src/main/jni/a.cpp\n@@ -1 +1 @@\n-old\n+new\n'
        name = 'takkernel/engine/src/main/jni/a.cpp'
        self.assertEqual(p.selected_client_patch(java+native, {name}), native)
        self.assertEqual(p.selected_client_patch(native+java, {name}), native)
        with self.assertRaises(ValueError):
            p.selected_client_patch(java, {name})
        with self.assertRaises(ValueError):
            p.selected_client_patch(native+native, {name})
        with self.assertRaises(ValueError):
            p.selected_client_patch(b'diff --git a/x b/x\n'+native, {name})

    def test_source_size_and_missing_input_are_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input'
            with self.assertRaises(FileNotFoundError):
                p.regular(path)
            path.write_bytes(b'12345')
            with self.assertRaises(ValueError):
                p.regular(path, limit=4)

    def test_default_verify_invokes_no_process(self):
        with patch('sys.argv', ['prepare.py']), patch.object(p.subprocess, 'Popen', side_effect=AssertionError('process forbidden')):
            p.main()
        with patch('sys.argv', ['prepare.py', '--output', '/unused']), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            p.main()


if __name__ == '__main__':
    unittest.main()
