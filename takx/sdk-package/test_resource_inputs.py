# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import json
from pathlib import Path
import unittest
import resource_inputs as r

class ResourceTests(unittest.TestCase):
    def fixture(self, paths=None):
        paths=paths or ['takkernel/engine/src/main/res/raw/shader.glsl','takkernel/engine/src/main/res/drawable/icon.png','takkernel/shared/src/main/assets/meshes/cube.obj','takkernel/engine/src/main/res/values/strings.xml']
        data={name:('real fixture '+name).encode() for name in paths};files=[];tree={}
        for name,value in data.items():
            dest,kind=r.destination(name);blob=hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest();tree[name]=('100644',blob,len(value))
            files.append(dict(source=name,destination=dest,kind=kind,mode='100644',blob=blob,bytes=len(value),sha256=hashlib.sha256(value).hexdigest()))
        return dict(namespace='gov.tak.desktop',files=files),tree,data
    def test_gradle_mapping_and_catalog(self):
        lock,tree,data=self.fixture();entries=r.collect(lock,tree,data.__getitem__)
        self.assertEqual(len(entries),5)
        self.assertIn('resources/drawable/icon',entries)
        self.assertIn('assets/meshes/cube.obj',entries)
        self.assertIn(b'gov.tak.desktop/raw/shader=resources/raw/shader\n',entries[r.CATALOG])
        self.assertNotIn(b'values',entries[r.CATALOG])
        self.assertEqual(entries['resources/values/strings'],data['takkernel/engine/src/main/res/values/strings.xml'])
    def test_exact_118_production_files(self):
        lock=json.loads((Path(__file__).parent/'runtime-resources.lock.json').read_text())
        self.assertEqual(len(lock['files']),118)
        self.assertEqual(sum(x['bytes'] for x in lock['files']),6666272)
        self.assertEqual(sum(x['kind']=='raw' for x in lock['files']),20)
        self.assertEqual(sum(x['kind']=='drawable' for x in lock['files']),5)
        self.assertEqual(len({x['destination'] for x in lock['files']}),118)
        self.assertEqual(sum(x['source'].endswith('/LICENSE.md') for x in lock['files']),3)
    def test_omission_and_addition_rejected(self):
        lock,tree,data=self.fixture();tree.pop(next(iter(tree)))
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_added_source_rejected(self):
        lock,tree,data=self.fixture();tree['takkernel/engine/src/main/assets/new']=('100644','0'*40,1)
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_changed_bytes_rejected(self):
        lock,tree,data=self.fixture();data[next(iter(data))]=b'changed'
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_hash_valid_lfs_pointer_rejected(self):
        lock,tree,data=self.fixture();name=next(iter(tree))
        value=b'version https://git-lfs.github.com/spec/v1\noid sha256:'+b'0'*64+b'\nsize 123\n'
        data[name]=value;item=lock['files'][0]
        item['bytes']=len(value);item['sha256']=hashlib.sha256(value).hexdigest()
        item['blob']=hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest()
        tree[name]=('100644',item['blob'],len(value))
        with self.assertRaisesRegex(ValueError,'Git LFS'):r.collect(lock,tree,data.__getitem__)
    def test_symlink_rejected(self):
        lock,tree,data=self.fixture();name=next(iter(tree));lock['files'][0]['mode']='120000';tree[name]=('120000',tree[name][1],tree[name][2])
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_catalog_collision_rejected(self):
        lock,tree,data=self.fixture(['takkernel/engine/src/main/res/raw/a.one','takkernel/shared/src/main/res/raw/a.two'])
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_unknown_types_rejected(self):
        lock,tree,data=self.fixture(['takkernel/engine/src/main/res/layout/view.xml'])
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_non_png_drawable_rejected(self):
        lock,tree,data=self.fixture(['takkernel/engine/src/main/res/drawable/vector.xml'])
        with self.assertRaises(ValueError):r.collect(lock,tree,data.__getitem__)
    def test_assembly_collision_rejected(self):
        with self.assertRaises(ValueError):r.merge({'a':b'1'},{'a':b'2'})
    def test_source_escape_rejected(self):
        for path in ['takkernel/engine/src/main/res/raw/../escape','takkernel/engine/src/main/res//raw/a','takkernel/engine/src/test/res/raw/a']:
            with self.assertRaises(ValueError):r.destination(path)

if __name__=='__main__':unittest.main()
