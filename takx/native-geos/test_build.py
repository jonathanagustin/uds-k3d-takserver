# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('historical_geos_profile', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class OfflineGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_exact_archive_license_tools_and_patch_selection(self):
        original = json.loads((HERE / 'inputs.lock.json').read_text())
        BUILD.validate_lock(original)
        for section, key, value in [('archives', 'geos-3.4.3', dict(BUILD.ARCHIVE, url='https://foreign/source')),
                                    ('archives', 'geos-3.4.3', dict(BUILD.ARCHIVE, expanded_bytes=1)),
                                    ('archives', 'geos-3.4.3', dict(BUILD.ARCHIVE, sha256='a' * 64)),
                                    ('license', 'source', 'geos-3.4.3/README'),
                                    ('license', 'sha256', 'a' * 64), ('tools', 'gcc', '15.1')]:
            lock = json.loads(json.dumps(original))
            lock[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                BUILD.validate_lock(lock)
        original['source_patch'] = {}
        with self.assertRaises(ValueError):
            BUILD.validate_lock(original)

    def test_patch_images_reject_wrong_original_or_patched_bytes(self):
        paths = {}
        hashes = {}
        for name in BUILD.PATCH['files']:
            path = self.root / name
            path.write_bytes(b'original-' + name.encode())
            paths[name] = path
            hashes[name] = {'before': BUILD.native.digest(path), 'after': '0' * 64}
        with patch.dict(BUILD.PATCH, {'files': hashes}):
            BUILD.check_patch_images(self.root, 'before')
            with self.assertRaises(ValueError):
                BUILD.check_patch_images(self.root, 'after')
            paths['ltmain.sh'].write_bytes(b'foreign patch')
            with self.assertRaises(ValueError):
                BUILD.check_patch_images(self.root, 'before')

    def test_offline_cache_does_not_fetch_and_rejects_tampering(self):
        entry = dict(BUILD.ARCHIVE)
        with patch.object(BUILD.native.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError, 'offline'):
                BUILD.native.acquire(self.root, entry, False)
            (self.root / entry['sha256']).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                BUILD.native.acquire(self.root, entry, False)

    def test_archive_link_traversal_and_expansion_are_refused(self):
        for name, kind in [('geos-3.4.3/../../escape', tarfile.REGTYPE),
                           ('geos-3.4.3/link', tarfile.SYMTYPE), ('foreign/file', tarfile.REGTYPE),
                           ('geos-3.4.3/file', tarfile.REGTYPE)]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / 'archive.tar'
                with tarfile.open(archive, 'w') as stream:
                    item = tarfile.TarInfo(name); item.type = kind; item.size = 4
                    stream.addfile(item, io.BytesIO(b'data'))
                with self.assertRaises(ValueError):
                    BUILD.las.unpack(archive, Path(directory) / 'out', 'geos-3.4.3',
                                     {'members': 1, 'regular_files': 1, 'expanded_bytes': 3})

    def test_new_external_output_and_cache_must_be_separate(self):
        cache = self.root / 'cache'; cache.mkdir()
        for out in (cache, cache / 'out', self.root):
            with self.subTest(out=out), self.assertRaises(ValueError):
                BUILD.validate_paths(out, cache)
        link = self.root / 'link'; link.symlink_to(cache)
        with self.assertRaises(ValueError):
            BUILD.validate_paths(self.root / 'new', link)
        self.assertEqual(BUILD.validate_paths(self.root / 'new', cache), (self.root / 'new', cache))

    def test_inherited_compiler_geos_and_make_injection_removed(self):
        injected = {'CFLAGS': '-DNDEBUG', 'LDFLAGS': '-lgeos', 'LD_PRELOAD': '/foreign',
                    'CPATH': '/foreign', 'CMAKE_TOOLCHAIN_FILE': '/foreign', 'GEOS_LIB': '/foreign',
                    'MAKEFLAGS': '-j20', 'GNUMAKEFLAGS': '-j20', 'AR': '/foreign', 'RANLIB': '/foreign', 'MAKEFILES': '/foreign', 'CONFIG_SITE': '/foreign',
                    'BASH_ENV': '/foreign', 'BASH_FUNC_injected%%': '() { false; }'}
        with patch.dict(os.environ, injected):
            env = BUILD.environment('/trusted/gcc')
        for name in set(injected) - {'CFLAGS', 'CONFIG_SITE'}:
            self.assertNotIn(name, env)
        self.assertEqual(env['CFLAGS'], '-O2 -fPIC')
        self.assertEqual(env['CONFIG_SITE'], '/dev/null')
        self.assertEqual(env['CC'], '/trusted/gcc')

    def test_untouched_source_rejects_changes_additions_and_symlinks(self):
        path = self.root / 'source.c'; path.write_bytes(b'original')
        expected = BUILD.source_inventory(self.root)
        for change in ('edit', 'new', 'link'):
            with self.subTest(change=change):
                path.write_bytes(b'original')
                extra = self.root / 'extra'
                if extra.exists() or extra.is_symlink(): extra.unlink()
                if change == 'edit': path.write_bytes(b'changed')
                elif change == 'new': extra.write_bytes(b'new')
                else: extra.symlink_to(path)
                with self.assertRaises(ValueError): BUILD.check_sources(self.root, expected)

    def test_proof_outputs_are_regular_and_hash_bound(self):
        for name in ('GeosGeometry.c', 'consumer', 'libgeos-pic-check.so'):
            (self.root / name).write_bytes(name.encode())
        before = BUILD.outputs(self.root)
        (self.root / 'consumer').write_bytes(b'changed')
        self.assertNotEqual(before, BUILD.outputs(self.root))
        (self.root / 'consumer').unlink()
        (self.root / 'consumer').symlink_to(self.root / 'GeosGeometry.c')
        with self.assertRaises(ValueError): BUILD.outputs(self.root)


@unittest.skipUnless(os.environ.get('TAKX_NATIVE_GEOS_PROOF'), 'opt-in fresh historical GEOS proof required')
class ActualComponentProof(unittest.TestCase):
    def test_fresh_entrypoint_identity_and_real_coordinate_consumer(self):
        root = Path(os.environ['TAKX_NATIVE_GEOS_PROOF']).resolve()
        receipt = json.loads((root / 'complete.json').read_text())
        self.assertEqual(receipt['recipe'], BUILD.recipe())
        self.assertEqual(receipt['outputs'], BUILD.outputs(root))
        self.assertEqual(receipt['installed'], BUILD.native.inventory(root / 'install'))
        BUILD.check_sources(root / 'source', receipt['source_inventory'])
        BUILD.las.verify_runtime(receipt['runtime_closure'])
        for tool in receipt['tools'].values():
            self.assertEqual(tool['sha256'], BUILD.native.digest(Path(tool['path'])))
        with tempfile.TemporaryDirectory() as directory:
            result = BUILD.native.run([str(root / 'consumer')], Path(directory), 'positive',
                                      timeout=10, capture=True,
                                      env=BUILD.environment(receipt['tools']['cc']['path'])).decode()
        self.assertIn('actual_release=3.4.3-CAPI-1.8.3 r4285\n', result)
        self.assertIn('geometry_and_error_controls=true\n', result)
        for name in ('jni_acceptance', 'modern_geos_api_compatibility', 'security_acceptance',
                     'target_image_abi_acceptance', 'kernel_sdk_acceptance', 'takx_acceptance'):
            self.assertFalse(receipt[name])


if __name__ == '__main__':
    unittest.main()
