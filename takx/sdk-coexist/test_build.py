# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline admission/resource guards. No compiler, JVM or native library runs."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('sdk_coexist',HERE/'build.py')
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)


class JoinedGuards(unittest.TestCase):
    def test_environment_preserves_home_and_rejects_native_java_driver_injection(self):
        values={'HOME':'/original-home','CODEX_HOME':'/original-codex','LD_PRELOAD':'untrusted',
                'JAVA_TOOL_OPTIONS':'untrusted','_JAVA_OPTIONS':'untrusted','JDK_JAVA_OPTIONS':'untrusted',
                'GDAL_DRIVER_PATH':'untrusted','PROJ_LIB':'untrusted','CLASSPATH':'untrusted'}
        with patch.dict(os.environ,values,clear=True):
            env=B.environment()
            self.assertEqual(env['HOME'],values['HOME']);self.assertEqual(env['CODEX_HOME'],values['CODEX_HOME'])
            for key in values.keys()-{'HOME','CODEX_HOME'}:self.assertNotIn(key,env)
            self.assertEqual(env['OPENSSL_CONF'],'/dev/null')
            self.assertEqual(dict(os.environ),values)

    def test_output_overlap_alias_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir()
            self.assertEqual(B.disjoint(root/'new',[source]),root/'new')
            for output in (source,source/'new',root):
                with self.subTest(output=output),self.assertRaises(ValueError):B.disjoint(output,[source])
            alias=root/'alias';alias.symlink_to(source,target_is_directory=True)
            with self.assertRaises(ValueError):B.disjoint(alias/'new',[source])
            with self.assertRaises(ValueError):B.disjoint(root/'missing/../new',[source])

    def test_map_integrity_complete_records_and_shared_backend_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);good=root/'libcomponent.so';good.write_bytes(b'\x7fELFfixture')
            sha=B.digest(good);line='JOINED_ELF '+sha+' '+str(good)+'\n';expected={str(good):sha}
            self.assertEqual(B.mapped(line,expected),expected)
            cases=(('',expected),(line+line,expected),(line,{}),
                   (line.replace(sha,'0'*64),expected))
            for text,allowed in cases:
                with self.subTest(text=text),self.assertRaises(ValueError):B.mapped(text,allowed)
            for name,data in [('libcrypto.so.3',b'\x7fELFfixture'),('not-elf',b'not an ELF')]:
                path=root/name;path.write_bytes(data);digest=B.digest(path)
                with self.assertRaises(ValueError):B.mapped('JOINED_ELF '+digest+' '+str(path)+'\n',{str(path):digest})
            alias=root/'alias.so';alias.symlink_to(good)
            with self.assertRaises(ValueError):B.mapped('JOINED_ELF '+sha+' '+str(alias)+'\n',{str(alias):sha})

    def test_native_extraction_data_limit_is_separate_from_log_limit(self):
        code='''import importlib.util, pathlib, resource, sys
s=importlib.util.spec_from_file_location('joined',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.child_limits(3)
assert resource.getrlimit(resource.RLIMIT_CORE)==(0,0)
assert resource.getrlimit(resource.RLIMIT_FSIZE)==(m.FILE_CAP,m.FILE_CAP)
p=pathlib.Path(sys.argv[2]);p.write_bytes(b'x'*(m.LOG_CAP+4096))
assert p.stat().st_size==m.LOG_CAP+4096
'''
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run([sys.executable,'-B','-c',code,str(HERE/'build.py'),str(Path(temporary)/'owned-resource')],
                           check=True,capture_output=True,timeout=5)

    def test_child_log_excess_fails_without_unbounded_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=[]
            with self.assertRaisesRegex(ValueError,'log cap'):
                B.execute([sys.executable,'-c','import sys;sys.stdout.write("x"*1048577)'],'overflow',3,
                          root,time.monotonic()+5,lambda:None,commands)
            self.assertLessEqual((root/'overflow.log').stat().st_size,B.LOG_CAP)
            self.assertEqual(commands[0]['status'],'failed')
            self.assertIn('exit',commands[0])

    def test_deadline_still_applies_after_child_closes_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=[];started=time.monotonic()
            with self.assertRaisesRegex(ValueError,'deadline'):
                B.execute([sys.executable,'-c','import os,time;os.close(1);os.close(2);time.sleep(10)'],
                          'closed-pipe',2,root,time.monotonic()+.2,lambda:None,commands)
            self.assertLess(time.monotonic()-started,3)
            self.assertEqual(commands[0]['status'],'failed')
            self.assertNotEqual(commands[0]['exit'],0)

    def test_missing_proof_arguments_never_launch_qualification(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'build.py'),'--phase','qualify'],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn(b'required',result.stderr)


if __name__=='__main__':unittest.main()
