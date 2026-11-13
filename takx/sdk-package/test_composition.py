# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline rejection controls; no SDK classes, compiler or native runtime."""
from pathlib import Path
import json
import importlib.util
from unittest.mock import Mock, patch
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
import composition
import source_families

spec=importlib.util.spec_from_file_location('sdk_public_recipe',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class CompositionGuards(unittest.TestCase):
    def test_actual_java_commands_contain_fatal_logs_in_owned_output(self):
        java=Path('/qualified-jdk');out=Path('/owned-output')
        argv=b.contained_java_argv([java/'bin/java','-Xcheck:jni','Main'],java,out)
        self.assertEqual(argv,[str(java/'bin/java'),'-XX:ErrorFile=/owned-output/hs_err_java_pid%p.log','-Xcheck:jni','Main'])
        compiler=b.contained_java_argv([java/'bin/javac','Source.java'],java,out)
        self.assertEqual(compiler[1:3],['-J-Xmx256m','-J-XX:ErrorFile=/owned-output/hs_err_javac_pid%p.log'])
        self.assertEqual(b.contained_java_argv(['/metadata/tool','arg'],java,out),['/metadata/tool','arg'])

    def test_actual_patch_executor_has_one_patch_and_no_recipe_inputs(self):
        run=Mock();patch=b.HERE/'patches/gles-null-shader-lengths.patch'
        b.apply_source_patch(run,Path('/owned-stage'),patch,'patch-gles')
        argv=run.call_args.args[0]
        self.assertEqual(argv,['patch','--batch','--fuzz=0','--no-backup-if-mismatch','-p1','-d',Path('/owned-stage'),'-i',patch])
        with self.assertRaises(ValueError):b.apply_source_patch(run,Path('/owned-stage'),b.HERE/'GdalReducedProfileSmoke.java','invalid')
        self.assertEqual(run.call_count,1)

    def test_actual_control_compiler_only_consumes_regular_java_sources(self):
        for selected in (False,True):
            run=Mock();sources=b.runtime_control_sources(selected)
            b.compile_java(run,Path('/owned-jdk'),[],Path('/owned-classes'),sources,'controls')
            argv=run.call_args.args[0]
            self.assertEqual(argv[argv.index('-d')+2:],sources)
            self.assertTrue(all(path.is_file() and path.suffix=='.java' for path in sources))
            self.assertEqual(sum(path.name=='GdalReducedProfileSmoke.java' for path in sources),int(selected))
            with self.assertRaises(ValueError):b.compile_java(run,Path('/jdk'),[],Path('/classes'),[*sources,b.HERE/'patches/obj-two-fixture-regression.patch'],'invalid')
            self.assertEqual(run.call_count,1)

    def test_actual_transitive_validator_sources_are_in_recipe_closure(self):
        closure=composition.source_closure()
        for name in ('native-gdal-jni/build.py','native-gdal-jni/kml_profile.py','native-gdal-jni/finalization_validation.py',
                     'kernel-scene/kernel.py','native-deps/build.py','jni_diagnostics.py','sdk-package/composition.py'):
            self.assertEqual(closure[name],composition.digest(b.HERE.parent/name))
        self.assertEqual(b.recipe()['native_finalization_validation'],closure)

    def test_transitive_import_edit_changes_hash_and_link_alias_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'parent.py';child=root/'child.py'
            parent.write_text('# parent source');child.write_text('# child source')
            imported=ModuleType('imported');imported.__file__=str(child)
            consumer=ModuleType('consumer');consumer.__file__=str(parent);consumer.imported=imported
            before=composition.module_source_closure([consumer],root);child.write_text('# changed child')
            after=composition.module_source_closure([consumer],root)
            self.assertNotEqual(before['child.py'],after['child.py']);self.assertEqual(before['parent.py'],after['parent.py'])
            alias=root/'alias.py';alias.symlink_to(child);imported.__file__=str(alias)
            with self.assertRaises(ValueError):composition.module_source_closure([consumer],root)

    def test_successful_and_historical_declarations_are_distinct_closed_variants(self):
        common={'schema':1,'profile':composition.PROFILE}
        historical={**common,**{key:'bound' for key in ('finalization_plan','finalization_plan_sha256','finalization_receipt','finalization_receipt_sha256')}}
        fresh={**common,'producer_kind':'successful',**{key:'bound' for key in ('producer_receipt','producer_receipt_sha256','producer_recipe_sha256')}}
        self.assertEqual(composition.declaration_kind(historical),'historical-finalized')
        self.assertEqual(composition.declaration_kind(fresh),'successful')
        for bad in ([],{**fresh,'schema':True},{**fresh,'producer_kind':'failed'},{**fresh,'originalProducerSuccess':False},
                    {**historical,'producer_kind':'successful'}):
            with self.assertRaises(ValueError):composition.declaration_kind(bad)

    def test_successful_route_replays_public_api_and_requires_actual_checked_controls(self):
        # Protocol-level fixture only: these bytes are never loaded as native code.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);receipt=root/'complete.json';receipt.write_text('{}');(root/'lib').mkdir()
            products={}
            for name in ('libgdal.so','libgdalalljni.so'):
                item=root/'lib'/name;item.write_bytes(b'guard fixture; never loaded');products[name]=composition.digest(item)
                (root/('dynamic-'+name+'.log')).write_text('(NEEDED) Shared library: [libc.so.6]\n'+
                    ('(NEEDED) Shared library: [libgdal.so]\n' if name=='libgdalalljni.so' else ''))
            markers=['GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true',
                     'PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS','PASS_GDAL_KML_DRIVERS_COORDINATES_ORIGINAL_THROWABLES']
            (root/'probe.log').write_text('\n'.join(markers)+'\n')
            data={'recipe':{'fixed-source':'a'*64},'genuine_gdal_jni':True,'kml_profile_enabled':True,
                  'strict_jni_diagnostics_free':True,'gdal_version':'2.4.4','checked_jni_warning_count':0,
                  'kml_build':{'buildInventory':{}},'gdal_archive_objects':1073,'products':products,
                  'bound_files':{},'mapped_providers':{str(root/'lib'/name):sha for name,sha in products.items()},
                  'dynamic_needed':{'libgdal.so':['libc.so.6'],'libgdalalljni.so':['libc.so.6','libgdal.so']}}
            producer=SimpleNamespace(replay=Mock(return_value=data),diagnostics=composition.validator().producer.diagnostics,
                                     audit_dynamic=composition.validator().producer.audit_dynamic)
            config={'producer_receipt':str(receipt),'producer_receipt_sha256':composition.digest(receipt),
                    'producer_recipe_sha256':b.hashlib.sha256(json.dumps(data['recipe'],sort_keys=True,separators=(',',':')).encode()).hexdigest()}
            with patch.object(composition,'validator',return_value=SimpleNamespace(producer=producer)),patch.object(composition,'verify_reduced_closure') as reduced:
                result=composition.successful_receipt(config)
                producer.replay.assert_called_once_with(root);self.assertTrue(result[3]['original_producer_success'])
                self.assertFalse(result[3]['original_failure_preserved']);reduced.assert_called_once()
                for key,value in [('kml_profile_enabled',False),('checked_jni_warning_count',1),('checked_jni_warning_count',False)]:
                    old=data[key];data[key]=value
                    with self.subTest(key=key,value=value),self.assertRaises(ValueError):composition.successful_receipt(config)
                    data[key]=old
                with self.assertRaises(ValueError):composition.successful_receipt({**config,'producer_recipe_sha256':'0'*64})
                (root/'probe.log').write_text('missing actual controls')
                with self.assertRaisesRegex(ValueError,'checked JNI controls'):composition.successful_receipt(config)
                (root/'failed.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'genuine completed'):composition.successful_receipt(config)

    def test_changed_declaration_rejected_before_any_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'selection.json';path.write_text('{}');sha=composition.digest(path);path.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'input differs'):composition.inspect(path,sha)

    def test_unrecognized_profile_cannot_enable_source_variant(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'selection.json';path.write_text(json.dumps({'profile':'full'}))
            with self.assertRaisesRegex(ValueError,'supported composition'):composition.inspect(path,composition.digest(path))

    def test_symlink_declaration_is_not_a_frozen_input(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'actual';target.write_text('{}');link=Path(temp)/'alias';link.symlink_to(target)
            with self.assertRaises(ValueError):composition.inspect(link,composition.digest(target))

    def test_full_profile_cannot_replace_gdal_family(self):
        original={name+'.class':b'original inventory' for name in source_families.FAMILIES}
        original['com/atakmap/map/gdal/GdalLibrary.class']=b'upstream skip policy'
        replacement={n:b'changed' for n in source_families.members(original)}
        replacement['com/atakmap/map/gdal/GdalLibrary.class']=b'forbidden automatic change'
        with self.assertRaises(ValueError):source_families.merge(original,replacement)

    def test_explicit_family_must_include_every_existing_inner(self):
        family='com/atakmap/map/layer/model/obj/ObjModelSpi'
        original={name+'.class':b'original inventory' for name in source_families.FAMILIES}
        original.update({family+'.class':b'outer',family+'$CallbackReader.class':b'inner'})
        replacement={n:b'changed' for n in source_families.members(original,source_families.FAMILIES+(family,))}
        del replacement[family+'$CallbackReader.class']
        with self.assertRaises(ValueError):source_families.merge(original,replacement,(family,))
