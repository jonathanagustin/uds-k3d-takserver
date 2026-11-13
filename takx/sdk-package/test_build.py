# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline pure guards: no compiler, JVM, native loading or acquisition."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import copy
import zipfile
spec=importlib.util.spec_from_file_location('sdk_package_under_test',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Guards(unittest.TestCase):
    def test_provider_failure_names_are_fixed_and_private_messages_never_leak(self):
        expected={name:{'receipt':'bound'} for name in b.p.FAMILIES};actual=copy.deepcopy(expected)
        del actual['gdal_jni'];actual['gles']={'receipt':'different'}
        errors={'gdal_jni':'PRIVATE_EXCEPTION_SENTINEL /private/path','proj':'PRIVATE_TOKEN_SENTINEL',
                'cross_provider_chain':'PRIVATE_CHAIN_SENTINEL'}
        with self.assertRaises(ValueError) as raised:b.require_provider_results(expected,actual,errors)
        self.assertEqual(str(raised.exception),'actual native providers differ: cross_provider_chain,gdal_jni,gles,proj')
        self.assertNotIn('PRIVATE',str(raised.exception));self.assertNotIn('/private',str(raised.exception))
        with self.assertRaisesRegex(ValueError,'inventory') as unknown:
            b.require_provider_results(expected,actual,{'PRIVATE_UNKNOWN_FAMILY':'PRIVATE_EXCEPTION'})
        self.assertNotIn('PRIVATE',str(unknown.exception))
        self.assertEqual(b.provider_failure_categories([],actual,errors),['inventory'])
        self.assertIsNone(b.require_provider_results(expected,copy.deepcopy(expected),{}))

    def test_archive_paths_reject_traversal_and_absolute_names(self):
        for name in ['../secret','/secret','libs/../../secret','libs\\secret']:
            with self.assertRaises(ValueError):b.safe(name)
    def test_exact_archive_roundtrip_excludes_unrequested_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            jar=Path(d)/'artifact.jar';expected={'a.class':b'owned fixture bytes','libs/linux64/example.txt':b'not a native library'}
            b.jar_write(jar,expected)
            with zipfile.ZipFile(jar) as z:self.assertEqual(set(z.namelist()),set(expected));self.assertEqual(z.read('a.class'),expected['a.class'])
    def test_map_policy_rejects_original_even_with_correct_hash(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'original';path.write_bytes(b'pure guard input');sha=b.p.digest(path)
            with self.assertRaises(ValueError):b.mapped_provider(path,sha,{}, {str(path):sha},{str(path)})
    def test_map_policy_rejects_unlisted_stale_or_changed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'input';path.write_bytes(b'pure guard input');sha=b.p.digest(path)
            with self.assertRaises(ValueError):b.mapped_provider(path,sha,{}, {},set())
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):b.mapped_provider(path,sha,{str(path):sha},{},set())
    def test_exact_packaged_map_is_required_for_graphics(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'libGLdispatch.so';path.write_bytes(b'pure identity fixture');sha=b.p.digest(path)
            with self.assertRaises(ValueError):b.mapped_provider(path,sha,{}, {str(path):sha},set())
            self.assertEqual(b.mapped_provider(path,sha,{str(path):sha},{},set()),str(path))
    def test_shared_backend_is_rejected_despite_hash_allowlist(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'libcrypto.so.3';path.write_bytes(b'pure identity fixture');sha=b.p.digest(path)
            with self.assertRaises(ValueError):b.mapped_provider(path,sha,{}, {str(path):sha},set())
    def test_output_overlap_cannot_modify_native_or_jdk_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);native=root/'native';native.mkdir()
            with self.assertRaises(ValueError):b.b.disjoint(native/'new',[native])
if __name__=='__main__':unittest.main()
