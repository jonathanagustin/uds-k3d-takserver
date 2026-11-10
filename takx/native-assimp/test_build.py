# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('public_assimp_profile', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class OfflineGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_archive_origin_hash_and_expansion_are_exact(self):
        original = json.loads((HERE / 'inputs.lock.json').read_text())
        BUILD.validate_lock(original)
        for key, value in [('url', 'https://other.example/source'), ('expanded_bytes', 120685649),
                           ('sha256', 'a' * 64)]:
            lock = json.loads(json.dumps(original))
            lock['archives']['assimp'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                BUILD.validate_lock(lock)

    def test_patch_and_license_paths_cannot_escape(self):
        for section, key, value in [('patches', 'source', 'assimp/../../escape'),
                                    ('licenses', 'source', '../escape')]:
            lock = json.loads((HERE / 'inputs.lock.json').read_text())
            next(iter(lock[section].values()))[key] = value
            with self.subTest(section=section), self.assertRaises(ValueError):
                BUILD.validate_lock(lock)
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        lock['licenses']['../escape'] = lock['licenses'].pop('assimp')
        with self.assertRaises(ValueError):
            BUILD.validate_lock(lock)

    def test_notice_sources_and_hashes_cannot_be_swapped(self):
        original = json.loads((HERE / 'inputs.lock.json').read_text())
        for value in [{'source': 'assimp/Readme.md', 'sha256': original['licenses']['assimp']['sha256']},
                      original['licenses']['OpenDDL.txt'],
                      {'source': 'assimp/LICENSE', 'sha256': 'a' * 64}]:
            lock = json.loads(json.dumps(original))
            lock['licenses']['assimp'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'license paths/hashes'):
                BUILD.validate_lock(lock)

    def test_output_reuse_and_source_cache_sdk_overlaps_refused(self):
        output, cache, jdk = self.root / 'output', self.root / 'cache', self.root / 'jdk'
        self.assertEqual(BUILD.validate_paths(output, cache, jdk), (output, cache, jdk))
        for a, b, c in [(output, output, jdk), (output / 'inside', output, jdk),
                        (output, cache, output / 'source/jdk'), (output, cache, cache / 'sdk'),
                        (jdk / 'output', cache, jdk)]:
            with self.subTest(paths=(a,b,c)), self.assertRaises(ValueError):
                BUILD.validate_paths(a,b,c)
        output.mkdir()
        marker = output / 'keep'
        marker.write_text('existing output')
        with self.assertRaisesRegex(ValueError, 'output must be new'):
            BUILD.validate_paths(output, cache, jdk)
        self.assertEqual(marker.read_text(), 'existing output')

    def test_source_mutation_new_files_and_links_refused(self):
        path = self.root / 'original'
        path.write_bytes(b'original')
        expected = BUILD.freeze_tree(self.root)
        BUILD.check_sources(self.root, expected)
        path.write_bytes(b'mutated')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            BUILD.check_sources(self.root, expected)
        path.write_bytes(b'original')
        extra = self.root / 'injected.cpp'
        extra.write_text('external source')
        with self.assertRaises(ValueError):
            BUILD.check_sources(self.root, expected)
        extra.unlink()
        extra.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            BUILD.check_sources(self.root, expected)

    def test_sdk_external_links_and_incomplete_sdk_refused(self):
        with self.assertRaisesRegex(ValueError, 'complete Linux JDK'):
            BUILD.sdk_inventory(self.root)
        (self.root / 'escape').symlink_to('/usr/bin/env')
        with self.assertRaisesRegex(ValueError, 'leaves prefix'):
            BUILD.sdk_inventory(self.root)

    def test_native_signature_changes_and_missing_declarations_refused(self):
        text = '\n'.join('public native int ' + name + '();\n descriptor: ' + descriptor
                         for name, descriptor in BUILD.NATIVE_METHODS.items())
        self.assertEqual(BUILD.native_signatures(text), BUILD.NATIVE_METHODS)
        with self.assertRaisesRegex(ValueError, 'signatures differ'):
            BUILD.native_signatures(text.replace('()I', '()J', 1))
        with self.assertRaises(ValueError):
            BUILD.native_signatures('')

    def test_duplicate_foreign_and_missing_native_mappings_refused(self):
        paths = [self.root / 'libjassimp.so', self.root / 'libassimp.so.4.1.0']
        for path in paths:
            path.write_bytes(path.name.encode())
        text = '\n'.join('mapped_library=' + str(path) for path in paths)
        self.assertEqual(set(BUILD.mapped_libraries(text, paths)), set(map(str, paths)))
        for bad in [text + '\n' + text.splitlines()[0], text.splitlines()[0],
                    text.replace(str(paths[0]), '/foreign/libjassimp.so')]:
            with self.subTest(text=bad), self.assertRaises(ValueError):
                BUILD.mapped_libraries(bad, paths)

    def test_child_compiler_java_and_cmake_injection_removed(self):
        injected = {'JAVA_TOOL_OPTIONS': '-javaagent:foreign', '_JAVA_OPTIONS': '-Xmx1m',
                    'JDK_JAVA_OPTIONS': '--patch-module foreign', 'CLASSPATH': '/foreign',
                    'CMAKE_PROJECT_INCLUDE': '/foreign/hook', 'CPATH': '/foreign',
                    'CONAN_HOME': '/foreign'}
        with patch.dict(os.environ, injected):
            env = BUILD.environment('/trusted/gcc', '/trusted/g++')
        for key in injected:
            self.assertNotIn(key, env)
        self.assertEqual(env['VCPKG_BINARY_SOURCES'], 'clear')

    def test_offline_cache_never_fetches_and_refuses_tampering(self):
        entry = {'bytes': 3, 'sha256': 'a' * 64, 'url': 'https://other.example/source'}
        with patch.object(BUILD.native.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError, 'offline'):
                BUILD.native.acquire(self.root, entry, False)
            (self.root / entry['sha256']).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                BUILD.native.acquire(self.root, entry, False)

    def test_pic_closure_requires_real_logger_provider_identity(self):
        core = self.root / 'libassimp.so.4.1.0'
        core.write_bytes(b'genuine source-built core')
        sha = BUILD.native.digest(core)
        elf = '(NEEDED) Shared library: [libassimp.so.4]\n(RPATH) Library rpath: [' + str(core.parent) + ']'
        BUILD.verify_pic_closure(elf, core, sha)
        for invalid in [elf.replace('libassimp.so.4]', 'foreign.so]'),
                        elf.replace(str(core.parent), '/foreign'), elf + '\n(TEXTREL)']:
            with self.subTest(elf=invalid), self.assertRaises(ValueError):
                BUILD.verify_pic_closure(invalid, core, sha)
        core.write_bytes(b'substituted core')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            BUILD.verify_pic_closure(elf, core, sha)

    def test_immutable_proof_outputs_are_regular_and_hash_bound(self):
        names = ('consumer-cpp', 'consumer-c', 'libjassimp.so', 'jassimp.jar',
                 'dependency-pic-check.so', 'valid/roundtrip.assbin')
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        original = BUILD.outputs(self.root)
        (self.root / 'jassimp.jar').write_bytes(b'replacement')
        self.assertNotEqual(original, BUILD.outputs(self.root))
        (self.root / 'jassimp.jar').unlink()
        (self.root / 'jassimp.jar').symlink_to(self.root / 'consumer-c')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            BUILD.outputs(self.root)


@unittest.skipUnless(os.environ.get('TAKX_NATIVE_ASSIMP_PROOF'), 'opt-in freshly built recipe proof required')
class ActualComponentProof(unittest.TestCase):
    def test_valid_component_jni_and_pic_receipt(self):
        root = Path(os.environ['TAKX_NATIVE_ASSIMP_PROOF']).resolve()
        receipt = json.loads((root / 'complete.json').read_text())
        self.assertEqual(receipt['profile'], 'public-assimp-native')
        self.assertEqual(receipt['recipe'], BUILD.recipe())
        self.assertEqual(receipt['probe_outputs'], BUILD.outputs(root))
        self.assertEqual(receipt['installed'], BUILD.native.inventory(root / 'install'))
        self.assertEqual(receipt['java_probe_classes'], BUILD.native.inventory(root / 'probe-classes'))
        BUILD.check_sources(root / 'source', receipt['source_postimages'])
        BUILD.las.verify_runtime(receipt['runtime_closure'])
        BUILD.las.verify_runtime(receipt['mapped_libraries'])
        tools = receipt['tools']
        jdk = Path(tools['java']['path']).parents[1]
        self.assertEqual(BUILD.sdk_inventory(jdk), json.loads((root / 'jdk-inputs.json').read_text()))
        env = BUILD.environment(tools['cc']['path'], tools['cxx']['path'])
        for item in tools.values():
            self.assertEqual(item['sha256'], BUILD.native.digest(Path(item['path'])))
        with tempfile.TemporaryDirectory() as logs:
            text = BUILD.native.run([tools['java']['path'], '-ea', '-Xcheck:jni', '-Djava.awt.headless=true',
                    '-cp', str(root / 'probe-classes') + ':' + str(root / 'jassimp.jar'), 'JassimpValidProbe',
                    str(root / 'libjassimp.so'), str(root / 'install/lib/libassimp.so.4.1.0'),
                    str(root / 'valid/roundtrip.assbin'), str(root / 'jassimp.jar')],
                    Path(logs), 'valid-control', timeout=30, env=env, capture=True).decode()
        self.assertNotIn('WARNING', text)
        self.assertNotIn('FATAL', text)
        self.assertEqual(receipt['mapped_libraries'], BUILD.mapped_libraries(text,
                         (root / 'libjassimp.so', root / 'install/lib/libassimp.so.4.1.0')))
        self.assertFalse(receipt['fault_parser_or_failure_path_tests_run'])
        self.assertFalse(receipt['kernel_sdk_acceptance'])
        self.assertFalse(receipt['takx_runtime_acceptance'])
        self.assertFalse(receipt['target_image_abi_acceptance'])


if __name__ == '__main__':
    unittest.main()
