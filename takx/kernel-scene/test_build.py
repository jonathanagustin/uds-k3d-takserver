# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('kernel_scene_build', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class Guards(unittest.TestCase):
    def test_existing_proof_and_nested_output_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            proof = root / 'proof'
            proof.mkdir()
            for output in (proof, proof / 'new', root):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    BUILD.validate_output(output, [proof])
            self.assertEqual(BUILD.validate_output(root / 'fresh', [proof]), root / 'fresh')
            self.assertFalse((proof / 'new').exists())

    def test_source_symlink_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'file').write_text('data')
            (root / 'alias').symlink_to(root / 'file')
            with self.assertRaises(ValueError):
                BUILD.inventory(root)

    def test_archive_traversal_links_and_duplicate_members_are_refused(self):
        for names, link in [(['../outside'], False), (['same', 'same'], False), (['link'], True)]:
            with self.subTest(names=names), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                archive = root / 'bad.tar.gz'
                with tarfile.open(archive, 'w:gz') as tar:
                    for name in names:
                        member = tarfile.TarInfo(name)
                        if link:
                            member.type = tarfile.SYMTYPE
                            member.linkname = '/outside'
                            tar.addfile(member)
                        else:
                            member.size = 1
                            tar.addfile(member, io.BytesIO(b'x'))
                entry = {'bytes': archive.stat().st_size, 'sha256': BUILD.native.digest(archive),
                         'members': len(names), 'regular_files': 0 if link else len(names),
                         'expanded_bytes': 0 if link else len(names)}
                with self.assertRaises(ValueError):
                    BUILD.unpack(archive, root / 'source', entry)
                self.assertFalse((root / 'source').exists())

    def test_archive_corruption_precedes_materialization(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / 'bad'
            archive.write_bytes(b'wrong')
            with self.assertRaises(ValueError):
                BUILD.unpack(archive, root / 'source', {'bytes': 5, 'sha256': '0' * 64})
            self.assertFalse((root / 'source').exists())

    def test_large_input_exception_cannot_expand_other_inputs(self):
        with self.assertRaises(ValueError):
            BUILD.validate_kernel_input('unrelated.h', b'x'*(2*1024**2+1))
        with self.assertRaises(ValueError):
            BUILD.validate_kernel_input('formats/wmm/EGM9615.h', b'x'*8416818)
        BUILD.validate_kernel_input('ordinary.h', b'ordinary bytes')

    def test_producer_schema_requires_all_material_facts_and_honest_freshness(self):
        from copy import deepcopy
        fact='0'*64
        data={'schema_version':1,'contract':BUILD.producer.CONTRACT,'fresh_build':False,
              'producer_lineage':{'fresh_build':False},'producer_recipe':{'build.py':fact},
              'kernel_scene_acceptance':False,'source_postimages_sha256':fact,
              'source_postimages':{'file':{'sha256':fact,'bytes':1}},
              'gdal_installed':[{'path':'lib/libgdal.a','sha256':fact,'bytes':1}],
              'objects_after':{'file.o':{'sha256':fact,'bytes':1}},
              'bindings':{'files':{name:fact for name in BUILD.producer.FILES},
                          'tools':{'/fixture/compiler':fact},'normalizer_sha256':fact,'gdal_makefile_sha256':fact}}
        self.assertFalse(BUILD.producer.normalize(data)['fresh_build'])
        for field in ('source_postimages','objects_after','gdal_installed','producer_lineage'):
            value=deepcopy(data);value.pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError): BUILD.producer.normalize(value)
        value=deepcopy(data);value['fresh_build']=1
        with self.assertRaises(ValueError): BUILD.producer.normalize(value)
        value=deepcopy(data);value['bindings']['files'].pop('minizip-positive-controls.log')
        with self.assertRaises(ValueError): BUILD.producer.normalize(value)
        value=deepcopy(data);value['bindings']['tools']['/fixture/compiler']='changed'
        with self.assertRaises(ValueError): BUILD.producer.normalize(value)

    def test_profile_and_patches_are_frozen(self):
        lock = json.loads((HERE / 'inputs.lock.json').read_text())
        self.assertEqual(lock['configure'], BUILD.CONFIGURE)
        self.assertEqual(lock['kernel_tus'], BUILD.KERNEL_TUS)
        for name, entry in lock['patches'].items():
            self.assertEqual(BUILD.native.digest(HERE / 'patches' / name), entry['sha256'])
        self.assertEqual(len(lock['libkml_patch_postimages']), 24)


if __name__ == '__main__':
    unittest.main()
