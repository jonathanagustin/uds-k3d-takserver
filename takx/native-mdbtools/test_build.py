# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
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
spec = importlib.util.spec_from_file_location('mdb_profile', HERE / 'build.py')
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
    def test_lock_binds_archive_patch_license_fixture_and_tools(self):
        lock = json.loads((HERE / 'inputs.lock.json').read_text()); B.validate_lock(lock)
        for key in ['archives','source_patch','licenses','fixture','tools']:
            altered = json.loads(json.dumps(lock)); altered[key] = {}
            with self.subTest(key=key), self.assertRaises(ValueError): B.validate_lock(altered)
    def test_consumer_explicit_posix_locale_contract(self):
        source = (HERE / 'build.py').read_text()
        self.assertIn("[cc, '-std=c11', '-D_XOPEN_SOURCE=700', '-O1'", source)
        self.assertNotIn('-D_GNU_SOURCE', source)
    def test_cache_is_offline_and_checksum_checked(self):
        with patch.object(B.native.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            for entry in [B.ARCHIVE, B.FIXTURE]:
                with self.assertRaisesRegex(ValueError,'offline'): B.native.acquire(self.root,entry,False)
                (self.root / entry['sha256']).write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError,'checksum'): B.native.acquire(self.root,entry,False)
    def test_archive_links_traversal_foreign_root_and_expansion_rejected(self):
        for name, kind in [('mdbtools-1.0.0/../../escape',tarfile.REGTYPE),('mdbtools-1.0.0/link',tarfile.SYMTYPE),('foreign/file',tarfile.REGTYPE),('mdbtools-1.0.0/file',tarfile.REGTYPE)]:
            archive=self.root/'bad.tar'
            with tarfile.open(archive,'w') as t:
                m=tarfile.TarInfo(name);m.type=kind;m.size=4;t.addfile(m,io.BytesIO(b'data'))
            with self.assertRaises(ValueError): B.las.unpack(archive,self.root/'out','mdbtools-1.0.0',{'members':1,'regular_files':1,'expanded_bytes':3})
    def test_patch_images_bind_added_and_existing_files(self):
        existing=self.root/'existing';existing.write_bytes(b'before')
        images={'existing':{'before':B.native.digest(existing),'after':'0'*64},'new':{'before':None,'after':'0'*64}}
        with patch.dict(B.PATCH,{'files':images}):
            B.check_patch_images(self.root,'before')
            with self.assertRaises(ValueError): B.check_patch_images(self.root,'after')
            (self.root/'new').write_bytes(b'injected')
            with self.assertRaises(ValueError): B.check_patch_images(self.root,'before')
    def test_paths_must_be_new_external_and_nonoverlapping(self):
        cache=self.root/'cache';cache.mkdir()
        for output in [cache,cache/'out',self.root]:
            with self.assertRaises(ValueError): B.validate_paths(output,cache)
        link=self.root/'link';link.symlink_to(cache)
        with self.assertRaises(ValueError): B.validate_paths(self.root/'new',link)
    def test_environment_removes_tool_make_compiler_injection(self):
        injected={'CFLAGS':'-DNDEBUG','LDFLAGS':'-lmdb','CPATH':'/foreign','LD_PRELOAD':'/foreign','MAKEFLAGS':'-j90','CONFIG_SITE':'/foreign','MDBTOOLS_LIB':'/foreign','MDBPATH':'/foreign','MDBICONV':'CP1251','MDBOPTS':'use_index','MDB_JET3_CHARSET':'CP1251','BASH_ENV':'/foreign','AR':'/foreign'}
        with patch.dict(os.environ,injected): env=B.environment('/trusted/gcc')
        for name in set(injected)-{'CFLAGS','CONFIG_SITE'}: self.assertNotIn(name,env)
        self.assertEqual(env['CFLAGS'],'-O2 -fPIC');self.assertEqual(env['CONFIG_SITE'],'/dev/null')
    def test_source_inventory_and_outputs_reject_changes_and_symlinks(self):
        f=self.root/'original';f.write_bytes(b'original');expected=B.source_inventory(self.root)
        f.write_bytes(b'changed')
        with self.assertRaises(ValueError): B.check_sources(self.root,expected)
        for name in ['MdbControls.c','consumer','libmdb-pic-check.so']:(self.root/name).write_bytes(b'output')
        before=B.outputs(self.root);(self.root/'consumer').write_bytes(b'changed');self.assertNotEqual(before,B.outputs(self.root))
        (self.root/'consumer').unlink();(self.root/'consumer').symlink_to(f)
        with self.assertRaises(ValueError): B.outputs(self.root)
@unittest.skipUnless(os.environ.get('TAKX_NATIVE_MDBTOOLS_PROOF'),'explicit fresh MDBTools proof required')
class ActualProof(unittest.TestCase):
    def test_receipt_sources_artifacts_tools_runtime_and_replayed_rows(self):
        root=Path(os.environ['TAKX_NATIVE_MDBTOOLS_PROOF']).resolve();r=json.loads((root/'complete.json').read_text())
        self.assertEqual(r['recipe'],B.recipe());self.assertEqual(r['outputs'],B.outputs(root))
        self.assertEqual(r['installed'],B.native.inventory(root/'install'));B.check_sources(root/'source',r['source_inventory'])
        B.las.verify_runtime(r['runtime_closure'])
        for tool in r['tools'].values():self.assertEqual(tool['sha256'],B.native.digest(Path(tool['path'])))
        fixture=Path(os.environ['TAKX_NATIVE_MDBTOOLS_FIXTURE']);B.native.verified(fixture,B.FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            result=B.native.run([str(root/'consumer'),str(fixture),str(Path(directory)/'missing.mdb')],Path(directory),'replay',timeout=10,capture=True,env=B.environment(r['tools']['cc']['path'])).decode()
        self.assertIn('customers=91\nalfki=Maria Anders\n',result)
        for key in ['ole_runtime_acceptance','kernel_provider_acceptance','kernel_sdk_acceptance','jni_acceptance','takx_acceptance','security_acceptance','target_image_abi_acceptance']:self.assertFalse(r[key])
if __name__=='__main__':unittest.main()
