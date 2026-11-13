# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Byte-only source binding controls; never import the historical source fixture."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('native_snapshot_guards',Path(__file__).with_name('native_source_snapshot.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

build_spec=importlib.util.spec_from_file_location('sdk_source_binding_consumer',Path(__file__).with_name('build.py'))
b=importlib.util.module_from_spec(build_spec);build_spec.loader.exec_module(b)

class SourceBindingTests(unittest.TestCase):
    def fixture(self,root):
        snapshot=root/'snapshot';snapshot.mkdir()
        body=b'raise RuntimeError("HISTORICAL CODE MUST NEVER EXECUTE")\n'
        relative='source/takx/kernel-native/build.py';path=snapshot/relative;path.parent.mkdir(parents=True);path.write_bytes(body);path.chmod(0o444)
        recipe={'build.py':s.digest_bytes(body)};recipe_sha=s.digest_bytes(json.dumps(recipe,sort_keys=True,separators=(',',':')).encode())
        manifest={'schema':1,'profile':'reviewed-fixture','sourceCount':1,'gitSourceCommit':'a'*40,'nativeRecipeSHA256':recipe_sha,
                  'files':[{'snapshotPath':relative,'receiptRecipePath':'build.py','sha256':recipe['build.py'],'bytes':len(body)}]}
        recipe_bytes=json.dumps(recipe).encode();(snapshot/'recipe.json').write_bytes(recipe_bytes);(snapshot/'recipe.json').chmod(0o444)
        manifest['recipeFile']={'path':'recipe.json','bytes':len(recipe_bytes),'sha256':s.digest_bytes(recipe_bytes)}
        raw=json.dumps(manifest).encode();(snapshot/'manifest.json').write_bytes(raw);(snapshot/'manifest.json').chmod(0o444)
        for directory in snapshot.rglob('*'):
            if directory.is_dir():directory.chmod(0o555)
        snapshot.chmod(0o555)
        receipt=root/'complete.json';receipt.write_text(json.dumps({'recipe':recipe}))
        known={s.digest_bytes(raw):{'profile':'reviewed-fixture','source_count':1,'git_source_commit':'a'*40,'native_recipe_sha256':recipe_sha}}
        return snapshot,receipt,s.digest_bytes(receipt.read_bytes()),known,path

    def test_exact_reviewed_bundle_is_bytes_only_and_receipt_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot,receipt,expected,known,path=self.fixture(Path(directory))
            result=s.verify(snapshot,receipt,expected,known)
            self.assertEqual(result['native_receipt_sha256'],expected);self.assertFalse(result['historical_code_executed'])
            self.assertEqual(result['source_count'],1)
            with patch.object(s.json,'loads',side_effect=AssertionError('must reject before parsing')):
                with self.assertRaisesRegex(ValueError,'explicit native receipt SHA differs'):s.verify(snapshot,receipt,'0'*64,known)
            with self.assertRaisesRegex(ValueError,'consumer-reviewed'):s.verify(snapshot,receipt,expected,{})

    def test_changed_missing_extra_or_linked_source_is_refused(self):
        for defect in ('changed','missing','extra','link','writable','writable-directory','extra-directory'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as directory:
                snapshot,receipt,expected,known,path=self.fixture(Path(directory))
                if defect=='changed':path.chmod(0o644);path.write_text('changed');path.chmod(0o444)
                if defect=='missing':path.parent.chmod(0o755);path.unlink();path.parent.chmod(0o555)
                if defect=='extra':snapshot.chmod(0o755);(snapshot/'extra.py').write_text('not requested');snapshot.chmod(0o555)
                if defect=='link':
                    target=Path(directory)/'outside';target.write_bytes(path.read_bytes());path.parent.chmod(0o755);path.unlink();path.symlink_to(target);path.parent.chmod(0o555)
                if defect=='writable':path.chmod(0o644)
                if defect=='writable-directory':path.parent.chmod(0o755)
                if defect=='extra-directory':snapshot.chmod(0o755);(snapshot/'extra').mkdir(mode=0o555);snapshot.chmod(0o555)
                with self.assertRaises(ValueError):s.verify(snapshot,receipt,expected,known)

    def test_snapshot_route_keeps_provider_tool_layout_and_elf_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);elf=root/'lib.so';elf.write_bytes(b'identity fixture never loaded')
            raw={'recipe':{},'native_translation_units':{'core':483,'jni':159,'cesium':173},'fresh_native_build':True,
                 'specified_runtime_controls_passed':True,'providers':{'reviewed':'provider'},'staged_sources':{},
                 'gltf_headers':{},'gles1_declarations':{},'actual_toolchain':{'reviewed':'toolchain'},
                 'elf_audit':{'elfs':{'engine':{'relative_path':'lib.so','sha256':b.p.digest(elf)}}}}
            (root/'complete.json').write_text(json.dumps(raw))
            with patch.object(b.native_source_snapshot,'verify',return_value={'reviewed':'binding'}) as snapshot,                 patch.object(b,'recipe',return_value={}),patch.object(b.b,'recipe',return_value={}),                 patch.object(b.p,'verify_all',return_value=({'reviewed':'provider'},{})) as providers,                 patch.object(b.p,'check_files') as files,patch.object(b.p,'inventory',return_value={}),                 patch.object(b.p,'root_of',return_value=Path('/reviewed-provider')),                 patch.object(b.b.toolchain,'verify') as tools:
                result=b.verify_native(root,{},Path('/reviewed-snapshot'),'a'*64)
                self.assertEqual(result,(raw,{'reviewed':'provider'}));self.assertEqual(files.call_count,4)
                snapshot.assert_called_once();providers.assert_called_once_with({});tools.assert_called_once_with(raw['actual_toolchain'])
                providers.return_value=({'different':'provider'},{})
                with self.assertRaisesRegex(ValueError,'native providers differ'):b.verify_native(root,{},Path('/snapshot'),'a'*64)
                providers.return_value=({'reviewed':'provider'},{})
                tools.side_effect=ValueError('toolchain changed')
                with self.assertRaisesRegex(ValueError,'toolchain changed'):b.verify_native(root,{},Path('/snapshot'),'a'*64)
                tools.side_effect=None;elf.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'native ELF differs'):b.verify_native(root,{},Path('/snapshot'),'a'*64)

    def test_receipt_cannot_choose_another_source_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot,receipt,expected,known,path=self.fixture(Path(directory))
            receipt.write_text(json.dumps({'recipe':{'build.py':'b'*64}}))
            with self.assertRaisesRegex(ValueError,'original native recipe differs'):
                s.verify(snapshot,receipt,s.digest_bytes(receipt.read_bytes()),known)

if __name__=='__main__':unittest.main()
