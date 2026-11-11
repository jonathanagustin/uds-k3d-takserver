# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import hashlib
import unittest
import zipfile
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('gles_guard',HERE/'build.py');B=importlib.util.module_from_spec(s);s.loader.exec_module(B)
class OfflineGuards(unittest.TestCase):
    def test_source_tool_header_license_lock_refuses_changes(self):
        d=json.loads((HERE/'inputs.lock.json').read_text());B.validate_lock(d)
        for key in ('source','meson','headers','license_notices','source_patches','bounds'):
            bad=dict(d);bad[key]={}
            with self.subTest(key=key),self.assertRaises(ValueError):B.validate_lock(bad)
    def test_missing_offline_source_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(B.native.urllib.request,'urlopen',side_effect=AssertionError('network')):
            d=json.loads((HERE/'inputs.lock.json').read_text())
            for key in ('source','meson'):
                with self.assertRaisesRegex(ValueError,'offline'):B.native.acquire(Path(tmp),d[key],False)
    def test_package_traversal_and_symlinks_rejected(self):
        for name,mode in [('../escape',0),('link',0o120777)]:
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);z=p/'bad.zip'
                with zipfile.ZipFile(z,'w') as archive:
                    entry=zipfile.ZipInfo(name);entry.external_attr=mode<<16;archive.writestr(entry,b'data')
                with self.assertRaises(ValueError):B.wheel_unpack(z,p/'out',{'members':1,'expanded_bytes':4})
    def test_exact_archive_owned_header_link_materializes_and_rejects_other_links(self):
        for target,content in [('src/',b'data'),('../escape',b'data'),('src/',b'evil')]:
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);archive=p/'source.tar';entry={'root':'root','members':2,'regular_files':1,'expanded_bytes':4}
                with tarfile.open(archive,'w') as t:
                    m=tarfile.TarInfo('root/uthash/src/header.h');m.size=4;t.addfile(m,io.BytesIO(content))
                    m=tarfile.TarInfo('root/uthash/include');m.type=tarfile.SYMTYPE;m.linkname=target;t.addfile(m)
                links={'root/uthash/include':{'target':'src/','source_subtree':'root/uthash/src/','files':{'header.h':{'bytes':4,'sha256':hashlib.sha256(b'data').hexdigest()}}}}
                if target=='src/' and content==b'data':
                    records=B.source_unpack(archive,p/'out',entry,links)
                    self.assertEqual((p/'out/root/uthash/include/header.h').read_bytes(),b'data')
                    self.assertEqual(len(records),2)
                else:
                    with self.assertRaises(ValueError):B.source_unpack(archive,p/'out',entry,links)

    def test_runtime_requires_actual_owned_and_mesa_providers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):B.providers('real_surfaceless_es3_clear_readback=true\n',Path(tmp))
            with self.assertRaises(ValueError):B.providers('providers_begin\n/foreign.so\nproviders_end\n',Path(tmp))
@unittest.skipUnless(os.environ.get('TAKX_NATIVE_GLES_PROOF'),'opt-in real GLES proof required')
class ActualProof(unittest.TestCase):
    def test_receipt_and_actual_fresh_surfaceless_render(self):
        root=Path(os.environ['TAKX_NATIVE_GLES_PROOF']).resolve();r=json.loads((root/'complete.json').read_text())
        self.assertEqual(r['recipe'],B.recipe());B.validate_lock(r['lock'])
        self.assertEqual(B.inventory(root/'source'),r['source_inventory']);self.assertEqual(B.inventory(root/'meson'),r['meson_inventory'])
        self.assertEqual(B.native.inventory(root/'install'),r['installed'])
        for path,sha in (r['tools']|r['host_inputs']).items():self.assertEqual(B.native.digest(Path(path)),sha)
        for path,data in r['runtime_providers'].items():self.assertEqual(B.native.digest(Path(path)),data['sha256'])
        self.assertEqual(B.native.digest(root/'surfaceless-es3'),r['probe']['sha256'])
        env=B.las.environment({'cc':{'path':'/usr/bin/gcc'},'cxx':{'path':'/usr/bin/gcc'}})
        for key in list(env):
            if key.startswith(('LD_','MESA_','EGL_','LIBGL_','GALLIUM_','__EGL_')):env.pop(key,None)
        env.update(r['runtime_env'])
        with tempfile.TemporaryDirectory() as tmp:
            text=B.native.run([str(root/'surfaceless-es3')],Path(tmp),'actual-replay',timeout=30,env=env,capture=True).decode()
        self.assertEqual(B.providers(text,root/'install'),r['runtime_providers'])
        self.assertEqual(text.splitlines().count('real_surfaceless_es3_clear_readback=true'),1)
        self.assertTrue(r['genuine_surfaceless_es3_clear_readback']);self.assertFalse(r['host_mesa_source_built_here'])
        for field in ('full_kernel_sdk_acceptance','renderer_integration_acceptance','takx_acceptance','target_abi_acceptance','security_acceptance'):self.assertFalse(r[field])

if __name__=='__main__':unittest.main()
