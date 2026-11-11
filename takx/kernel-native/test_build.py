# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guards: no downloads, compiler, CMake, JVM or native loading by default."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('kernel_native_profile',HERE/'build.py');B=importlib.util.module_from_spec(spec);spec.loader.exec_module(B)
class Guards(unittest.TestCase):
    def test_exact_source_version_counts_patches_and_history(self):
        lock=B.p.load(HERE/'inputs.lock.json');B.validate_lock(lock)
        self.assertEqual(lock['source_counts'],{'core':483,'jni':159,'cesium':173});self.assertEqual(lock['native_file_count'],1396)
        for key in ['revision','kernel_version','patches','core_sqlite_exports','jni_patch_finalized']:
            bad=json.loads(json.dumps(lock));bad[key]={}
            with self.subTest(key=key),self.assertRaises(ValueError):B.validate_lock(bad)
    def test_source_path_and_bytes_checks(self):
        for name in ['../escape','/absolute','valid/../../escape','bad\\path']:
            with self.assertRaises(ValueError):B.sources.relative(name)
        entry={'bytes':4,'sha256':hashlib.sha256(b'data').hexdigest()};B.sources.checked(b'data',entry)
        with self.assertRaises(ValueError):B.sources.checked(b'fake',entry)
    def test_unsafe_output_overlap_existing_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            for out in [source,source/'out',root]:
                with self.assertRaises(ValueError):B.disjoint(out,[source])
            link=root/'alias';link.symlink_to(source)
            with self.assertRaises(ValueError):B.external(link)
    def test_environment_blocks_compiler_loader_java_injection(self):
        injected={'LD_PRELOAD':'/foreign','CPATH':'/foreign','CMAKE_PREFIX_PATH':'/foreign','JAVA_TOOL_OPTIONS':'-Xmx9g','JDK_JAVAC_OPTIONS':'-processor foreign','PYTHONPATH':'/foreign','MAKEFLAGS':'-j88','GDAL_DATA':'/foreign','BASH_ENV':'/foreign'}
        with patch.dict(os.environ,injected):env=B.environment(Path('/jdk'),'cc','cxx',Path('/out'))
        for name in injected:self.assertNotIn(name,env)
        self.assertEqual(env['CMAKE_BUILD_PARALLEL_LEVEL'],'1')
        self.assertEqual(env['OPENSSL_CONF'],'/dev/null');self.assertEqual(env['OPENSSL_MODULES'],'/out/absent-openssl-modules')
    def test_exact_provider_inventory_and_no_unknown_recipe_variant(self):
        with self.assertRaises(ValueError):B.p.verify_all({})
        fake=type('Producer',(),{'recipe':lambda self:{'build.py':'real'},'HERE':HERE})()
        with patch.object(B.p,'module',return_value=fake):
            with self.assertRaisesRegex(ValueError,'unreviewed consumed'):B.p.recipe_check('sqlcipher',{'recipe':{'build.py':'invented'}})
    def test_actual_history_is_source_variants_not_receipt_goldens(self):
        history=B.p.load(HERE/'producer-history.lock.json')
        for family,entry in history.items():
            self.assertFalse(entry['arbitrary_frozen_recipes_accepted'])
            for item in entry['variants'].values():self.assertEqual(B.p.digest(HERE/item['snapshot']),item['sha256'])
    def test_exact_class_inventory_rejects_stale_shadow(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Real.class').write_bytes(b'actual')
            expected={'Real.class':B.p.digest(root/'Real.class')};B.p.check_files(root,expected)
            (root/'Shadow.class').write_bytes(b'stale')
            with self.assertRaises(ValueError):B.p.check_files(root,expected)
    def test_all_ancestry_inputs_participate_in_disjointness(self):
        paths={'cesium':{'root':'/a','dependency_root':'/b','stopped_inventory':'/c/file','acquisition_root':'/d'}}
        self.assertEqual(set(map(str,B.p.declared_paths(paths))),{'/a','/b','/c/file','/d'})
    def test_actual_archive_dynamic_symbol_intersections(self):
        exports,imports,names=B.audit.symbols('Num: Value Size Type Bind Vis Ndx Name\n1: 00012 32 FUNC GLOBAL DEFAULT 12 sqlite3_config\n2: 00000 0 FUNC GLOBAL DEFAULT UND sqlite3_errstr\n')
        self.assertEqual(exports,{'sqlite3_config'});self.assertEqual(imports,{'sqlite3_errstr'});self.assertEqual(names,exports|imports)
        defined,_,_=B.audit.symbols('3: 00012 8 OBJECT UNIQUE DEFAULT 12 actual_unique_object\n4: 00020 8 OBJECT WEAK DEFAULT 12 actual_weak_object\n')
        self.assertEqual(defined,{'actual_unique_object','actual_weak_object'})
    def test_mapped_policy_requires_exact_bound_path_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);actual=root/'actual';actual.write_bytes(b'bound object');sha=B.p.digest(actual)
            allowed={str(actual):sha};self.assertEqual(B.audit.check_mapped_provider(actual,sha,allowed,root),actual)
            extra=root/'unlisted';extra.write_bytes(b'bound object')
            with self.assertRaises(ValueError):B.audit.check_mapped_provider(extra,sha,allowed,root)
            actual.write_bytes(b'changed')
            with self.assertRaises(ValueError):B.audit.check_mapped_provider(actual,sha,allowed,root)
    def test_all_strict_jni_warning_families(self):
        for text in ['WARNING in native method: bad','WARNING: JNI local refs','FATAL ERROR in native method','FATAL ERROR: native defect']:
            self.assertTrue(B.audit.strict_jni_diagnostics(text))
        self.assertFalse(B.audit.strict_jni_diagnostics('SLF4J: default NOP warning'))
    def test_operative_code_has_no_private_paths_or_source_reductions(self):
        for name in ['build.py','sources.py','providers.py','audit.py','toolchain.py','CMakeLists.txt']:
            self.assertNotIn('/workspace/',(HERE/name).read_text())
        parent=(HERE/'CMakeLists.txt').read_text();self.assertIn('Cesium3DTilesSelection',parent);self.assertIn('src/main/cpp',parent);self.assertIn('src/main/jni',parent)
        self.assertNotIn('--exclude-libs,libsqlite3.a',parent);self.assertNotIn('-Bsymbolic',parent)
class ToolchainBounds(unittest.TestCase):
    def test_backend_fingerprints_reject_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'tool';path.write_bytes(b'actual tool')
            record={'bound_files':{str(path):B.p.digest(path)}};B.toolchain.verify(record)
            path.write_bytes(b'changed tool')
            with self.assertRaises(ValueError):B.toolchain.verify(record)
    def test_wrapper_is_not_native_tool_elf(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'launcher';path.write_bytes(b'#!/usr/bin/python3\n')
            with self.assertRaises(ValueError):B.toolchain.elf(path)
class LiveBounds(unittest.TestCase):
    def test_closed_stdout_still_has_live_disk_bound(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            code='import os,time;from pathlib import Path;os.close(1);os.close(2);Path('+repr(str(root/'payload'))+').write_bytes(b"x"*4096);time.sleep(8)'
            started=time.monotonic()
            with self.assertRaisesRegex(ValueError,'output quota'):
                B.runner.execute([sys.executable,'-c',code],root,'closed',5,dict(os.environ),disk_limit=1024)
            self.assertLess(time.monotonic()-started,3)
    def test_stalled_source_reader_is_bounded_by_owned_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fake=root/'stalled-git'
            fake.write_text('#!'+sys.executable+'\nimport time\nprint("retained source diagnostic",flush=True)\ntime.sleep(5)\n');fake.chmod(0o700)
            def run(argv,label,timeout):return B.runner.execute(list(map(str,argv)),root,label,.15,dict(os.environ),capture=True)
            entry={'bytes':1,'sha256':'0'*64,'git_blob':'0'*40}
            with self.assertRaisesRegex(ValueError,'deadline'):
                list(B.sources.git_blobs(root,{'file':entry},run,fake))
            self.assertIn('retained source diagnostic',(root/'source-0.log').read_text())
    def test_log_and_process_group_lifetime_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'log quota'):
                B.runner.execute([sys.executable,'-c','print("x"*2048)'],root,'log',5,dict(os.environ),log_limit=100)
            with self.assertRaisesRegex(ValueError,'deadline'):
                B.runner.execute([sys.executable,'-c','import time;print("diagnostic",flush=True);time.sleep(4)'],root,'deadline',.15,dict(os.environ))
            self.assertIn('diagnostic',(root/'deadline.log').read_text())
    def test_recipe_binds_runner_and_excludes_documentation_guards(self):
        recipe=B.recipe();self.assertIn('../native-commoncommo/runner.py',recipe)
        self.assertNotIn('README.md',recipe);self.assertNotIn('test_build.py',recipe)
if __name__=='__main__':unittest.main()
