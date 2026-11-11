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
spec = importlib.util.spec_from_file_location('kernel_spatial_profile', HERE / 'build.py')
BUILD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUILD)


class OfflineGuards(unittest.TestCase):
    def test_normalization_is_exact_context_only_and_fails_tampering(self):
        entry = BUILD.LOCK['patches']['libspatialite']
        norm = entry['normalization']
        data = b'--- old\n+++ new\n' + norm['old_context'].encode() + b'+actual addition\n'
        import hashlib
        expected = data.replace(norm['old_context'].encode(), norm['new_context'].encode())
        custom = entry | {'normalization': norm | {'sha256':hashlib.sha256(expected).hexdigest(), 'bytes':len(expected)}}
        self.assertEqual(BUILD.normalized_patch(data, custom), expected)
        for bad in (data + norm['old_context'].encode(), data.replace(b' | dvp',b' | foreign'), data+b'extra'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): BUILD.normalized_patch(bad, custom)
        self.assertEqual(BUILD.normalized_patch(b'untouched', {'normalization':{}}), b'untouched')

    def test_actual_zlib_header_dependencies_reject_host_or_missing_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prefix=root/'verified';prefix.mkdir()
            for name in ('zlib.h','zconf.h'): (prefix/name).write_bytes(name.encode())
            text='object.o: '+str(prefix/'zlib.h')+' '+str(prefix/'zconf.h')+'\n'
            self.assertEqual(len(BUILD.audit_zlib_headers(text,prefix)),2)
            for bad in (text.replace(str(prefix/'zconf.h'),'/usr/include/zconf.h'), text.replace(str(prefix/'zconf.h'),'')):
                with self.assertRaises(ValueError): BUILD.audit_zlib_headers(bad,prefix)

    def test_static_archive_guard_rejects_nested_text_and_truncated_members(self):
        def archive(data):
            name=b'object.o/'.ljust(16)
            header=name+b'0'.ljust(12)+b'0'.ljust(6)+b'0'.ljust(6)+b'100644'.ljust(8)+str(len(data)).encode().ljust(10)+b'`\n'
            return b'!<arch>\n'+header+data+(b'\n' if len(data)%2 else b'')
        elf=b'\x7fELF\x02\x01'+b'\0'*10+b'\x01\x00'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'provider.a';path.write_bytes(archive(elf))
            self.assertEqual(BUILD.archive_objects(path),1)
            for bad in (archive(b'!<arch>\n'),archive(b'not a real object'),archive(elf)[:-1],b'!<thin>\n'):
                path.write_bytes(bad)
                with self.assertRaises(ValueError): BUILD.archive_objects(path)

    def test_new_output_must_be_separate_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';cache.mkdir()
            for out in (cache,cache/'out',root):
                with self.assertRaises(ValueError): BUILD.paths(out,cache)
            self.assertEqual(BUILD.paths(root/'new',cache),(root/'new',cache))

    def test_receipt_is_bound_before_using_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'complete.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'producer recipe differs'): BUILD.dependency(root,'proj')

    def test_normative_producer_contract_allows_metadata_paths_not_wrong_source(self):
        import copy
        producer=BUILD.MODULES['proj']
        receipt={'recipe':producer.recipe(),'source_revision':BUILD.REVISION,
            'profile':'historical-proj-native','version':'4.9.1','archive':producer.ARCHIVE,
            'license':producer.LICENSE,'strict_pic':True,'source_patches':[],
            'known_coordinates_forward_inverse':True,'production_path':'/another/owned/output'}
        BUILD.provider_contract(json.loads(json.dumps(receipt,indent=4)),'proj')
        for key,value in [('source_revision','0'*40),('version','9.9'),('archive',{}),('recipe',{}),('strict_pic',False),('source_patches',['foreign'])]:
            wrong=copy.deepcopy(receipt);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): BUILD.provider_contract(wrong,'proj')

    def test_portable_receipt_bytes_and_actual_source_library_tampering(self):
        producer=BUILD.MODULES['proj']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'source').mkdir();(root/'source/src.c').write_bytes(b'source')
            (root/'install/lib').mkdir(parents=True);library=root/'install/lib/libproj.a';library.write_bytes(b'fixture-library')
            receipt={'recipe':producer.recipe(),'source_revision':BUILD.REVISION,
                'profile':'historical-proj-native','version':'4.9.1','archive':producer.ARCHIVE,
                'license':producer.LICENSE,'strict_pic':True,'source_patches':[],
                'known_coordinates_forward_inverse':True,'source_inventory':producer.source_inventory(root/'source'),
                'installed':BUILD.native.inventory(root/'install'),'runtime_closure':{},'tools':{}}
            path=root/'complete.json';path.write_text(json.dumps(receipt))
            # No executable runs in this cache-integrity fixture. Runtime validation
            # itself is isolated here; real producer inventories are checked separately.
            with patch.object(BUILD.las,'verify_runtime'):
                first=BUILD.dependency(root,'proj')['input_receipt_sha256']
                path.write_text(json.dumps(receipt,indent=4)+'\n')
                second=BUILD.dependency(root,'proj')['input_receipt_sha256']
                self.assertNotEqual(first,second)
                (root/'source/src.c').write_bytes(b'tampered')
                with self.assertRaises(ValueError): BUILD.dependency(root,'proj')
                (root/'source/src.c').write_bytes(b'source');library.write_bytes(b'tampered')
                with self.assertRaises(ValueError): BUILD.dependency(root,'proj')

    def test_other_producer_scope_and_source_contracts_reject_wrong_identity(self):
        for name in ('geos','sqlcipher','zlib'):
            with self.subTest(name=name),self.assertRaises(ValueError): BUILD.provider_contract({'recipe':{}},name)
        self.assertFalse(any('receipt_sha256' in entry for entry in BUILD.LOCK['dependencies'].values()))

    def test_offline_acquisition_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(BUILD.native.urllib.request,'urlopen',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError,'offline'):
                BUILD.native.acquire(Path(tmp),BUILD.LOCK['archives']['libspatialite'],False)

    def test_actual_translation_units_and_no_stub_or_gc_selection(self):
        self.assertTrue({'db/SpatiaLiteDB.cpp','db/Database.cpp','db/Cursor.cpp','db/Statement.cpp','thread/impl/ThreadImpl_libpthread.cpp'}.issubset(BUILD.SOURCES))
        text=(HERE/'build.py').read_text()
        self.assertNotIn('--gc-sections',text)
        self.assertNotIn('-ffunction-sections',text)
        self.assertIn('kernel_inventory(source) != kernel',text)

    def test_recipe_binds_directly_executed_directory_helper(self):
        self.assertEqual(BUILD.recipe()['../native-geos/run-in.py'],BUILD.native.digest(BUILD.geos.HERE/'run-in.py'))


@unittest.skipUnless(os.environ.get('TAKX_KERNEL_SPATIAL_DB_PROOF'), 'opt-in real joined proof required')
class ActualJoinedProof(unittest.TestCase):
    def test_receipt_bound_actual_kernel_consumer_with_new_owned_database(self):
        root=Path(os.environ['TAKX_KERNEL_SPATIAL_DB_PROOF']).resolve()
        receipt=json.loads((root/'complete.json').read_text())
        self.assertEqual(receipt['recipe'],BUILD.recipe())
        self.assertEqual(receipt['lock'],BUILD.LOCK)
        self.assertTrue(receipt['real_kernel_spatial_database_controls'])
        self.assertTrue(receipt['strict_pic'])
        for name,record in receipt['outputs'].items():
            self.assertEqual(BUILD.native.digest(root/name),record['sha256'])
            self.assertEqual((root/name).stat().st_size,record['bytes'])
        for name,record in receipt['selected_archives'].items():
            self.assertEqual(BUILD.native.digest(Path(name)),record['sha256'])
        for name,path in receipt['dependency_roots'].items(): BUILD.dependency(Path(path),name)
        for name,inventory in receipt['installed'].items():
            self.assertEqual(BUILD.native.inventory(root/(name+'-install')),inventory)
        BUILD.las.verify_runtime(receipt['runtime_closure'])
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            env=BUILD.geos.environment(receipt['tools']['gcc']['path'],receipt['tools']['g++']['path'])
            env.update(OPENSSL_CONF='/dev/null',OPENSSL_MODULES=str(directory/'absent-provider'))
            text=BUILD.native.run([str(root/'kernel-spatial-consumer'),str(directory/'owned.sqlite')],directory,'real-replay',timeout=30,capture=True,env=env).decode()
            self.assertIn('real_kernel_spatial_database_geometry_transform_typed_transaction_reopen=PASS\n',text)
        for field in ('modern_db2_encrypted_api_acceptance','full_sdk_acceptance','jni_acceptance','takx_acceptance','target_abi_acceptance','security_acceptance'):
            self.assertFalse(receipt[field])


if __name__ == '__main__': unittest.main()
