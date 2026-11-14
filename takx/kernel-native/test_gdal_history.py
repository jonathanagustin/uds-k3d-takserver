# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Pure source/receipt guards; no provider replay run, JVM, or native execution."""
import ast
import copy
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gdal_history_providers', HERE/'providers.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
SOURCE = HERE.parent/'native-gdal-jni/build.py'
TREE = ast.parse(SOURCE.read_text())
NAMES = next(ast.literal_eval(node.value) for node in TREE.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'RECIPE_PATHS' for target in node.targets))


def pure_replay():
    # Load the actual pure functions without importing build/tool dependencies.
    selected = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and
                node.name in ('file_hashes', 'unchanged', 'replay', 'replay_artifacts')]
    namespace = {'Path': Path, 'json': json, 'b': SimpleNamespace(native=SimpleNamespace(digest=p.digest)),
                 'recipe': lambda: {name:p.digest(HERE.parent/name) for name in NAMES}}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class GdalHistory(unittest.TestCase):
    def setUp(self):
        self.history = p.load(HERE/'producer-history.lock.json')['gdal_jni']
        self.producer = SimpleNamespace(HERE=SOURCE.parent,
            recipe=lambda: {name:p.digest(HERE.parent/name) for name in NAMES}, **{
                name:value for name,value in pure_replay().items() if name in ('replay','replay_artifacts')})
        self.record = {'recipe':copy.deepcopy(self.history['recipe']), 'tools':{}}

    def test_history_and_native_lock_pins_bind_exact_current_bytes(self):
        tree=ast.parse((HERE/'build.py').read_text())
        constant=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                      and any(isinstance(target,ast.Name) and target.id=='LOCK_SHA' for target in node.targets))
        lock=p.load(HERE/'inputs.lock.json')
        self.assertEqual(hashlib.sha256(json.dumps(lock,sort_keys=True).encode()).hexdigest(),constant)
        self.assertEqual(lock['historical_producer_sources_sha256'],p.digest(HERE/'producer-history.lock.json'))

    def test_exact_curated_twenty_file_variant_and_reviewed_deltas(self):
        self.assertEqual(len(self.history['recipe']),20)
        self.assertEqual(set(self.history['variants']),{'native-gdal-jni/build.py','gis-java/build.py','kernel-scene/kernel.py'})
        with patch.object(p,'module',return_value=self.producer):
            self.assertTrue(p.recipe_check('gdal_jni',self.record))
        for entry in self.history['variants'].values():
            source=HERE/entry['snapshot']
            self.assertEqual(p.digest(source),entry['sha256'])
            self.assertEqual(source.stat().st_size,entry['bytes'])
            self.assertEqual(p.digest(Path(str(source)+'.diff')),entry['delta_to_current_sha256'])
            self.assertFalse(source.stat().st_mode & 0o111)
        for name,entry in self.history['variants'].items():
            source=HERE/entry['snapshot']
            delta=''.join(difflib.unified_diff(source.read_text().splitlines(True),
                (HERE.parent/name).read_text().splitlines(True),fromfile='historical/'+name,tofile='current/'+name))
            self.assertEqual(Path(str(source)+'.diff').read_text(),delta)

    def test_unknown_map_changed_body_escape_and_tools_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p,'module',return_value=self.producer):
            bad=copy.deepcopy(self.record);bad['recipe']['native-gdal-jni/build.py']='0'*64
            with self.assertRaisesRegex(ValueError,'unreviewed consumed'):p.recipe_check('gdal_jni',bad)
            snapshot=HERE/self.history['variants']['native-gdal-jni/build.py']['snapshot']
            digest=p.digest
            with patch.object(p,'digest',side_effect=lambda path:'0'*64 if Path(path)==snapshot else digest(path)):
                with self.assertRaisesRegex(ValueError,'source body differs'):p.recipe_check('gdal_jni',self.record)
            history=p.load(HERE/'producer-history.lock.json')
            history['gdal_jni']['variants']['native-gdal-jni/build.py']['snapshot']=str(Path(directory)/'outside')
            with patch.object(p,'load',return_value=history),self.assertRaises(ValueError):
                p.recipe_check('gdal_jni',self.record)
            tool=Path(directory)/'compiler';tool.write_bytes(b'current compiler')
            bad=copy.deepcopy(self.record);bad['tools']={str(tool):'0'*64}
            with self.assertRaisesRegex(ValueError,'producer tool changed'):p.recipe_check('gdal_jni',bad)

    def fixture(self,root):
        for folder in ('lib','classes'):(root/folder).mkdir()
        (root/'lib/library.so').write_bytes(b'offline artifact fixture')
        (root/'classes/Probe.class').write_bytes(b'offline class fixture')
        bound=root/'bound';bound.write_bytes(b'bound input')
        mapped=root/'mapped';mapped.write_bytes(b'actual mapped fixture')
        evidence=root/'control.json';evidence.write_text('{}')
        replay=pure_replay()
        record={**copy.deepcopy(self.record),'products':replay['file_hashes'](root/'lib'),
            'probe_classes':replay['file_hashes'](root/'classes'),'bound_files':{str(bound):p.digest(bound)},
            'mapped_providers':{str(mapped):p.digest(mapped)},'evidence':{'control.json':p.digest(evidence)},
            'native_kernel_or_client_acceptance':False}
        (root/'complete.json').write_text(json.dumps(record));return record

    def test_historical_admission_still_checks_products_classes_bound_mapped_and_evidence(self):
        for mutation in (None,'products','classes','bound','mapped','evidence','acceptance'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);record=self.fixture(root)
                target={'products':'lib/library.so','classes':'classes/Probe.class','bound':'bound','mapped':'mapped','evidence':'control.json'}.get(mutation)
                if target:(root/target).write_bytes(b'tampered')
                if mutation=='acceptance':
                    record['native_kernel_or_client_acceptance']=True;(root/'complete.json').write_text(json.dumps(record))
                with patch.object(p,'module',return_value=self.producer):
                    if mutation:
                        with self.assertRaises(ValueError):p.verify('gdal_jni',root)
                    else:self.assertEqual(p.verify('gdal_jni',root)['source_recipe'],record['recipe'])

    def test_strict_public_replay_and_historical_profile_claims_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'replay recipe differs'):self.producer.replay(root)
            for key in ('kml_profile_enabled','strict_jni_diagnostics_free','kml_build'):
                bad=copy.deepcopy(record);bad[key]=True;(root/'complete.json').write_text(json.dumps(bad))
                with patch.object(p,'module',return_value=self.producer),self.assertRaisesRegex(ValueError,'cannot claim'):
                    p.verify('gdal_jni',root)
