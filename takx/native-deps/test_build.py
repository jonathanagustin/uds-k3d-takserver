# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
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
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_dependencies', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reviewed_lock_and_foreign_header_origin(self):
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        BUILD.validate_lock(lock)
        lock['headers'][0]['url'] = 'https://example.invalid/replacement.h'
        with self.assertRaisesRegex(ValueError, 'origin'):
            BUILD.validate_lock(lock)

    def test_header_cannot_select_other_pinned_repository_path(self):
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        lock['headers'][0]['url'] = lock['headers'][1]['url']
        with self.assertRaisesRegex(ValueError, 'source path'):
            BUILD.validate_lock(lock)

    def test_cached_corruption_and_symlink_are_refused(self):
        good = b'locked public bytes'
        entry = {'bytes': len(good), 'sha256': hashlib.sha256(good).hexdigest()}
        path = self.root / entry['sha256']
        path.write_bytes(good)
        self.assertEqual(BUILD.acquire(self.root, entry, False), path)
        path.write_bytes(b'x' * len(good))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            BUILD.acquire(self.root, entry, False)
        path.unlink()
        other = self.root / 'other'
        other.write_bytes(good)
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            BUILD.acquire(self.root, entry, False)

    def test_download_does_not_adopt_or_delete_another_partial(self):
        data = b'verified source bytes'
        entry = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                 'url': 'https://example.invalid/fixture'}
        other = self.root / (entry['sha256'] + '.partial')
        other.write_bytes(b'another invocation owns this')
        with patch.object(BUILD.urllib.request, 'urlopen', return_value=io.BytesIO(data)):
            target = BUILD.acquire(self.root, entry, True)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(other.read_bytes(), b'another invocation owns this')

    def test_offline_missing_input_cannot_download(self):
        with self.assertRaisesRegex(ValueError, 'offline'):
            BUILD.acquire(self.root, {'sha256': 'a' * 64}, False)

    def archive(self, members):
        path = self.root / 'headers.tar'
        with tarfile.open(path, 'w') as archive:
            for name, content, link in members:
                item = tarfile.TarInfo(name)
                if link:
                    item.type = tarfile.SYMTYPE
                    item.linkname = '/etc/passwd'
                    archive.addfile(item)
                else:
                    item.size = len(content)
                    archive.addfile(item, io.BytesIO(content))
        return path

    def selection(self):
        data = b'genuine header'
        return {'path': './library/api.h', 'destination': 'include/library/api.h',
                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def test_archive_selected_hash_and_no_unselected_extraction(self):
        entry = self.selection()
        path = self.archive([('./library/api.h', b'genuine header', False),
                             ('unselected.bin', b'not exported', False)])
        BUILD.unpack_selected(path, [entry], self.root / 'out')
        self.assertEqual((self.root / 'out/include/library/api.h').read_bytes(), b'genuine header')
        self.assertFalse((self.root / 'out/unselected.bin').exists())

    def test_archive_duplicate_or_symlink_does_not_replace_header(self):
        entry = self.selection()
        for members in [
            [('./library/api.h', b'', True)],
            [('./library/api.h', b'genuine header', False), ('library/api.h', b'genuine header', False)],
        ]:
            with self.subTest(members=members):
                with self.assertRaisesRegex(ValueError, 'nonregular|ambiguous'):
                    BUILD.unpack_selected(self.archive(members), [entry], self.root / 'out')

    def test_archive_hash_and_traversal_fail(self):
        entry = self.selection()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            BUILD.unpack_selected(self.archive([('library/api.h', b'changed header', False)]),
                                  [entry], self.root / 'out')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            BUILD.unpack_selected(self.archive([('../outside', b'bad', False)]),
                                  [entry], self.root / 'out')

    def fixture_git(self):
        source = self.root / 'repo'
        source.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q')
        git('config', 'user.name', 'jonathanagustin')
        git('config', 'user.email', '5193877+jonathanagustin@users.noreply.github.com')
        (source / '.gitignore').write_text('ignored*\n')
        (source / 'draco').mkdir()
        (source / 'draco/CMakeLists.txt').write_text('project(fixture)\n')
        fixture = source / 'draco/cube.obj'
        fixture.write_text('v 0 0 0\n')
        git('add', '.')
        git('commit', '-qm', 'fixture')
        lock = {'revision': git('rev-parse', 'HEAD'), 'draco': {'tree': git('rev-parse', 'HEAD:draco'),
                'bytes': 25, 'files': 2, 'fixture': 'cube.obj', 'fixture_sha256': BUILD.digest(fixture)}}
        lock['draco']['bytes'] = sum(p.stat().st_size for p in (source / 'draco').iterdir())
        output = self.root / 'proof'
        output.mkdir()
        return source, output, lock

    def test_partial_clone_cannot_lazily_fetch_missing_objects(self):
        source, output, lock = self.fixture_git()
        blob = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD:draco/cube.obj'],
                                       text=True).strip()
        (source / '.git/objects' / blob[:2] / blob[2:]).unlink()
        config = {'core.repositoryformatversion': '1', 'extensions.partialClone': 'fixture',
                  'remote.fixture.url': 'fixture://public-source', 'remote.fixture.promisor': 'true',
                  'remote.fixture.partialclonefilter': 'blob:none', 'protocol.fixture.allow': 'always'}
        for name, value in config.items():
            subprocess.run(['git', '-C', str(source), 'config', name, value], check=True)
        helpers = self.root / 'helpers'
        helpers.mkdir()
        marker = self.root / 'remote-called'
        helper = helpers / 'git-remote-fixture'
        helper.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nPath(' +
                          repr(str(marker)) + ').touch()\nraise SystemExit(1)\n')
        helper.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(helpers) + os.pathsep + os.environ['PATH']}):
            control = subprocess.run(['git', '-C', str(source), 'cat-file', '-p', blob],
                                     capture_output=True, timeout=5)
            self.assertNotEqual(control.returncode, 0)
            self.assertTrue(marker.exists())
            marker.unlink()
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.git(source, 'cat-file', '-p', blob)
            self.assertFalse(marker.exists())
            # Complete local worktree bytes still freeze against the pinned blob IDs.
            BUILD.freeze(source, output, lock)
            self.assertFalse(marker.exists())

    def test_git_export_is_frozen_and_worktree_tamper_is_refused(self):
        source, output, lock = self.fixture_git()
        staged = BUILD.freeze(source, output, lock)
        before = (staged / 'CMakeLists.txt').read_bytes()
        (source / 'draco/CMakeLists.txt').write_text('altered source\n')
        self.assertEqual((staged / 'CMakeLists.txt').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'modified'):
            BUILD.freeze(source, output, lock)

    def test_untracked_ignored_native_input_is_refused(self):
        source, output, lock = self.fixture_git()
        (source / 'draco/ignored-generated.cpp').write_text('unexpected code')
        with self.assertRaisesRegex(ValueError, 'untracked'):
            BUILD.freeze(source, output, lock)

    def test_wrong_revision_and_source_inventory_are_refused(self):
        source, output, lock = self.fixture_git()
        wrong = copy.deepcopy(lock)
        wrong['revision'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'revision'):
            BUILD.freeze(source, output, wrong)
        lock['draco']['files'] = 3
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            BUILD.freeze(source, output, lock)

    def test_probe_byte_changes_and_symlinks_fail_before_execution(self):
        for name in BUILD.PROBE_OUTPUTS:
            (self.root / name).write_bytes(b'known probe output')
        expected = BUILD.probe_inventory(self.root)
        BUILD.verify_probe_outputs(self.root, expected)
        (self.root / 'consumer').write_bytes(b'changed probe data')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            BUILD.verify_probe_outputs(self.root, expected)
        (self.root / 'consumer').unlink()
        target = self.root / 'elsewhere'
        target.write_bytes(b'known probe output')
        (self.root / 'consumer').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            BUILD.verify_probe_outputs(self.root, expected)

    def test_ambient_build_hook_and_flags_cannot_override_profile(self):
        tools = {'cc': {'path': '/trusted/gcc'}, 'cxx': {'path': '/trusted/g++'}}
        with patch.dict(os.environ, {'CXXFLAGS': '-fno-pic', 'CPATH': '/foreign/headers',
                                     'CMAKE_PROJECT_TOP_LEVEL_INCLUDES': '/foreign/hook.cmake',
                                     'VCPKG_BINARY_SOURCES': 'foreign-cache'}):
            env = BUILD.build_environment(tools)
        self.assertNotIn('CXXFLAGS', env)
        self.assertNotIn('CPATH', env)
        self.assertNotIn('CMAKE_PROJECT_TOP_LEVEL_INCLUDES', env)
        self.assertEqual(env['VCPKG_BINARY_SOURCES'], 'clear')
        self.assertEqual(env['CC'], '/trusted/gcc')

    def test_owned_command_deadline_and_complete_output_bound(self):
        start = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'timed out'):
            BUILD.run([sys.executable, '-c', 'import time; time.sleep(30)'], self.root,
                      'timeout', timeout=0.05)
        self.assertLess(time.monotonic() - start, 2)
        with self.assertRaisesRegex(ValueError, 'exceeds bound'):
            BUILD.run([sys.executable, '-c', 'print("x"*4096)'], self.root,
                      'too-large', limit=256)


@unittest.skipUnless(os.environ.get('TAKX_NATIVE_DEPS_PROOF'), 'opt-in real source-built proof required')
class ActualCodecTests(unittest.TestCase):
    def test_real_codec_and_pic_output(self):
        proof = Path(os.environ['TAKX_NATIVE_DEPS_PROOF']).resolve()
        receipt = json.loads((proof / 'complete.json').read_text())
        self.assertEqual(receipt['recipe'], {p.name: BUILD.digest(p) for p in
                         (HERE / 'build.py', HERE / 'inputs.lock.json', HERE / 'DracoSourceProbe.cpp')})
        self.assertEqual(receipt['installed'], BUILD.inventory(proof / 'install'))
        BUILD.verify_probe_outputs(proof, receipt['probe_outputs'])
        result = subprocess.run([str(proof / 'consumer'), str(proof / 'cube.drc')],
                                capture_output=True, check=True, timeout=10)
        self.assertIn(b'truncation_rejected=true', result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'truncated.drc'
            bad.write_bytes((proof / 'cube.drc').read_bytes()[:1])
            rejected = subprocess.run([str(proof / 'install/bin/draco_decoder'), '-i', str(bad),
                                       '-o', str(Path(tmp) / 'bad.obj')], capture_output=True, timeout=10)
            self.assertNotEqual(rejected.returncode, 0)
        result = subprocess.run(['readelf', '-d', str(proof / 'libdraco-pic-check.so')],
                                capture_output=True, check=True, timeout=10)
        self.assertNotIn(b'TEXTREL', result.stdout)
        self.assertFalse(receipt['kernel_sdk_acceptance'])
        self.assertFalse(receipt['takx_acceptance'])


if __name__ == '__main__':
    unittest.main()
