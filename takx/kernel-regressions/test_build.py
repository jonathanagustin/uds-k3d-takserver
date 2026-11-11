# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline admission guards only; no compiler, native library or JVM starts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('kernel_regressions_under_test', Path(__file__).with_name('build.py'))
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)

class Guards(unittest.TestCase):
    def test_sdk_inventory_escape_is_rejected(self):
        for name in ['../secret', '/absolute', 'a/../../escape', 'a\\b', 'a//b', None]:
            with self.assertRaises(ValueError):
                b.safe(name)

    def test_reviewed_receipt_hash_is_mandatory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'complete.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'reviewed SDK proof hash'):
                b.inspect(root, '0' * 64)

    def test_native_smoke_without_resource_gate_cannot_be_relabelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'complete.json').write_text(json.dumps({
                'component_runtime_acceptance': True,
                'stock_resource_loader_controls_passed': True,
            }))
            with self.assertRaisesRegex(ValueError, 'resource-complete'):
                b.inspect(root, b.sha(root / 'complete.json'))

    def test_missing_required_packaged_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = root / 'libhost.so'
            host.write_bytes(b'guard identity only; never loaded')
            with self.assertRaisesRegex(ValueError, 'packaged provider absent'):
                b.verify_maps('ELF ' + b.sha(host) + ' ' + str(host), root / 'packaged',
                              {'libtakengine.so': '0' * 64}, {str(host): b.sha(host)})

    def test_original_provider_cannot_replace_packaged_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'libtakengine.so'
            original.write_bytes(b'guard identity only; never loaded')
            with self.assertRaisesRegex(ValueError, 'unapproved host or original provider'):
                b.verify_maps('ELF ' + b.sha(original) + ' ' + str(original), root / 'packaged', {}, {})

    def test_shared_backend_is_not_admitted_even_by_matching_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / 'libsqlite3.so.0'
            backend.write_bytes(b'guard identity only; never loaded')
            with self.assertRaisesRegex(ValueError, 'shared backend'):
                b.verify_maps('ELF ' + b.sha(backend) + ' ' + str(backend), root / 'packaged', {}, {str(backend): b.sha(backend)})

    def test_upstream_provenance_covers_the_three_real_slices(self):
        lock = json.loads(Path(__file__).with_name('upstream.lock.json').read_text())
        self.assertEqual(lock['revision'], b.REVISION)
        self.assertEqual(len(lock['tests']), 3)
        self.assertTrue(all(len(row['blob']) == 40 and len(row['sha256']) == 64 for row in lock['tests']))
        self.assertIn('DTED height decoding', lock['adaptation']['not_covered'])

if __name__ == '__main__':
    unittest.main()
