# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""No downloads, compilers or native execution in recipe guard tests."""
import hashlib
import importlib.util
import json
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
            record = {'key': 'key', 'artifacts': artifacts, 'runtime_closure': {'libc': 'hash'}}
            (output / 'complete.json').write_text(json.dumps(record))
            with patch.object(build, 'runtime_closure', return_value={'libc': 'hash'}):
                self.assertEqual(build.validate_output(output, 'key'), record)
                with self.assertRaisesRegex(ValueError, 'different/unknown'):
                    build.validate_output(output, 'wrong-key')
                (output / build.ARTIFACTS[0]).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError, 'Corrupt'):
                    build.validate_output(output, 'key')

    def test_recipe_key_includes_tools_and_sources(self):
        a, _ = build.build_key({'gcc': 'one'})
        b, _ = build.build_key({'gcc': 'two'})
        self.assertNotEqual(a, b)


if __name__ == '__main__':
    unittest.main()
