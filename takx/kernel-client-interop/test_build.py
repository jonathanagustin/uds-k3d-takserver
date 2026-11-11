# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline mutation and command-boundary controls; no compiler/native execution."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('client_interop_build',Path(__file__).with_name('build.py'))
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

class Guards(unittest.TestCase):
    def test_real_source_lock(self):
        build.validate(build.load(build.HERE/'inputs.lock.json'))
    def test_no_version_alias(self):
        lock=build.load(build.HERE/'inputs.lock.json');lock['actual_kernel_version']='8.57.11'
        with self.assertRaises(ValueError):build.validate(lock)
    def test_changed_patch_rejected(self):
        lock=build.load(build.HERE/'inputs.lock.json');lock['patch_sha256']='0'*64
        with self.assertRaises(ValueError):build.validate(lock)
    def test_changed_policy_rejected(self):
        lock=build.load(build.HERE/'inputs.lock.json');lock['owned_java']['java/PublicViewportFit.java']='0'*64
        with self.assertRaises(ValueError):build.validate(lock)
    def test_output_cannot_replace_or_nest_input(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);source=path/'source';source.mkdir()
            for output in [source,source/'child',path]:
                with self.assertRaises(ValueError):build.disjoint(output,[source])
            build.disjoint(path/'new',[source])
    def test_syntax_command_has_no_object_or_dependency_outputs(self):
        row={'file':'/old/source.cpp','arguments':['g++','-DREAL=1','-I/real/include','-MD','-MF','deps.d','-MT','object.o','-o','object.o','-c','/old/source.cpp']}
        argv=build.syntax_command(row,Path('/owned/source.cpp'),Path('/owned/headers'))
        self.assertEqual(argv,['g++','-fsyntax-only','-I/owned/headers','-DREAL=1','-I/real/include','/owned/source.cpp'])
    def test_syntax_requires_exact_direct_source(self):
        for row in [{'file':'a.cpp','arguments':['g++','-c','b.cpp']},{'file':'a.cpp','arguments':['g++','@hidden.rsp','a.cpp']},{'file':'a.cpp','arguments':['g++','a.cpp','-o']}]:
            with self.assertRaises(ValueError):build.syntax_command(row,Path('/owned/source.cpp'),Path('/owned/headers'))
    def test_real_bridge_and_runtime_limits_are_explicit(self):
        lock=build.load(build.HERE/'inputs.lock.json')
        self.assertEqual(len(lock['files']),9)
        self.assertFalse(lock['native_execution_accepted']);self.assertFalse(lock['multipoint_detail_accepted'])
        self.assertEqual({v['coordinate'] for v in lock['public_runtime_jars'].values()},{'com.github.weisj:jsvg:1.6.1','org.gavaghan:geodesy:1.1.3'})

if __name__=='__main__':unittest.main()
