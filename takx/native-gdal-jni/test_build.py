#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline fail-closed compiler-input guards."""
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import subprocess
import unittest
spec=importlib.util.spec_from_file_location('gdal_jni_build',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Guards(unittest.TestCase):
    def test_actual_dependency_continuations_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); header=root/'real.h';header.write_bytes(b'actual header')
            deps=root/'wrap.d';deps.write_text('wrap.o: \\\n '+str(header)+'\n')
            self.assertEqual(b.consumed_headers(deps,[root]),{str(header):b.b.native.digest(header)})
    def test_foreign_header_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); header=root/'foreign.h';header.write_bytes(b'x');deps=root/'wrap.d';deps.write_text('wrap.o: '+str(header))
            with self.assertRaises(ValueError):b.consumed_headers(deps,[root/'allowed'])
    def test_symlink_header_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);real=root/'real.h';real.write_bytes(b'x');link=root/'link.h';link.symlink_to(real);deps=root/'wrap.d';deps.write_text('wrap.o: '+str(link))
            with self.assertRaises(ValueError):b.consumed_headers(deps,[root])
    def test_missing_or_empty_dependencies_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);deps=root/'wrap.d'
            for body in ('wrap.o:','wrap.o: '+str(root/'missing.h')):
                deps.write_text(body)
                with self.assertRaises(ValueError):b.consumed_headers(deps,[root])
class DynamicGuards(unittest.TestCase):
    def test_textrel_and_unexpected_dependency_rejected(self):
        for text in ('TEXTREL', '(NEEDED) Shared library: [libcrypto.so.3]', '(NEEDED) Shared library: [/tmp/libgdal.so]'):
            with self.assertRaises(ValueError):b.audit_dynamic(Path('libgdal.so'),text)
    def test_shared_provider_required(self):
        with self.assertRaises(ValueError):b.audit_dynamic(Path('libgdalalljni.so'),'(NEEDED) Shared library: [libc.so.6]')
    @unittest.skipUnless(os.environ.get('GDAL_JNI_PROOF'),'explicit existing real proof only; no default compilation')
    def test_opt_in_real_receipt_replay(self):
        proof=Path(os.environ['GDAL_JNI_PROOF']).resolve()
        data=b.replay(proof)
        self.assertTrue(data['genuine_gdal_jni']);self.assertEqual(data['gdal_archive_objects'],1056)
        java=[Path(n) for n in data['tools'] if Path(n).name=='java']
        jars=[Path(n) for n in data['bound_files'] if Path(n).name=='gdal-2.4.4-mod-java.jar']
        headers=[Path(n) for n in data['bound_files'] if Path(n).name=='gdal_version.h'
                 and Path(n).parent.name=='include' and Path(n).parent.parent.name=='gdal-install']
        self.assertEqual((len(java),len(jars),len(headers)),(1,1,1))
        native_prefix=headers[0].parent.parent
        accepted=json.loads((proof/'accepted-inputs.json').read_text())
        self.assertEqual(b.b.native.inventory(native_prefix),accepted['native']['installed'])
        env=b.b.assimp.environment('/usr/bin/gcc','/usr/bin/g++')
        for key in list(env):
            if key.startswith(('LD_','GDAL_','PROJ_','BASH_FUNC_')) or key in (
                'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH'):
                env.pop(key)
        env['GDAL_DATA']=str(native_prefix/'share/gdal')
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([str(java[0]),'-Xmx128m','-Djava.library.path='+str(proof/'lib'),
                '-cp',str(proof/'classes')+os.pathsep+str(jars[0]),'GdalJniProbe'],
                cwd=temp,env=env,capture_output=True,text=True,timeout=60,check=True)
        self.assertEqual(result.stdout.splitlines().count(
            'GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true'),1)
        providers={line[4:] for line in result.stdout.splitlines() if line.startswith('ELF ')}
        self.assertEqual(providers,set(data['mapped_providers']))
        b.unchanged(data['mapped_providers'])
if __name__=='__main__':unittest.main()
