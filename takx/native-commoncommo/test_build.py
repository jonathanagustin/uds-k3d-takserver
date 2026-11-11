# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('commoncommo_build',HERE/'build.py')
BUILD=importlib.util.module_from_spec(spec);spec.loader.exec_module(BUILD)
class Guards(unittest.TestCase):
    def test_full_crypto_symbol_union_not_only_prefixes(self):
        row=lambda name,index='13':f'  1: 0000 16 FUNC GLOBAL DEFAULT {index} {name}\n'
        self.assertEqual(BUILD.exports(row('JNI_OnLoad')+row('Java_com_atakmap_commoncommo_Commo_createNative'),{'unprefixed_real_crypto'}),['JNI_OnLoad','Java_com_atakmap_commoncommo_Commo_createNative'])
        for text in [row('JNI_OnLoad')+row('unprefixed_real_crypto'),row('JNI_OnLoad')+row('unprefixed_real_crypto','UND'),row('JNI_OnLoad')+row('unexpected'),row('Java_com_atakmap_commoncommo_Commo_createNative')]:
            with self.assertRaises(ValueError):BUILD.exports(text,{'unprefixed_real_crypto'})
    def test_sources_reject_missing_tampered_and_links(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'source';p.write_bytes(b'original');r=BUILD.record(root);BUILD.check_record(root,r)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):BUILD.check_record(root,r)
            p.unlink();p.symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):BUILD.check_record(root,r)
    def test_exact_sources_and_archive_budget(self):
        lock=BUILD.LOCK
        self.assertEqual(lock['revision'],'9f6893dd657feacc35ec5de03dad721c2e44170e')
        self.assertEqual({x['name'] for x in lock['archives']},{'curl','nghttp2','ngtcp2','protobuf','libmicrohttpd'})
        self.assertLess(sum(x['bytes'] for x in lock['archives']),32*1024**2)
        self.assertLess(sum(x['expanded_bytes'] for x in lock['archives']),512*1024**2)
    def test_signed_tools_are_required_not_shims(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises((ValueError,FileNotFoundError)):BUILD.verify_tools(Path(t),Path(t))
    def test_absent_provider_proof_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises((ValueError,FileNotFoundError)):BUILD.verify_providers(Path(t),Path(t),Path(t))

class RunnerGuards(unittest.TestCase):
    def test_real_timeout_retains_child_diagnostic(self):
        import os,sys
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            with self.assertRaisesRegex(ValueError,'deadline'):
                BUILD.runner.execute([sys.executable,'-c','import time;print("retained diagnostic",flush=True);time.sleep(5)'],p,'timed',.15,dict(os.environ))
            self.assertIn(b'retained diagnostic',(p/'timed.log').read_bytes())
    def test_real_live_disk_and_log_quotas(self):
        import os,sys
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            code='from pathlib import Path;import time;Path('+repr(str(p/'payload'))+').write_bytes(b"x"*2048);time.sleep(5)'
            with self.assertRaisesRegex(ValueError,'output quota'):
                BUILD.runner.execute([sys.executable,'-c',code],p,'disk',5,dict(os.environ),disk_limit=1024)
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'log quota'):
                BUILD.runner.execute([sys.executable,'-c','print("x"*2000)'],Path(t),'log',5,dict(os.environ),log_limit=100)
    def test_real_system_cpp_runtime_allowed_not_crypto(self):
        candidates=sorted(Path('/usr/lib').glob('*-linux-gnu/libstdc++.so.6'))
        self.assertTrue(candidates,'system C++ runtime prerequisite')
        path=candidates[0]
        self.assertTrue(path.is_file())
        result=BUILD.runtime_closure('libstdc++.so.6 => '+str(path)+' (0x1234)\n')
        self.assertIn(str(path.resolve()),result)
        for text in ['libcrypto.so.3 => /usr/lib/x86_64-linux-gnu/libcrypto.so.3 (0x1234)','libstdc++.so.6 => /tmp/libstdc++.so.6 (0x1234)','libstdc++.so.6 => not found','']:
            with self.assertRaises(ValueError):BUILD.runtime_closure(text)
    def test_original_archive_mtime_preserved(self):
        import tarfile,io
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'source').mkdir();(p/'source/Makefile.in').write_bytes(b'generated')
            tar=p/'source.tar'
            with tarfile.open(tar,'w') as tf:
                e=tarfile.TarInfo('source/Makefile.in');e.size=9;e.mtime=1716099959;tf.addfile(e,io.BytesIO(b'generated'))
            BUILD.archive_mtimes(tar,p,{})
            self.assertEqual((p/'source/Makefile.in').stat().st_mtime,1716099959)

class AntAndClosedStreamGuards(unittest.TestCase):
    def test_ant_configs_refuse_without_changing_home(self):
        with tempfile.TemporaryDirectory() as t:
            home=Path(t);BUILD.ant_config_guard(home)
            (home/'.ant').mkdir();path=home/'.ant/ant.conf';path.write_text('JAVACMD=foreign')
            with self.assertRaises(ValueError):BUILD.ant_config_guard(home)
            path.unlink();(home/'.antrc').symlink_to(home/'missing')
            with self.assertRaises(ValueError):BUILD.ant_config_guard(home)
    def test_closed_stream_writer_still_has_live_disk_quota(self):
        import os,sys,time
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            code='import os,time;from pathlib import Path;os.close(1);os.close(2);Path('+repr(str(p/'payload'))+').write_bytes(b"x"*2048);time.sleep(5)'
            started=time.monotonic()
            with self.assertRaisesRegex(ValueError,'output quota'):
                BUILD.runner.execute([sys.executable,'-c',code],p,'closed-stream',4,dict(os.environ),disk_limit=1024)
            self.assertLess(time.monotonic()-started,3)

class ConcurrentFilesystemGuards(unittest.TestCase):
    def test_quota_scan_tolerates_only_disappeared_file(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'stable').write_bytes(b'a'*111);(root/'transient').write_bytes(b'x'*999)
            original=Path.lstat
            def missing(path,*args,**kwargs):
                if path.name=='transient':raise FileNotFoundError('installer removed entry')
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',missing):self.assertEqual(BUILD.runner.disk_bytes(root),111)
            def denied(path,*args,**kwargs):
                if path.name=='transient':raise PermissionError('unexpected permission failure')
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',denied),self.assertRaises(PermissionError):BUILD.runner.disk_bytes(root)
            (root/'link').symlink_to('/etc/hosts')
            self.assertEqual(BUILD.runner.disk_bytes(root),1110)

class JniPatchAndReuseGuards(unittest.TestCase):
    def test_jni_patch_rejects_wrong_source_before_running_patch(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'jni/native').mkdir(parents=True)
            for name in BUILD.LOCK['jni_patch']['files']:(root/name).write_bytes(b'wrong source')
            invoked=[]
            with self.assertRaisesRegex(ValueError,'preimage'):
                BUILD.apply_jni_patch(root,lambda *args,**kwargs:invoked.append(args))
            self.assertEqual(invoked,[])
    def test_resume_cannot_overlap_original_stage(self):
        spec=importlib.util.spec_from_file_location('resume_guard',HERE/'resume.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);original=root/'original';original.mkdir()
            for output in (original,original/'new',root):
                with self.assertRaises(ValueError):module.separated(output,[original])
            self.assertEqual(module.separated(root/'new',[original]),root/'new')
    def test_stage_never_promotes_original_jni_and_requires_full_closure(self):
        spec=importlib.util.spec_from_file_location('stage_guard',HERE/'stage.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);r={'producer':module.PRODUCER,'stage_class':'local-observed-dependencies-core-from-stopped-commoncommo','original_root':str(root),'original_jni_accepted':True}
            with self.assertRaisesRegex(ValueError,'scope'):module.validate_record(r,root)
            r['original_jni_accepted']=False
            with self.assertRaisesRegex(ValueError,'closure'):module.validate_record(r,root)
            path=root/'manifest.json';path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'digest'):module.verify(root,path,'0'*64)
    def test_stage_manifest_read_is_bounded(self):
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('bounded_stage',HERE/'stage.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'manifest';path.write_bytes(b'x'*9)
            with patch.object(module,'MAX_MANIFEST',8),self.assertRaisesRegex(ValueError,'bound'):module.load(path)

if __name__=='__main__':unittest.main()
