# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
SPEC=importlib.util.spec_from_file_location('public_kml',Path(__file__).with_name('build.py'))
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)


class SourceGuards(unittest.TestCase):
    def archive(self,root,kind):
        path=root/'source.tar'
        with tarfile.open(path,'w') as tar:
            if kind=='traversal':name='vendor/../outside'
            else:name='vendor/file'
            member=tarfile.TarInfo(name)
            if kind=='symlink':member.type=tarfile.SYMTYPE;member.linkname='/outside';tar.addfile(member)
            else:
                member.size=2;tar.addfile(member,io.BytesIO(b'xx'))
                if kind=='duplicate':tar.addfile(member,io.BytesIO(b'xx'))
        return path,{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_fresh_cesium_needs_real_freshness_and_no_stopped_snapshot(self):
        fresh={'lineage':None,'fresh_dependency_build':True,'fresh_cesium_build':True}
        B.verify_cesium_lineage(fresh,None)
        for value,snapshot in [({**fresh,'fresh_dependency_build':False},None),
                               ({**fresh,'fresh_cesium_build':False},None),(fresh,Path('/foreign')),
                               ({**fresh,'lineage':{'previous_output':'/foreign'}},None)]:
            with self.assertRaises(ValueError):B.verify_cesium_lineage(value,snapshot)

    def test_continued_cesium_still_checks_stopped_inventory(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';old.mkdir();(old/'source').write_text('pinned')
            snapshot=root/'snapshot.json';snapshot.write_text(json.dumps(B.inventory(old)))
            receipt={'fresh_dependency_build':False,'lineage':{'previous_output':str(old),
                      'stopped_inventory_sha256':B.native.digest(snapshot)}}
            B.verify_cesium_lineage(receipt,snapshot)
            (old/'source').write_text('changed')
            with self.assertRaises(ValueError):B.verify_cesium_lineage(receipt,snapshot)

    def test_archive_identity_is_checked_before_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path,entry=self.archive(root,'regular');entry['sha256']='0'*64
            with self.assertRaises(ValueError):B.extract(path,root/'out',entry)
            self.assertFalse((root/'out').exists())

    def test_unsafe_members_rejected_before_materialization(self):
        for kind in ('traversal','symlink','duplicate'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                root=Path(d);path,entry=self.archive(root,kind)
                with self.assertRaises(ValueError):B.extract(path,root/'out',entry)
                self.assertFalse((root/'out').exists())

    def test_real_regular_bytes_are_recorded_and_tampering_changes_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path,entry=self.archive(root,'regular')
            self.assertEqual(B.extract(path,root/'out',entry),2)
            before=B.inventory(root/'out');(root/'out/file').write_bytes(b'changed')
            self.assertNotEqual(B.inventory(root/'out'),before)
            (root/'out/link').symlink_to('file')
            with self.assertRaises(ValueError):B.inventory(root/'out')


if __name__=='__main__':unittest.main()
