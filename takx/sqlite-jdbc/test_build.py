# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""No downloads, compilers or native execution in recipe guard tests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('sqlite_build', Path(__file__).with_name('build.py'))
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class BuildGuards(unittest.TestCase):
    def test_locked_inventory_and_exact_patch(self):
        lock = json.loads((build.HERE / 'inputs.lock.json').read_text())
        build.validate_lock(lock)
        altered = json.loads(json.dumps(lock)); altered['inputs'][0]['url'] = 'https://foreign/source'
        with self.assertRaises(ValueError): build.validate_lock(altered)
        self.assertEqual(len(lock['inputs']), 74)
        self.assertEqual(sum(e['bytes'] for e in lock['inputs']), 15814646)
        self.assertEqual(sum(e['path'].endswith('.java') for e in lock['inputs']), 59)
        self.assertEqual(build.digest(build.PATCH), build.PATCH_SHA)
        for entry in lock['inputs']:
            build.relative(entry['path'])
            self.assertTrue(entry['url'].startswith(('https://raw.githubusercontent.com/xerial/sqlite-jdbc/',
                                                    'https://www.sqlite.org/', 'https://repo.maven.apache.org/')))

    def test_corrupt_source_rejected(self):
        data = b'actual source'
        entry = {'path': 'source.c', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        build.checked(data, entry)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            build.checked(b'wrong source', entry)

    def test_unsafe_paths_and_archives(self):
        for value in ('/absolute', '../escape', 'safe/../../escape', 'bad\\path'):
            with self.assertRaises(ValueError):
                build.relative(value)
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr('../escape', 'bad')
            with self.assertRaises(ValueError):
                build.check_archive(archive)

    def test_unknown_or_corrupt_completed_cache_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            with self.assertRaisesRegex(ValueError, 'no completed'):
                build.validate_output(output, 'key')
            artifacts = {}
            for name in build.ARTIFACTS:
                path = output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
                artifacts[name] = build.digest(path)
            (output / 'sqlite-definitions.json').write_text('["sqlite3_open"]')
            record = {'sqlite_definitions_sha256': build.digest(output / 'sqlite-definitions.json'), 'jni_exports': ['JNI_OnLoad'], 'key': 'key', 'artifacts': artifacts, 'runtime_closure': {'libc': 'hash'}}
            (output / 'complete.json').write_text(json.dumps(record))
            with patch.object(build, 'runtime_closure', return_value={'libc': 'hash'}), patch.object(build, 'audit_native', return_value=['JNI_OnLoad']):
                self.assertEqual(build.validate_output(output, 'key'), record)
                with self.assertRaisesRegex(ValueError, 'different/unknown'):
                    build.validate_output(output, 'wrong-key')
                (output / build.ARTIFACTS[0]).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError, 'Corrupt'):
                    build.validate_output(output, 'key')

    def test_final_jni_policy_rejects_actual_backend_and_accidental_exports(self):
        good = '1: 000123 32 FUNC GLOBAL DEFAULT 12 Java_org_sqlite_core_NativeDB_open\n'
        self.assertEqual(build.audit_exports(good, {'sqlite3_open'}), ['Java_org_sqlite_core_NativeDB_open'])
        for bad in ['2: 000123 32 FUNC GLOBAL DEFAULT 12 sqlite3_open\n',
                    '2: 000000 0 FUNC GLOBAL DEFAULT UND sqlite3_open\n',
                    '2: 000123 32 FUNC GLOBAL DEFAULT 12 accidental_export\n']:
            with self.assertRaises(ValueError): build.audit_exports(good + bad, {'sqlite3_open'})
        self.assertEqual(build.defined_symbols('00000000 T sqlite3_open\n00000100 t internal_sqlite\n'), {'sqlite3_open', 'internal_sqlite'})

    def test_compiler_java_and_loader_injection_removed(self):
        import os
        injected = {'LD_PRELOAD': '/foreign', 'CCFLAGS': '/foreign', 'LINKFLAGS': '/foreign',
                    'MAKEFLAGS': '-j88', 'JAVA_TOOL_OPTIONS': '-Xmx9g', 'CLASSPATH': '/foreign',
                    'CPATH': '/foreign', 'SQLITE_FLAGS': '/foreign'}
        with patch.dict(os.environ, injected): env = build.clean_environment()
        for key in injected: self.assertNotIn(key, env)

    def test_recipe_key_includes_tools_and_sources(self):
        a, _ = build.build_key({'gcc': 'one'})
        b, _ = build.build_key({'gcc': 'two'})
        self.assertNotEqual(a, b)


@unittest.skipUnless(os.environ.get('TAKX_SQLITE_JDBC_PROOF'), 'explicit actual JDBC proof required')
class ActualJDBCProof(unittest.TestCase):
    def test_native_inventory_jdbc_and_both_real_global_load_orders(self):
        output = Path(os.environ['TAKX_SQLITE_JDBC_PROOF']).resolve()
        record = json.loads((output / 'complete.json').read_text())
        for tool in record['identity']['tools'].values():
            self.assertEqual(build.digest(Path(tool['path'])), tool['sha256'])
        key, identity = build.build_key(record['identity']['tools'])
        self.assertEqual(identity, record['identity']); build.validate_output(output, key)
        java_home = Path(record['identity']['tools']['java']['path']).parent.parent
        self.assertIn('PASS actual source-built SQLite JDBC/native:', build.smoke(output, java_home))
        isolation = build.load_orders(output, java_home, Path(os.environ['TAKX_SQLITE_CRYPTO_PROOF']).resolve(), Path(os.environ['TAKX_SQLITE_MODERN_PROOF']).resolve())
        self.assertTrue(isolation['both_rtld_global_orders'])
        self.assertEqual(isolation['crypto_receipt_sha256'], record['isolation']['crypto_receipt_sha256'])
        self.assertFalse(isolation['full_sdk_acceptance'])


if __name__ == '__main__':
    unittest.main()
