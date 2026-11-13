# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess

SPEC=importlib.util.spec_from_file_location('cesium_builder',Path(__file__).with_name('build.py'))
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)


class ResumeGuards(unittest.TestCase):
    def test_crlf_patch_applies_to_lf_source_without_changing_vendor_patch(self):
        patch=b'--- a/input.txt\r\n+++ b/input.txt\r\n@@ -1 +1 @@\r\n-before\r\n+after\r\n'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'vendor.patch';original.write_bytes(patch)
            source=root/'input.txt';source.write_bytes(b'before\n')
            records=[];staged=B.stage_patch(original,root/'staged/port.patch',records)
            result=subprocess.run(['patch','--binary','--batch','--fuzz=0','-p1','-d',str(root),'-i',str(staged)],capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(source.read_bytes(),b'after\n')
            self.assertEqual(original.read_bytes(),patch)
            self.assertEqual(staged.read_bytes(),patch.replace(b'\r\n',b'\n'))
            self.assertEqual(records[0]['preimage'],B.a.native.digest(original))
            self.assertEqual(records[0]['postimage'],B.a.native.digest(staged))

    def test_lf_patch_is_unchanged_and_mixed_or_bare_cr_is_refused(self):
        self.assertEqual(B.canonical_patch(b'patch\ncontent\n'),b'patch\ncontent\n')
        for raw in (b'patch\rcontent\n',b'patch\r\ncontent\n'):
            with self.assertRaisesRegex(ValueError,'port patch refused'):B.canonical_patch(raw)

    def fixture(self,root,completed=None):
        old=root/'old';old.mkdir();(old/'install').mkdir()
        (old/'install/libreal.a').write_bytes(b'genuine product fixture')
        tool=root/'compiler';tool.write_bytes(b'bound actual tool')
        tools={'compiler':{'path':str(tool),'sha256':B.a.native.digest(tool)}}
        providers={'sqlcipher':{'receipt':'bound'}}
        (old/'producer.json').write_text(json.dumps({'tools':tools,'providers':providers,'sources_receipt_sha256':'source identity'}))
        (old/'failed.json').write_text(json.dumps({'completed':completed or ['first']}))
        snapshot=root/'inventory.json';snapshot.write_text(json.dumps(B.a.inventory(old)))
        return old,snapshot,tools,providers

    def test_validated_resume_retains_true_original_lineage(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.fixture(Path(d))
            lineage,completed,_=B.verify_resume(*args,'source identity',['first','next'])
            self.assertFalse(lineage['fresh_dependency_build'])
            self.assertEqual(completed,['first'])
            self.assertEqual(lineage['original_producer']['tools'],args[2])

    def test_changed_added_or_linked_stopped_input_is_rejected(self):
        for change in ('changed','added','link'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                args=self.fixture(Path(d));old=args[0]
                if change=='changed':(old/'install/libreal.a').write_bytes(b'changed product')
                elif change=='added':(old/'unexpected').write_bytes(b'extra')
                else:(old/'unexpected').symlink_to('install/libreal.a')
                with self.assertRaises(ValueError):B.verify_resume(*args,'source identity',['first','next'])

    def test_changed_actual_tool_or_provider_or_action_order_is_rejected(self):
        for change in ('tool','provider','source','order'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                args=list(self.fixture(Path(d)))
                if change=='tool':(Path(d)/'compiler').write_bytes(b'changed compiler')
                if change=='provider':args[3]={'sqlcipher':{'receipt':'different'}}
                with self.assertRaises(ValueError):
                    B.verify_resume(*args,'different' if change=='source' else 'source identity',['next','first'] if change=='order' else ['first','next'])

    def test_pkgconfig_relocation_changes_only_owned_copy_and_rejects_cmake_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old=root/'old';prefix=root/'new';prefix.mkdir();old.mkdir()
            original=b'prefix='+str(old/'install').encode()+b'\nLibs: -lreal\n'
            (old/'real.pc').write_bytes(original);(prefix/'real.pc').write_bytes(original)
            changes=[];B.relocate_pkgconfig(prefix,old,changes)
            self.assertEqual((old/'real.pc').read_bytes(),original)
            self.assertEqual((prefix/'real.pc').read_bytes(),original.replace(str(old/'install').encode(),str(prefix).encode()))
            self.assertEqual(len(changes),1)
            (prefix/'bad.cmake').write_text(str(old/'install/libreal.a'))
            with self.assertRaises(ValueError):B.relocate_pkgconfig(prefix,old,[])


if __name__=='__main__':unittest.main()
