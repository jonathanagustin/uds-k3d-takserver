#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline source/cache guards, not fabricated GIS or JNI acceptance."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gis_java_build', HERE / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class SourceAndCacheGuards(unittest.TestCase):
    def archive(self, root, names):
        path = root / 'fixture.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, kind in names:
                member = tarfile.TarInfo(name)
                if kind == 'link':
                    member.type = tarfile.SYMTYPE
                    member.linkname = '/outside'
                    archive.addfile(member)
                else:
                    data = b'fixture source, not an SDK implementation'
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        return path

    def test_official_revision_url_and_target_are_consistent(self):
        lock = json.loads((HERE / 'sources.lock.json').read_text())
        build.validate_lock(lock)
        for field, value in (('revision', 'b' * 40), ('repository', 'https://unreviewed.invalid/source'),
                             ('java_release', 17)):
            changed = {**lock, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                build.validate_lock(changed)

    def test_integrity_accepts_only_exact_size_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'archive'
            path.write_bytes(b'exact fixture')
            entry = {'bytes': path.stat().st_size, 'sha256': build.digest(path)}
            self.assertEqual(build.verified(path, entry), path)
            path.write_bytes(b'wrong fixture')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                build.verified(path, entry)
            link = Path(tmp) / 'link'; link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'integrity'):
                build.verified(link, {'bytes': path.stat().st_size, 'sha256': build.digest(path)})

    def test_offline_cache_never_downloads_or_replaces_corruption(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build.urllib.request, 'urlopen') as network:
            cache = Path(tmp)
            entry = {'bytes': 3, 'sha256': hashlib.sha256(b'abc').hexdigest()}
            with self.assertRaisesRegex(ValueError, 'missing'):
                build.archive(cache, entry, True)
            path = cache / (entry['sha256'] + '.tar.gz')
            path.write_bytes(b'abc')
            self.assertEqual(build.archive(cache, entry, True), path)
            path.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                build.archive(cache, entry, False)
            self.assertEqual(path.read_bytes(), b'bad')
            network.assert_not_called()

    def test_invalid_download_never_becomes_a_cache_entry(self):
        for response in (b'too large', b'bad'):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp)
                entry = {'bytes': 3, 'sha256': hashlib.sha256(b'abc').hexdigest(), 'url': 'https://fixture.invalid/source'}
                with patch.object(build.urllib.request, 'urlopen', return_value=io.BytesIO(response)):
                    with self.assertRaises(ValueError):
                        build.archive(cache, entry, False)
                self.assertEqual(list(cache.iterdir()), [])

    def test_safe_source_selection_and_no_models_or_native_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.archive(root, [('gdal/swig/include/Dataset.i', 'file'), ('gdal/unrelated.exe', 'file')])
            chosen = build.extract(path, root / 'stage', 'gdal')
            self.assertEqual(chosen, {'gdal/swig/include/Dataset.i'})
            self.assertFalse((root / 'stage/gdal/unrelated.exe').exists())

    def test_traversal_absolute_links_and_duplicate_paths_fail_closed(self):
        for names in ([('../escape', 'file')], [('/absolute', 'file')],
                      [('gdal/swig/include/Dataset.i', 'link')],
                      [('gdal/swig/include/Dataset.i', 'file')] * 2):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaises(ValueError):
                    build.extract(self.archive(root, names), root / 'stage', 'gdal')
                self.assertFalse((root / 'escape').exists())

    def test_checkout_output_and_root_symlinks_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            build.external(build.REPO / 'build-gis')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); link = root / 'link'; link.symlink_to(root / 'other')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                build.external(link)

    def test_unknown_incomplete_changed_and_extra_completed_state_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(build.completed(root, 'key'))
            (root / 'artifact.jar').write_bytes(b'fixture output')
            with self.assertRaisesRegex(ValueError, 'unknown or incomplete'):
                build.completed(root, 'key')
            state = {'input_key': 'key', 'outputs': build.output_files(root)}
            (root / 'build-state.json').write_text(json.dumps(state))
            self.assertTrue(build.completed(root, 'key'))
            with self.assertRaisesRegex(ValueError, 'changed'):
                build.completed(root, 'other key')
            (root / 'extra').write_text('unknown')
            with self.assertRaisesRegex(ValueError, 'unknown'):
                build.completed(root, 'key')
            (root / 'extra').unlink()
            (root / 'nested').mkdir(); (root / 'nested/build-state.json').write_text('unknown nested file')
            with self.assertRaisesRegex(ValueError, 'unknown'):
                build.completed(root, 'key')
            (root / 'nested/build-state.json').unlink()
            (root / 'artifact.jar').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'corrupt'):
                build.completed(root, 'key')

    def test_recipe_probe_tool_or_source_change_invalidates_key(self):
        lock = json.loads((HERE / 'sources.lock.json').read_text())
        first = build.fingerprint(lock, {'tool': 'one'})[0]
        self.assertNotEqual(first, build.fingerprint(lock, {'tool': 'two'})[0])
        lock['revision'] = 'different source'
        self.assertNotEqual(first, build.fingerprint(lock, {'tool': 'one'})[0])
        with patch.object(build, 'digest', return_value='changed recipe or probe'):
            self.assertNotEqual(first, build.fingerprint(lock, {'tool': 'one'})[0])


if __name__ == '__main__':
    unittest.main()
