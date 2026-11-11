#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('draco_capsule', Path(__file__).with_name('draco.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class CapsuleGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.identity = {'source': 'a', 'patches': [], 'compiler': 'b', 'abi': 'c',
                         'flags': ['-fPIC'], 'dependency_digests': [], 'recipe': 'd'}
        self.files = {name: b'bytes' for name in d.FIXED}
        self.files['prefix/include/draco/version.h'] = b'#define DRACO_VERSION "1.5.7"\n'

    def tearDown(self):
        self.temporary.cleanup()

    def capsule(self, mutate=None, extra=None):
        manifest = {'schema': 'uds-draco-local-capsule-v1', 'qualification': 'experimental-local-only',
                    'registry_qualified': False, 'sdk_accepted': False, 'input_key': d.key(self.identity),
                    'identity': self.identity, 'producer_receipt_sha256': '0' * 64,
                    'files': {n: {'bytes': len(v), 'sha256': d.sha(v), 'mode': 0o644}
                              for n, v in self.files.items()}}
        if mutate:
            mutate(manifest)
        entries = [(n, v, tarfile.REGTYPE) for n, v in self.files.items()]
        entries.append(('manifest.json', d.canonical(manifest), tarfile.REGTYPE))
        entries.extend(extra or [])
        archive = self.root / ('capsule-' + str(len(list(self.root.glob('capsule-*')))) + '.tar.gz')
        with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as stream:
            for name, data, kind in entries:
                info = tarfile.TarInfo(name)
                info.type, info.mode = kind, 0o644
                if kind == tarfile.REGTYPE:
                    info.size = len(data)
                else:
                    info.linkname = '../../escape'
                stream.addfile(info, io.BytesIO(data) if info.isfile() else None)
        return archive

    def verify(self, path, **overrides):
        return d.verify(path, overrides.get('digest', d.file_sha(path)),
                        overrides.get('key', d.key(self.identity)))

    def test_key_sensitive_to_actual_inputs_not_json_object_order(self):
        self.assertEqual(d.key(self.identity), d.key(dict(reversed(list(self.identity.items())))))
        for field in self.identity:
            changed = copy.deepcopy(self.identity)
            changed[field] = ['changed'] if isinstance(changed[field], list) else 'changed'
            self.assertNotEqual(d.key(self.identity), d.key(changed), field)

    def test_digest_key_and_file_tamper_rejected(self):
        path = self.capsule()
        with self.assertRaises(ValueError):
            self.verify(path, digest='1' * 64)
        with self.assertRaises(ValueError):
            self.verify(path, key='local-v1-' + '1' * 64)
        path = self.capsule(lambda m: m['files']['prefix/lib/libdraco.a'].update(sha256='1' * 64))
        with self.assertRaises(ValueError):
            self.verify(path)

    def test_privacy_allowlist_links_duplicates_and_path_escape(self):
        cases = [('prefix/secret.key', b'x', tarfile.REGTYPE),
                 ('prefix/logs/build.log', b'x', tarfile.REGTYPE),
                 ('prefix/include/draco/link.h', b'', tarfile.SYMTYPE),
                 ('prefix/include/draco/hard.h', b'', tarfile.LNKTYPE),
                 ('prefix/include/draco/../../escape.h', b'x', tarfile.REGTYPE),
                 ('/absolute', b'x', tarfile.REGTYPE),
                 ('prefix/lib/libdraco.a', b'x', tarfile.REGTYPE),
                 ('prefix/include/draco//ambiguous.h', b'x', tarfile.REGTYPE)]
        for entry in cases:
            with self.subTest(entry=entry[0]), self.assertRaises(ValueError):
                self.verify(self.capsule(extra=[entry]))

    def test_remote_qualification_cannot_be_claimed(self):
        for mutate in [lambda m: m.update(registry_qualified=True),
                       lambda m: m.update(sdk_accepted=True),
                       lambda m: m.update(qualification='trusted-main')]:
            with self.assertRaises(ValueError):
                self.verify(self.capsule(mutate))

    def test_restore_requires_new_non_symlink_prefix_and_rehashes(self):
        capsule = self.capsule()
        output = self.root / 'restored'
        manifest = d.restore(capsule, d.file_sha(capsule), d.key(self.identity), output)
        for name, entry in manifest['files'].items():
            self.assertEqual(d.file_sha(output / name), entry['sha256'])
        with self.assertRaises(ValueError):
            d.restore(capsule, d.file_sha(capsule), d.key(self.identity), output)
        (self.root / 'alias').symlink_to(output, target_is_directory=True)
        with self.assertRaises(ValueError):
            d.restore(capsule, d.file_sha(capsule), d.key(self.identity), self.root / 'alias/child')
        self.assertFalse((output / 'child').exists())

    def test_duplicate_json_keys_are_not_canonical_input(self):
        with self.assertRaises(ValueError):
            d.decode(b'{"source":"first","source":"second"}')

    def test_expansion_is_bounded_before_tar_extensions(self):
        path = self.root / 'bomb.tar.gz'
        with gzip.open(path, 'wb') as stream:
            stream.write(b'\0' * (d.MAX_EXPANDED + 2 * 1024**2 + 1))
        with self.assertRaises(ValueError):
            self.verify(path)

    def test_missing_payload_cannot_hide_behind_manifest(self):
        path = self.capsule(lambda m: m['files'].pop('prefix/lib/libdraco.a'))
        with self.assertRaises(ValueError):
            self.verify(path)


if __name__ == '__main__':
    unittest.main()
