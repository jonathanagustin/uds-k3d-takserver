# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Small offline guards; never invokes javac or accepts a synthetic compile."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('client_compiler', Path(__file__).with_name('build.py'))
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'classes').mkdir()
        (self.root / 'sources').mkdir()
        (self.root / 'classes/A.class').write_bytes(b'qualified class')
        (self.root / 'sources/A.java').write_text('class A {}')
        self.roots = {'input': self.root}
        self.lock = {'files': {}, 'sources': {'input:sources/A.java': build.sha(self.root / 'sources/A.java')},
                     'class_directories': {'input:classes': build.inventory(self.root / 'classes', '.class')},
                     'official_client_tree': 'input:sources',
                     'official_client_sources': build.inventory(self.root / 'sources', '.java')}

    def test_valid_inputs(self):
        build.verify(self.lock, self.roots)

    def test_changed_source_rejected(self):
        (self.root / 'sources/A.java').write_text('class Changed {}')
        with self.assertRaisesRegex(ValueError, 'input digest differs'):
            build.verify(self.lock, self.roots)

    def test_extra_class_rejected(self):
        (self.root / 'classes/Partial.class').write_bytes(b'interrupted')
        with self.assertRaisesRegex(ValueError, 'exact prerequisite class set'):
            build.verify(self.lock, self.roots)

    def test_extra_official_source_rejected(self):
        (self.root / 'sources/B.java').write_text('class B {}')
        with self.assertRaisesRegex(ValueError, 'official Client source tree'):
            build.verify(self.lock, self.roots)

    def test_root_escape_rejected(self):
        for relative in ['../outside', '/absolute']:
            with self.assertRaisesRegex(ValueError, 'unsafe relative input'):
                build.resolve('input:' + relative, self.roots)

    def test_qualified_lock_shape(self):
        text = build.LOCK.read_text()
        lock = json.loads(text)
        self.assertNotIn('/workspace/', text)
        self.assertEqual(len(lock['sources']), 1678)
        self.assertEqual(len(lock['official_client_sources']), 1678)
        self.assertEqual(len(lock['expected_class_names']), 2815)
        self.assertEqual(sorted(len(v) for v in lock['class_directories'].values()),
                         [2, 4, 5, 8, 15, 15, 45, 2098])
        for ref in lock['classpath'] + lock['processorpath'] + [lock['javac']]:
            self.assertIn(ref.split(':', 1)[0], lock['roots'])
        self.assertEqual(lock['limits']['new_output_bytes'], 15 * 1024**2)
        self.assertEqual(lock['limits']['minimum_free_bytes'], 2 * 1024**3)


if __name__ == '__main__':
    unittest.main()
