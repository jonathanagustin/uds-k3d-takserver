# Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('crypto_profile',HERE/'build.py');B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)
class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_lock_binds_actual_crypto_source_patch_license_and_tools(self):
        B.validate_lock(B.LOCK)
        for key in ['archive','patch','license','tools','modern_producer']:
            lock=json.loads(json.dumps(B.LOCK));lock[key]={}
            with self.subTest(key=key),self.assertRaises(ValueError):B.validate_lock(lock)
    def test_offline_cache_and_checksum(self):
        with patch.object(B.native.urllib.request,'urlopen',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError,'offline'):B.native.acquire(self.root,B.LOCK['archive'],False)
            (self.root/B.LOCK['archive']['sha256']).write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'checksum'):B.native.acquire(self.root,B.LOCK['archive'],False)
    def test_archive_escape_link_and_expansion_refused(self):
        for name,kind in [('openssl-openssl-3.0.14-quic1/../../escape',tarfile.REGTYPE),('openssl-openssl-3.0.14-quic1/link',tarfile.SYMTYPE),('foreign/file',tarfile.REGTYPE),('openssl-openssl-3.0.14-quic1/file',tarfile.REGTYPE)]:
            p=self.root/'input.tar'
            with tarfile.open(p,'w') as t:
                m=tarfile.TarInfo(name);m.type=kind;m.size=4;t.addfile(m,io.BytesIO(b'data'))
            with self.assertRaises(ValueError):B.las.unpack(p,self.root/'out','openssl-openssl-3.0.14-quic1',{'members':1,'regular_files':1,'expanded_bytes':3})
    def test_crypto_symbol_exports_and_imports_fail_closed(self):
        good='1: 000123 32 FUNC GLOBAL DEFAULT 12 q_aes\n'
        B.symbols(good,['q_aes'])
        for bad in ['2: 000123 32 FUNC GLOBAL DEFAULT 12 EVP_EncryptInit_ex\n','2: 000000 0 FUNC GLOBAL DEFAULT UND OPENSSL_init_crypto\n','2: 000123 32 FUNC GLOBAL DEFAULT 12 sqlite3_key\n','2: 000123 32 FUNC GLOBAL DEFAULT 12 accidental_export\n']:
            with self.assertRaises(ValueError):B.symbols(good+bad,['q_aes'])
    def test_reuse_requires_normative_producer_not_only_receipt_hash(self):
        (self.root/'complete.json').write_text(json.dumps({'recipe':{},'archives':{},'licenses':{}}))
        with self.assertRaisesRegex(ValueError,'producer/source identity'):B.reused(self.root)
    def test_paths_and_environment(self):
        cache=self.root/'cache';cache.mkdir()
        for output in [cache,cache/'nested',self.root]:
            with self.assertRaises(ValueError):B.sql.validate_paths(output,cache)
        tools={k:{'path':'/trusted/'+k} for k in ['cc','ar','ranlib','perl']}
        injected={'LD_PRELOAD':'/foreign','OPENSSL_CONF':'/foreign','OPENSSL_MODULES':'/foreign','CFLAGS':'-DNDEBUG','CPATH':'/foreign','MAKEFLAGS':'-j88','MAKEFILES':'/foreign','BASH_ENV':'/foreign','QUIC_CUSTOM':'/foreign'}
        with patch.dict(os.environ,injected):env=B.environment(tools,self.root)
        for key in set(injected)-{'OPENSSL_CONF','OPENSSL_MODULES','CFLAGS'}:self.assertNotIn(key,env)
        self.assertEqual(env['OPENSSL_CONF'],'/dev/null');self.assertEqual(env['OPENSSL_MODULES'],str(self.root/'absent-provider-modules'));self.assertEqual(env['CFLAGS'],'-O2 -fPIC')
@unittest.skipUnless(os.environ.get('TAKX_NATIVE_CRYPTO_PROOF'),'fresh crypto proof explicitly required')
class ActualProof(unittest.TestCase):
    def test_inventory_symbols_both_orders_and_real_encryption_replay(self):
        root=Path(os.environ['TAKX_NATIVE_CRYPTO_PROOF']).resolve();modern=Path(os.environ['TAKX_NATIVE_CRYPTO_MODERN']).resolve();r=json.loads((root/'complete.json').read_text())
        self.assertEqual(r['recipe'],B.recipe());self.assertEqual(r['lock'],B.LOCK)
        _,sha=B.reused(modern);self.assertEqual(r['modern_receipt_sha256'],sha)
        B.sql.check_sources(root/'source',r['source_inventory']);self.assertEqual(r['quictls_installed'],B.native.inventory(root/'quictls-install'))
        for name,item in r['outputs'].items():self.assertEqual(item['sha256'],B.native.digest(root/name));self.assertEqual(item['bytes'],(root/name).stat().st_size)
        for tool in list(r['tools'].values())+[r['patch_tool']]:self.assertEqual(tool['sha256'],B.native.digest(Path(tool['path'])))
        for paths in r['maps'].values():
            for name,sha in paths.items():self.assertEqual(sha,B.native.digest(Path(name)))
        env=B.environment(r['tools'],root)
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory)
            for order in ['qm','mq']:
                text=B.native.run([str(root/'load-orders'),order,str(root/'quictls-group.so'),str(root/'modern-group.so'),str(tmp/(order+'.db'))],tmp,order,timeout=30,capture=True,env=env).decode()
                self.assertIn('aes_both=PASS',text);self.assertIn('quictls_clienthello_callback=PASS',text);self.assertIn('encrypt_reopen_wrong_key=PASS',text)
            for group,expected in [('quictls',['q_version','q_aes','q_quic']),('modern',['m_version','m_aes','m_database'])]:
                text=B.native.run([r['tools']['readelf']['path'],'--dyn-syms','--wide',str(root/(group+'-group.so'))],tmp,group,timeout=10,capture=True,env=env).decode();B.symbols(text,expected)
        for key in ['full_quic_handshake','commoncommo_acceptance','kernel_sdk_acceptance','takx_acceptance']:self.assertFalse(r[key])
if __name__=='__main__':unittest.main()
