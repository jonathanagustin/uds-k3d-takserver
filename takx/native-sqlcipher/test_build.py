# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline refusal tests; real source-built controls require explicit opt-in."""
import copy
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
SPEC = importlib.util.spec_from_file_location('sqlcipher_profile', HERE / 'build.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


class OfflineGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_official_origins_sizes_hashes_licenses_and_provenance_are_pinned(self):
        original = json.loads((HERE / 'inputs.lock.json').read_text())
        B.validate_lock(original)
        for section, name, field, value in [
                ('archives', 'openssl', 'url', 'https://unofficial.example/source'),
                ('archives', 'sqlcipher', 'sha256', 'f' * 64),
                ('archives', 'tcl', 'expanded_bytes', 1),
                ('archives', 'tcl', 'root', '../outside')]:
            lock = copy.deepcopy(original)
            lock[section][name][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                B.validate_lock(lock)
        for section in ('licenses', 'provenance', 'tools'):
            lock = copy.deepcopy(original)
            lock[section][next(iter(lock[section]))] = '../unreviewed'
            with self.subTest(section=section), self.assertRaises(ValueError):
                B.validate_lock(lock)

    def test_missing_tampered_and_symlink_cache_fail_without_network(self):
        entry = {'sha256': B.native.digest(HERE / 'build.py'), 'bytes': (HERE / 'build.py').stat().st_size}
        cache = self.root / 'cache'
        cache.mkdir()
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(ValueError, 'offline source cache'):
                B.native.acquire(cache, entry, False)
            target = cache / entry['sha256']
            target.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                B.native.acquire(cache, entry, False)
            target.unlink()
            target.symlink_to(HERE / 'build.py')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                B.native.acquire(cache, entry, False)

    def test_output_reuse_and_cache_overlap_never_remove_files(self):
        output, cache = self.root / 'output', self.root / 'cache'
        self.assertEqual(B.validate_paths(output, cache), (output, cache))
        for a, b in [(output, output), (output / 'inside', output), (output, output / 'cache')]:
            with self.assertRaises(ValueError):
                B.validate_paths(a, b)
        output.mkdir()
        marker = output / 'keep'
        marker.write_text('preserved')
        with self.assertRaises(ValueError):
            B.validate_paths(output, cache)
        self.assertEqual(marker.read_text(), 'preserved')

    def archive(self, names):
        path = self.root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name in names:
                member = tarfile.TarInfo(name)
                member.size, member.mtime = 4, 123456789
                archive.addfile(member, io.BytesIO(b'data'))
        return path

    def test_safe_unpack_keeps_vendor_timestamps_and_refuses_ambiguous_paths(self):
        entry = {'root': 'source', 'members': 1, 'regular_files': 1, 'expanded_bytes': 4}
        archive = self.archive(['source/input'])
        destination = self.root / 'valid'
        B.unpack(archive, destination, entry)
        self.assertEqual((destination / 'source/input').stat().st_mtime, 123456789)
        for index, names in enumerate([['source/../../escape'], ['source/input', 'source/./input']]):
            archive = self.archive(names)
            with self.subTest(names=names), self.assertRaises(ValueError):
                B.unpack(archive, self.root / ('bad' + str(index)), entry | {'members': len(names)})
        self.assertFalse((self.root / 'escape').exists())

    def test_expansion_count_and_links_fail_closed(self):
        entry = {'root': 'source', 'members': 1, 'regular_files': 1, 'expanded_bytes': 3}
        with self.assertRaisesRegex(ValueError, 'expansion'):
            B.unpack(self.archive(['source/input']), self.root / 'expanded', entry)
        archive = self.root / 'link.tar'
        with tarfile.open(archive, 'w') as stream:
            member = tarfile.TarInfo('source/link')
            member.type, member.linkname = tarfile.SYMTYPE, '/outside'
            stream.addfile(member)
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            B.unpack(archive, self.root / 'links', entry)

    def test_tcl_host_generator_and_host_zlib_are_refused(self):
        valid = 'NATIVE_TCLSH\t= ./${TCL_EXE}\nZLIB_OBJS = Zadler32.o Zcompress.o\nLIBS = -lm\n'
        B.audit_tcl(valid)
        for bad in [valid.replace('./${TCL_EXE}', '/usr/bin/tclsh'),
                    valid.replace('Zadler32.o', ''), valid.replace('-lm', '-lz -lm')]:
            with self.assertRaises(ValueError):
                B.audit_tcl(bad)

    def test_inherited_compiler_perl_tcl_openssl_and_make_injection_removed(self):
        dirty = {'CPATH': '/foreign', 'LD_PRELOAD': '/foreign', 'LD_AUDIT': '/foreign',
                 'TCL_LIBRARY': '/foreign', 'PERL5OPT': '-Mforeign', 'OPENSSL_CONF': '/foreign',
                 'MAKEFLAGS': '--eval=foreign', 'ac_cv_path_tclsh': '/foreign', 'CONAN_HOME': '/foreign'}
        tools = {name: {'path': '/explicit/' + name} for name in ('cc', 'ar', 'ranlib', 'perl')}
        with patch.dict(os.environ, dirty):
            env = B.environment(tools, self.root)
        for key in dirty:
            self.assertNotEqual(env.get(key), dirty[key])
        self.assertEqual(env['OPENSSL_CONF'], '/dev/null')
        self.assertEqual(env['CC'], '/explicit/cc')

    def test_source_mutations_added_files_and_symlinks_are_rejected(self):
        source = self.root / 'source'
        source.mkdir()
        path = source / 'input'
        path.write_bytes(b'initial')
        expected = {'input': {'bytes': 7, 'sha256': B.native.digest(path)}}
        B.check_sources(source, expected)
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            B.check_sources(source, expected)
        path.write_bytes(b'initial')
        extra = source / 'extra'
        extra.symlink_to(path)
        with self.assertRaises(ValueError):
            B.check_sources(source, expected)

    def test_foreign_header_and_runtime_provider_cannot_pass(self):
        with self.assertRaises(ValueError):
            B.audit_headers('/usr/include/openssl/crypto.h', self.root / 'include')
        for text in ['libcrypto.so.3 => /usr/lib/libcrypto.so.3 (0x1)', 'libc.so.6 => not found', '']:
            with self.assertRaises(ValueError):
                B.runtime_closure(text)

    def test_missing_tampered_or_linked_probe_outputs_are_rejected(self):
        for name in B.PROBES:
            (self.root / name).write_text(name)
        expected = B.probes(self.root)
        B.verify_probes(self.root, expected)
        path = self.root / B.PROBES[0]
        path.write_text('tampered')
        with self.assertRaises(ValueError):
            B.verify_probes(self.root, expected)
        path.unlink()
        path.symlink_to(self.root / B.PROBES[1])
        with self.assertRaises(ValueError):
            B.verify_probes(self.root, expected)


@unittest.skipUnless(os.environ.get('TAKX_SQLCIPHER_PROOF'), 'set TAKX_SQLCIPHER_PROOF to opt into real local proof')
class ActualNativeProof(unittest.TestCase):
    def test_real_source_recipe_runtime_and_encryption_controls(self):
        output = Path(os.environ['TAKX_SQLCIPHER_PROOF']).resolve()
        proof = json.loads((output / 'complete.json').read_text())
        self.assertEqual(proof['recipe'], B.recipe())
        self.assertEqual(proof['licenses'], B.PINNED['licenses'])
        self.assertEqual(proof['archives'], B.PINNED['archives'])
        for name, digest in B.PINNED['licenses'].items():
            self.assertEqual(B.native.digest(output / 'licenses' / name.replace('/', '__')), digest)
        self.assertTrue(proof['fresh_entrypoint'])
        self.assertFalse(proof['TAKX_acceptance'])
        B.verify_probes(output, proof['probe_outputs'])
        B.check_sources(output / 'source', json.loads((output / 'source-inputs.json').read_text()))
        for name, prefix in [('tcl', 'tcl-install'), ('openssl', 'openssl-install'), ('sqlcipher', 'sqlcipher-install')]:
            self.assertEqual(B.native.inventory(output / prefix), proof['installed'][name])
        for path, sha in proof['runtime_closure'].items():
            self.assertEqual(B.native.digest(Path(path)), sha)
        for item in proof['tools'].values():
            self.assertEqual(B.native.digest(Path(item['path'])), item['sha256'])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            env = B.environment(proof['tools'], output)
            result = B.native.run([str(output / 'sqlcipher-consumer'), str(target / 'fresh.db')],
                                  target, 'consumer', timeout=120, env=env, capture=True).decode()
            self.assertIn('encrypt_reopen_wrong_key=PASS', result)
            result = B.native.run([str(output / 'openssl-control')], target, 'openssl', env=env, capture=True).decode()
            self.assertIn('SHA256-positive=PASS', result)
