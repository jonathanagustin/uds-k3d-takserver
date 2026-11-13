# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline rejection controls; no SDK classes, compiler or native runtime."""
from pathlib import Path
import json
import importlib.util
from unittest.mock import Mock
import tempfile
import unittest
import composition
import source_families

spec=importlib.util.spec_from_file_location('sdk_public_recipe',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class CompositionGuards(unittest.TestCase):
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
