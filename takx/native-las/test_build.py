# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('las_profile', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class SourceGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, entries):
        target = self.root / 'input.tar'
        with tarfile.open(target, 'w') as output:
            for name, kind, data in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.size = len(data) if kind == tarfile.REGTYPE else 0
                item.linkname = '/foreign'
                output.addfile(item, io.BytesIO(data) if item.isfile() else None)
        return target

    def unpack(self, entries, **overrides):
        bounds = dict(members=len(entries), regular_files=len(entries), expanded_bytes=16)
        bounds.update(overrides)
        return BUILD.unpack(self.archive(entries), self.root / 'source', 'libLAS', bounds)

    def test_traversal_symlinks_hardlinks_and_duplicate_members_refused(self):
        for entries in [ [('libLAS/../escape', tarfile.REGTYPE, b'x')],
                         [('libLAS/link', tarfile.SYMTYPE, b'')],
                         [('libLAS/link', tarfile.LNKTYPE, b'')],
                         [('libLAS/x', tarfile.REGTYPE, b'x')] * 2 ]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.unpack(entries)

    def test_expansion_and_member_count_bounds_refused(self):
        with self.assertRaisesRegex(ValueError, 'expansion'):
            self.unpack([('libLAS/x', tarfile.REGTYPE, b'abc')], expanded_bytes=2)
        with self.assertRaisesRegex(ValueError, 'count'):
            self.unpack([('libLAS/y', tarfile.REGTYPE, b'a')], members=0)

    def test_mutated_or_missing_source_and_unreviewed_generated_file_refused(self):
        root = self.root / 'source'
        root.mkdir()
        file = root / 'original'
        file.write_bytes(b'original')
        expected = {'original': {'bytes': 8, 'sha256': BUILD.native.digest(file)}}
        BUILD.check_sources(root, expected)
        file.write_bytes(b'mutated!')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            BUILD.check_sources(root, expected)
        file.unlink()
        with self.assertRaisesRegex(ValueError, 'source changed'):
            BUILD.check_sources(root, expected)
        file.write_bytes(b'original')
        (root / 'injected.cpp').write_text('ambient source')
        with self.assertRaisesRegex(ValueError, 'unexpected generated'):
            BUILD.check_sources(root, expected)
        with self.assertRaisesRegex(ValueError, 'unreviewed generated'):
            BUILD.check_sources(root, expected, {'injected.cpp': {}})

    def test_generated_bootstrap_files_remain_hash_bound(self):
        file = self.root / 'libLAS/find_package/boost/b2'
        file.parent.mkdir(parents=True)
        file.write_bytes(b'generated executable')
        generated = {str(file.relative_to(self.root)): {'bytes': file.stat().st_size,
                                                      'sha256': BUILD.native.digest(file)}}
        BUILD.check_sources(self.root, {}, generated)
        file.write_bytes(b'substitute executable')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            BUILD.check_sources(self.root, {}, generated)

    def test_offline_missing_and_tampered_cache_never_fetch(self):
        entry = {'sha256': 'a' * 64, 'bytes': 3, 'url': 'https://invalid.example/source'}
        with patch.object(BUILD.native.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError, 'offline'):
                BUILD.native.acquire(self.root, entry, False)
            (self.root / entry['sha256']).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                BUILD.native.acquire(self.root, entry, False)

    def test_existing_output_never_adopted(self):
        output = self.root / 'existing'
        output.mkdir()
        marker = output / 'keep'
        marker.write_text('previous invocation')
        with patch('sys.argv', ['build.py', '--output', str(output), '--cache', str(self.root / 'cache')]), \
                patch.object(BUILD.platform, 'system', return_value='Linux'), \
                patch.object(BUILD.platform, 'machine', return_value='x86_64'):
            with self.assertRaisesRegex(ValueError, 'output must be new'):
                BUILD.main()
        self.assertEqual(marker.read_text(), 'previous invocation')

    def test_host_dependency_prefix_refused_before_compile(self):
        build = self.root / 'build'
        build.mkdir()
        (build / 'CMakeCache.txt').write_text(
            'LASZIP_LIBRARY:FILEPATH=/foreign/liblaszip.a\n'
            'LASZIP_INCLUDE_DIR:PATH=/foreign/include\n'
            'Boost_INCLUDE_DIR:PATH=/foreign/boost\n')
        with self.assertRaisesRegex(ValueError, 'prefix mismatch'):
            BUILD.audit_configuration(build, self.root / 'laszip', self.root / 'boost',
                                      self.root / 'stage', '')

    def test_source_origin_and_patch_bytes_locked(self):
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        BUILD.validate_lock(lock)
        lock['archives']['LASzip']['url'] = 'https://unreviewed.example/LASzip.tar.gz'
        with self.assertRaisesRegex(ValueError, 'unreviewed'):
            BUILD.validate_lock(lock)

    def test_lock_patch_and_license_paths_cannot_escape(self):
        for section, key, value in [('patches', 'root', '../libLAS'),
                                    ('patches', 'source', 'libLAS/../../escape'),
                                    ('licenses', 'source', '../escape')]:
            lock = json.loads((HERE / 'inputs.lock.json').read_text())
            next(iter(lock[section].values()))[key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                BUILD.validate_lock(lock)
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        lock['licenses']['../escape'] = lock['licenses'].pop('Boost')
        with self.assertRaises(ValueError):
            BUILD.validate_lock(lock)
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        lock['patches'].pop(next(iter(lock['patches'])))
        with self.assertRaisesRegex(ValueError, 'patch selection'):
            BUILD.validate_lock(lock)

    def test_runtime_and_loaded_library_provenance_refused_after_tamper(self):
        lib = self.root / 'install/lib/liblas.so'
        lib.parent.mkdir(parents=True)
        lib.write_bytes(b'actual library')
        closure = {str(lib): BUILD.native.digest(lib)}
        BUILD.verify_runtime(closure)
        lib.write_bytes(b'substitute library')
        with self.assertRaisesRegex(ValueError, 'runtime library integrity'):
            BUILD.verify_runtime(closure)
        with self.assertRaisesRegex(ValueError, 'foreign'):
            BUILD.loaded_libraries('loaded_liblas=' + str(lib), self.root / 'other')
        with self.assertRaisesRegex(ValueError, 'provenance incomplete'):
            BUILD.loaded_libraries('loaded_liblas=' + str(lib), self.root / 'install')

    def test_ambient_build_injection_removed(self):
        tools = {'cc': {'path': '/trusted/gcc'}, 'cxx': {'path': '/trusted/g++'}}
        with patch.dict(os.environ, {'CONAN_HOME': '/foreign', 'BOOST_ROOT': '/foreign',
                                     'BASH_ENV': '/foreign/script', 'CPATH': '/foreign',
                                     'CMAKE_PROJECT_INCLUDE': '/foreign/hook'}):
            env = BUILD.environment(tools)
        for key in ('CONAN_HOME', 'BOOST_ROOT', 'BASH_ENV', 'CPATH', 'CMAKE_PROJECT_INCLUDE'):
            self.assertNotIn(key, env)
        self.assertEqual(env['VCPKG_BINARY_SOURCES'], 'clear')
        self.assertEqual(env['CMAKE_BUILD_PARALLEL_LEVEL'], '1')

    def test_probe_symlink_and_tamper_refused(self):
        names = ('consumer', 'consumer-asan', 'liblas-dependencies-pic-check.so', 'original-truncated.laz')
        for name in names:
            (self.root / name).write_bytes(name.encode())
        original = BUILD.probe_outputs(self.root)
        (self.root / 'consumer').write_bytes(b'substitute')
        self.assertNotEqual(original, BUILD.probe_outputs(self.root))
        (self.root / 'consumer').unlink()
        (self.root / 'consumer').symlink_to(self.root / 'consumer-asan')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            BUILD.probe_outputs(self.root)


@unittest.skipUnless(os.environ.get('TAKX_NATIVE_LAS_PROOF'), 'opt-in real native LAS proof required')
class ActualNativeProof(unittest.TestCase):
    def test_bound_real_library_codec_cursor_errors_and_pic(self):
        root = Path(os.environ['TAKX_NATIVE_LAS_PROOF']).resolve()
        receipt = json.loads((root / 'complete.json').read_text())
        self.assertEqual(receipt['recipe'], BUILD.recipe())
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        self.assertEqual(BUILD.native.digest(root / 'original-truncated.laz'), lock['malformed_fixture_sha256'])
        self.assertEqual(receipt['probe_outputs'], BUILD.probe_outputs(root))
        self.assertEqual(receipt['installed'], BUILD.native.inventory(root / 'install'))
        for item in receipt['loaded_libraries'].values():
            self.assertEqual(item['sha256'], BUILD.native.digest(Path(item['path'])))
        BUILD.verify_runtime(receipt['runtime_closure'])
        tools = {'cc': receipt['tools']['cc'], 'cxx': receipt['tools']['cxx']}
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([str(root / 'consumer'), tmp, str(root / 'original-truncated.laz')],
                                    capture_output=True, timeout=20, check=True, env=BUILD.environment(tools))
        self.assertEqual(receipt['loaded_libraries'], BUILD.loaded_libraries(result.stdout.decode(), root / 'install'))
        self.assertIn(b'c_api_seek_exception_returns_failure_with_error_stack=true', result.stdout)
        self.assertIn(b'immutable_original_truncated_laz_rejected_by_cpp_and_c=true', result.stdout)
        result = subprocess.run([receipt['tools']['readelf']['path'], '-d',
                                 str(root / 'liblas-dependencies-pic-check.so')],
                                capture_output=True, timeout=10, check=True, env=BUILD.environment(tools))
        self.assertNotIn(b'TEXTREL', result.stdout)
        self.assertTrue(receipt['consumer_asan_ubsan'])
        self.assertTrue(receipt['whole_archive_pic'])
        self.assertFalse(receipt['general_malformed_input_safety'])
        self.assertFalse(receipt['kernel_sdk_acceptance'])
        self.assertFalse(receipt['target_image_abi_acceptance'])
        self.assertFalse(receipt['takx_acceptance'])


if __name__ == '__main__':
    unittest.main()
