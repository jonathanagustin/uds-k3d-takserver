#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline integrity guards; these fixtures are never used as compiler dependencies."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
import warnings
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('kernel_compile_recipe', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
LOCK = json.loads((HERE / 'inputs.lock.json').read_text())


class CompilerGuards(unittest.TestCase):
    def test_complete_pinned_source_and_classpath_inventory(self):
        BUILD.validate_lock(LOCK)
        self.assertEqual(sum(LOCK['modules'].values()), 945)
        self.assertEqual(sum(v for k, v in LOCK['modules'].items() if '/engine/' in k), 862)
        self.assertEqual(sum(len(e['class_entries']) for e in LOCK['gis_java']['artifacts'].values()), 107)
        for key, value in [('revision', '0' * 40), ('java_release', 17), ('modules', {})]:
            wrong = copy.deepcopy(LOCK); wrong[key] = value
            with self.assertRaises(ValueError): BUILD.validate_lock(wrong)
        wrong = copy.deepcopy(LOCK); wrong['public_jars'].pop(next(iter(wrong['public_jars'])))
        with self.assertRaises(ValueError): BUILD.validate_lock(wrong)

    def test_profiles_preserve_baseline_and_require_complete_locks(self):
        baseline = BUILD.select_profile(LOCK, 'baseline')
        patched = BUILD.select_profile(LOCK, 'patched')
        self.assertEqual(baseline['public_jars'], LOCK['public_jars'])
        self.assertEqual(len(patched['public_jars']), 23)
        self.assertEqual(len(set(baseline['public_jars']) & set(patched['public_jars'])), 17)
        self.assertNotIn('guava-30.0-jre.jar', patched['public_jars'])
        wrong = copy.deepcopy(LOCK); wrong['patched_replacements'].pop('guava-30.0-jre.jar')
        with self.assertRaises(ValueError): BUILD.select_profile(wrong, 'patched')
        with self.assertRaises(ValueError): BUILD.select_profile(LOCK, 'unknown')

    def test_dependency_origin_and_size_guards(self):
        for url in ('http://repo.maven.apache.org/a.jar', 'https://example.com/a.jar', 'https://user:password@repo.maven.apache.org/a.jar'):
            wrong = copy.deepcopy(LOCK)
            entry = next(iter(wrong['public_jars'].values())); entry['url'] = url
            with self.assertRaises(ValueError): BUILD.validate_lock(wrong)
        wrong = copy.deepcopy(LOCK); next(iter(wrong['public_jars'].values()))['bytes'] = 0
        with self.assertRaises(ValueError): BUILD.validate_lock(wrong)

    def test_cached_bytes_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); target = root / 'fixture.jar'; target.write_bytes(b'archive')
            entry = {'bytes': 7, 'sha256': hashlib.sha256(b'archive').hexdigest()}
            self.assertEqual(BUILD.public_jar(root, target.name, entry, False), target)
            target.write_bytes(b'changed')
            with self.assertRaises(ValueError): BUILD.public_jar(root, target.name, entry, True)
            self.assertEqual(target.read_bytes(), b'changed')
            with self.assertRaises(ValueError): BUILD.public_jar(root, 'missing.jar', entry, False)
            self.assertFalse((root / 'missing.jar').exists())
            link = root / 'link.jar'; link.symlink_to(target)
            with self.assertRaises(ValueError): BUILD.verified_jar(link, entry)

    def test_gis_container_metadata_may_change_but_class_bytes_may_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            expected = {'fixture/Entry.class': hashlib.sha256(b'bytecode fixture').hexdigest()}
            def archive(name, data=b'bytecode fixture', extra=False):
                path = root / name
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('fixture/Entry.class', data)
                    z.writestr('META-INF/NOTICE', name)
                    if extra: z.writestr('fixture/Unexpected.class', b'extra')
                return path
            first, second = archive('first.jar'), archive('second.jar')
            self.assertNotEqual(BUILD.digest(first), BUILD.digest(second))
            BUILD.verified_class_entries(first, expected); BUILD.verified_class_entries(second, expected)
            with self.assertRaises(ValueError): BUILD.verified_class_entries(archive('changed.jar', b'changed'), expected)
            with self.assertRaises(ValueError): BUILD.verified_class_entries(archive('extra.jar', extra=True), expected)

    def test_gis_duplicate_native_and_traversal_entries_fail(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ('../outside', 'libnative.so', 'unexpected.txt'):
                path = Path(d) / 'bad.jar'
                with zipfile.ZipFile(path, 'w') as z: z.writestr(bad, b'x')
                with self.assertRaises(ValueError): BUILD.class_entries(path)
            path = Path(d) / 'duplicate.jar'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('fixture/Entry.class', b'a'); z.writestr('fixture/Entry.class', b'b')
            with self.assertRaises(ValueError): BUILD.class_entries(path)

    @staticmethod
    def adapter_repository(root):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT)
        git('init', '-q')
        git('config', 'user.name', 'uds-takserver-test')
        git('config', 'user.email', 'test@example.invalid')
        source = root / 'takx/compat/src/main/java/fixture/Entry.java'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'class Entry {}\n')
        (root / '.gitignore').write_text('Ignored.java\n')
        (root / 'README.md').write_text('unrelated document\n')
        git('add', '.'); git('commit', '-qm', 'test fixture')
        return source, git

    def test_adapter_snapshot_binds_committed_bytes_and_allows_unrelated_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source, git = self.adapter_repository(root)
            (root / 'README.md').write_text('changed unrelated document\n')
            (root / 'unrelated.java').write_text('outside consumed tree\n')
            commit, snapshot = BUILD.adapter_sources(root)
            self.assertEqual(commit, git('rev-parse', 'HEAD').decode().strip())
            self.assertEqual(snapshot, {'fixture/Entry.java': b'class Entry {}\n'})
            # A later worktree edit cannot alter the verified bytes written to the proof.
            source.write_bytes(b'class Altered {}\n')
            self.assertEqual(snapshot['fixture/Entry.java'], b'class Entry {}\n')

    def test_adapter_boundary_rejects_changed_staged_untracked_and_ignored_java(self):
        for case in ('modified', 'staged', 'assume-unchanged', 'untracked', 'ignored', 'deleted'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                root = Path(d); source, git = self.adapter_repository(root)
                if case in ('modified', 'staged', 'assume-unchanged'):
                    if case == 'assume-unchanged': git('update-index', '--assume-unchanged', str(source))
                    source.write_text('class Changed {}\n')
                    if case == 'staged': git('add', str(source))
                elif case == 'deleted':
                    source.unlink()
                else:
                    (source.parent / ('Ignored.java' if case == 'ignored' else 'Extra.java')).write_text('class Extra {}\n')
                with self.assertRaises(ValueError): BUILD.adapter_sources(root)

    def test_adapter_boundary_rejects_source_and_directory_symlinks(self):
        for case in ('source', 'directory', 'committed-link'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                root = Path(d); source, git = self.adapter_repository(root)
                if case in ('source', 'committed-link'):
                    target = root / 'original'; target.write_bytes(source.read_bytes())
                    source.unlink(); source.symlink_to(target)
                    if case == 'committed-link':
                        git('add', str(source)); git('commit', '-qm', 'link fixture')
                else:
                    original = root / 'original-directory'
                    source.parent.rename(original); source.parent.symlink_to(original, target_is_directory=True)
                with self.assertRaises(ValueError): BUILD.adapter_sources(root)

    def test_new_external_output_and_argument_quoting(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError): BUILD.fresh_output(root)
            with self.assertRaises(ValueError): BUILD.fresh_output(BUILD.REPO / 'not-created-output')
            link = root / 'link'; link.symlink_to(root / 'not-created')
            with self.assertRaises(ValueError): BUILD.fresh_output(link)
            new = root / 'spaces in output'
            self.assertEqual(BUILD.fresh_output(new), new)
            self.assertFalse(new.exists())
            self.assertEqual(BUILD.quoted_argument('a b/"x".java'), '"a b/\\"x\\".java"\n')


if __name__ == '__main__':
    unittest.main()
