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
from unittest.mock import Mock
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
class KmlAdmissionGuards(unittest.TestCase):
    def test_actual_inventory_metadata_and_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);item=root/'header.h';item.write_bytes(b'owned admission fixture')
            expected={'header.h':{'bytes':item.stat().st_size,'sha256':b.kml.digest(item)}}
            b.kml.verify_inventory(root,expected)
            expected['header.h']['bytes']+=1
            with self.assertRaisesRegex(ValueError,'size differs'):b.kml.verify_inventory(root,expected)
            expected['header.h']['bytes']-=1
            item.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'inventory differs'):b.kml.verify_inventory(root,expected)
    def test_missing_provider_directory_never_equals_empty_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'directory required'):
                b.kml.verify_inventory(Path(temp)/'absent',{})
class CompilerBackendGuards(unittest.TestCase):
    def test_selected_compiler_identifies_hash_bound_helpers_without_host_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);helpers=[]
            for name in ('cc1','cc1plus','collect2'):
                item=root/name;item.write_bytes(('owned metadata fixture '+name).encode());helpers.append(item)
            run=Mock(side_effect=[(str(item)+'\n').encode() for item in helpers])
            self.assertEqual(b.compiler_backends('/selected/gcc',run),{str(item):b.b.native.digest(item) for item in helpers})
            self.assertEqual([call.args[0] for call in run.call_args_list],
                [['/selected/gcc','-print-prog-name='+name] for name in ('cc1','cc1plus','collect2')])
    def test_unresolved_or_missing_helpers_are_rejected(self):
        for value in (b'cc1\n',b'/definitely-missing-compiler-helper\n',b''):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'existing absolute backend'):
                b.compiler_backends('/selected/gcc',Mock(return_value=value))
class OwnedGnuTreeGuards(unittest.TestCase):
    def test_only_exact_internal_metadata_link_is_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.libs').mkdir();(root/'libgdal.la').write_bytes(b'owned GNU metadata fixture')
            (root/'.libs/libgdal.la').symlink_to('../libgdal.la')
            snapshot=b.kml.owned_gnu_build_inventory(root)
            self.assertEqual(snapshot['symlinks']['.libs/libgdal.la']['target'],'../libgdal.la')
            self.assertEqual(b.kml.legacy_gnu_build_inventory(snapshot)['.libs/libgdal.la'],b.kml.digest(root/'libgdal.la'))
            with self.assertRaisesRegex(ValueError,'symlink inventory input'):b.file_hashes(root)
    def test_other_absolute_dangling_or_external_links_fail(self):
        for target in ('../missing.la','/etc/passwd','../../outside.la'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'.libs').mkdir();(root/'libgdal.la').write_bytes(b'owned')
                (root/'.libs/libgdal.la').symlink_to(target)
                with self.assertRaises(ValueError):b.kml.owned_gnu_build_inventory(root)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'.libs').mkdir();(root/'libgdal.la').write_bytes(b'owned')
            (root/'.libs/libgdal.la').symlink_to('../libgdal.la');(root/'unexpected').symlink_to('libgdal.la')
            with self.assertRaisesRegex(ValueError,'unexpected'):b.kml.owned_gnu_build_inventory(root)
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
        self.assertTrue(data['genuine_gdal_jni'])
        enabled=data.get('kml_profile_enabled',False)
        self.assertGreater(data['gdal_archive_objects'],0)
        java=[Path(n) for n in data['tools'] if Path(n).name=='java']
        jars=[Path(n) for n in data['bound_files'] if Path(n).name=='gdal-2.4.4-mod-java.jar']
        headers=[Path(n) for n in data['bound_files'] if Path(n).name=='gdal_version.h'
                 and Path(n).parent.name=='include' and Path(n).parent.parent.name in ('gdal-install','gdal-kml-install')]
        self.assertEqual((len(java),len(jars),len(headers)),(1,1,1))
        native_prefix=headers[0].parent.parent
        accepted=json.loads((proof/'accepted-inputs.json').read_text())
        if enabled:
            self.assertEqual(b.file_hashes(native_prefix),data['kml_build']['installed'])
        else:
            self.assertEqual(b.b.native.inventory(native_prefix),accepted['native']['installed'])
        self.assertEqual(sum(b.kernel.archive_members(native_prefix/'lib/libgdal.a').values()),data['gdal_archive_objects'])
        env=b.b.assimp.environment('/usr/bin/gcc','/usr/bin/g++')
        for key in list(env):
            if key.startswith(('LD_','GDAL_','PROJ_','BASH_FUNC_')) or key in (
                'JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH'):
                env.pop(key)
        env['GDAL_DATA']=str(native_prefix/'share/gdal')
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([str(java[0]),'-Xcheck:jni','-Xmx128m','-Djava.library.path='+str(proof/'lib'),
                '-cp',str(proof/'classes')+os.pathsep+str(jars[0]),'GdalFormatProfileProbe' if enabled else 'GdalJniProbe'],
                cwd=temp,env=env,capture_output=True,text=True,timeout=60,check=True)
        self.assertFalse(b.diagnostics.strict_jni_failures(result.stdout+result.stderr))
        self.assertEqual(result.stdout.splitlines().count(
            'GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true'),1)
        if enabled:
            self.assertEqual(result.stdout.splitlines().count('PASS_GDAL_KML_DRIVERS_COORDINATES_ORIGINAL_THROWABLES'),1)
            self.assertEqual(result.stdout.splitlines().count('PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS'),1)
        providers={line[4:] for line in result.stdout.splitlines() if line.startswith('ELF ')}
        self.assertEqual(providers,set(data['mapped_providers']))
        b.unchanged(data['mapped_providers'])
if __name__=='__main__':unittest.main()
