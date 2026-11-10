# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline integrity/cleanup guards and opt-in complete source builds."""

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('ui_java_build', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
LOCK = json.loads(BUILD.LOCK.read_text())
SOURCE_DIR = os.environ.get('UI_JAVA_SOURCES_DIR')
CLASSPATH_DIR = os.environ.get('UI_JAVA_CLASSPATH_DIR')
JAVA_HOME = os.environ.get('JAVA_HOME')


def fixture_archive(root, entries):
    path = root / 'source.tar.gz'
    with tarfile.open(path, 'w:gz') as archive:
        for name, data, kind in entries:
            item = tarfile.TarInfo(name)
            item.type = kind
            if kind == tarfile.SYMTYPE:
                item.linkname = '/not-a-source-input'
            elif kind == tarfile.REGTYPE:
                item.size = len(data)
            archive.addfile(item, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    descriptor = {'prefix': 'source/', 'bytes': path.stat().st_size, 'sha256': BUILD.sha256(path)}
    return path, descriptor


class OfflineGuardTests(unittest.TestCase):
    def test_default_profile_keeps_wizard_experimental_and_version_gaps_explicit(self):
        normal = BUILD.selected_artifacts(LOCK, 'original')
        self.assertEqual(len(normal), 5)
        self.assertNotIn('wizard-reference', normal)
        self.assertIn('NOT requested1.1', normal['colorchooser-author-1.5']['identity']['project_identity'])
        reference = BUILD.selected_artifacts(LOCK, 'wizard-reference')['wizard-reference']
        self.assertEqual(reference['classification'], 'experimental-source-reference')
        self.assertIn('NOT exact rev-28122010', reference['identity']['project_identity'])
        for changed in ('profile', 'classification'):
            value = copy.deepcopy(LOCK)
            if changed == 'profile':
                value['profiles']['original'].append('wizard-reference')
            else:
                value['artifacts']['wizard-reference']['classification'] = 'established-original'
            with self.assertRaises(BUILD.BuildFailure):
                BUILD.selected_artifacts(value, 'original')
        with self.assertRaises(BUILD.BuildFailure):
            BUILD.selected_artifacts(LOCK, 'unknown')

    def test_missing_sources_fail_before_parsing_tools_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(BUILD.tarfile, 'open') as parse, patch.object(BUILD, 'run_tool') as tool:
                with self.assertRaisesRegex(BUILD.BuildFailure, 'source archive size/type'):
                    BUILD.build(root, root, root / 'output', root, 'original')
                parse.assert_not_called()
                tool.assert_not_called()
            self.assertFalse((root / 'output').exists())

    def test_same_size_changed_archive_fails_before_tar_parser(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = LOCK['archives']['wizard-reference']
            source = root / expected['file']
            with source.open('wb') as stream:
                stream.truncate(expected['bytes'])
            with patch.object(BUILD.tarfile, 'open') as parse:
                with self.assertRaisesRegex(BUILD.BuildFailure, 'SHA-256'):
                    BUILD.extract_source(source, expected, lambda name: True, root / 'source')
                parse.assert_not_called()
            self.assertFalse((root / 'source').exists())

    def test_same_size_changed_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'dependency.jar'
            source.write_bytes(b'changed')
            expected = {'bytes': 7, 'sha256': hashlib.sha256(b'correct').hexdigest()}
            with self.assertRaisesRegex(BUILD.BuildFailure, 'SHA-256'):
                BUILD.checked_file(source, expected, 'dependency JAR')

    def test_source_selection_preserves_exact_bytes_and_rejects_unsafe_members(self):
        cases = [
            [('source/../escape.java', b'bad', tarfile.REGTYPE)],
            [('source/src/A.java', b'', tarfile.SYMTYPE)],
            [('source/src/A.java', b'a', tarfile.REGTYPE), ('source/src/A.java', b'b', tarfile.REGTYPE)],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, descriptor = fixture_archive(root, entries)
                with self.assertRaises(BUILD.BuildFailure):
                    BUILD.extract_source(source, descriptor, lambda name: name.endswith('.java'), root / 'selected')
                self.assertFalse((root / 'selected').exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, descriptor = fixture_archive(root, [
                ('source/src/A.java', b'original source\r\n', tarfile.REGTYPE),
                ('source/ignored.txt', b'not a selected resource', tarfile.REGTYPE)])
            files = BUILD.extract_source(source, descriptor, lambda name: name.endswith('.java'), root / 'selected')
            self.assertEqual(files, {'src/A.java': b'original source\r\n'})
            self.assertFalse((root / 'selected/ignored.txt').exists())

    def test_inventory_rejects_missing_extra_and_changed_sources_or_resources(self):
        original = {'a': b'A', 'b': b'B'}
        expected = {'count': 2, 'inventory_sha256': BUILD.canonical_hash(BUILD.inventory(original))}
        BUILD.checked_inventory(original, expected, 'fixture')
        for files in ({'a': b'A'}, {**original, 'c': b'C'}, {**original, 'a': b'X'}):
            with self.subTest(files=files), self.assertRaisesRegex(BUILD.BuildFailure, 'inventory mismatch'):
                BUILD.checked_inventory(files, expected, 'fixture')

    def test_packaging_is_deterministic_and_keeps_resource_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = BUILD.package(root / 'first.jar', {'z/resource': b'\x00\xff', 'a/license': b'notice'})
            second = BUILD.package(root / 'second.jar', {'a/license': b'notice', 'z/resource': b'\x00\xff'})
            self.assertEqual(first['sha256'], second['sha256'])
            with zipfile.ZipFile(root / 'first.jar') as archive:
                self.assertEqual(archive.namelist(), ['a/license', 'z/resource'])
                self.assertEqual(archive.read('z/resource'), b'\x00\xff')
                for entry in archive.infolist():
                    self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                    self.assertEqual(entry.external_attr >> 16, 0o100644)

    def test_failed_and_timed_out_builds_remove_partial_products(self):
        for timed_out in (False, True):
            with self.subTest(timed_out=timed_out), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises(BUILD.BuildFailure):
                    with BUILD.workspace(root / 'output') as (_, product):
                        (product / 'partial.jar').write_bytes(b'not accepted')
                        if timed_out:
                            BUILD.run_tool([sys.executable, '-c', 'import time; time.sleep(10)'],
                                           product / 'logs', 'fixture', 0.05)
                        raise BUILD.BuildFailure('fixture compile failed')
                self.assertEqual(list(root.iterdir()), [])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, report = root / 'output', root / 'failure.json'

            def timeout_build(source, classpath, destination, java, profile, timeout):
                with BUILD.workspace(destination) as (_, product):
                    (product / 'partial.jar').write_bytes(b'not accepted')
                    child = ("import sys,time; "
                             "sys.stdout.write('x'*70000+'\\nretained stdout diagnostic\\n'); sys.stdout.flush(); "
                             "sys.stderr.write('y'*70000+'\\nretained stderr diagnostic\\n'); sys.stderr.flush(); "
                             "time.sleep(10)")
                    BUILD.run_tool([sys.executable, '-c', child], product / 'logs', 'fixture', timeout)

            args = [str(BUILD.HERE / 'build.py'), '--sources-dir', str(root), '--classpath-dir', str(root),
                    '--output', str(output), '--java-home', str(root), '--timeout-seconds', '1',
                    '--failure-report', str(report)]
            # Exercise the real child deadline, workspace cleanup and CLI report
            # writer without requiring third-party sources or a Java compiler.
            stderr = io.StringIO()
            with patch.object(BUILD, 'build', side_effect=timeout_build), patch.object(sys, 'argv', args), \
                    patch.object(sys, 'stderr', stderr):
                with self.assertRaises(SystemExit) as exited:
                    BUILD.main()
            self.assertEqual(exited.exception.code, 1)
            self.assertIn('fixture timed out', stderr.getvalue())
            failure = json.loads(report.read_text())
            self.assertIn('timed out', failure['error'])
            for stream in ('stdout', 'stderr'):
                tail = failure['details'][stream + '_tail']
                self.assertLessEqual(len(tail), 65536)
                self.assertTrue(tail.endswith('retained ' + stream + ' diagnostic\n'))
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [report])

    def test_existing_or_concurrently_created_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            output.mkdir()
            marker = output / 'user-file'
            marker.write_bytes(b'preserved')
            with self.assertRaises(BUILD.BuildFailure):
                with BUILD.workspace(output):
                    self.fail('must not enter with existing output')
            self.assertEqual(marker.read_bytes(), b'preserved')
            output2 = root / 'created-during-build'
            with self.assertRaises(BUILD.BuildFailure):
                with BUILD.workspace(output2):
                    output2.mkdir()
                    (output2 / 'user-file').write_bytes(b'preserved too')
            self.assertEqual((output2 / 'user-file').read_bytes(), b'preserved too')
            self.assertFalse(list(root.glob('.ui-java-*')))


@unittest.skipUnless(SOURCE_DIR and CLASSPATH_DIR and JAVA_HOME,
                     'set UI_JAVA_SOURCES_DIR, UI_JAVA_CLASSPATH_DIR and JAVA_HOME for complete source builds')
class CompleteSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.first = {}
        for profile in BUILD.PROFILES:
            cls.first[profile] = BUILD.build(Path(SOURCE_DIR), Path(CLASSPATH_DIR), cls.root / profile,
                                             Path(JAVA_HOME), profile)

    def test_complete_source_resources_and_identity_receipts(self):
        for profile, receipt in self.first.items():
            self.assertFalse(receipt['complete_client_or_runtime_acceptance'])
            self.assertEqual(len(receipt['artifacts']), 5 if profile == 'original' else 1)
            for name, artifact in zip(BUILD.PROFILES[profile], receipt['artifacts']):
                expected = LOCK['artifacts'][name]
                self.assertEqual(len(artifact['java_sources']), expected['java']['count'])
                self.assertEqual(len(artifact['class_files']), expected['reference_class_files'])
                self.assertEqual(len(artifact['resources']), expected['resources']['count'])
                self.assertFalse(artifact['complete_client_or_runtime_acceptance'])
                with zipfile.ZipFile(self.root / profile / artifact['artifact']['file']) as archive:
                    for resource in artifact['resources'] + artifact['licenses']:
                        self.assertEqual(hashlib.sha256(archive.read(resource['path'])).hexdigest(), resource['sha256'])
                    identity = json.loads(archive.read('META-INF/UPSTREAM-SOURCE.json'))
                    self.assertEqual(identity['classification'], expected['classification'])
                    self.assertEqual(identity['project_identity'], expected['identity']['project_identity'])

    def test_two_clean_builds_produce_identical_binary_and_source_jars(self):
        for profile, first in self.first.items():
            second = BUILD.build(Path(SOURCE_DIR), Path(CLASSPATH_DIR), self.root / (profile + '-second'),
                                 Path(JAVA_HOME), profile)
            for before, after in zip(first['artifacts'], second['artifacts']):
                self.assertEqual(before['artifact'], after['artifact'])
                self.assertEqual(before['source_archive'], after['source_archive'])


if __name__ == '__main__':
    unittest.main()
