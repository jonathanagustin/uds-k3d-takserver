# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Real offline Git/blob construction, not native or historical Python execution."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('source_materializer',Path(__file__).with_name('materialize_native_source_bundle.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MaterializerTests(unittest.TestCase):
    def fixture(self,root,derived):
        repo=root/'repo';repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)],check=True,capture_output=True)
        prefix=b'# exact fixture notice\n' if derived else b''
        body=b'raise RuntimeError("NEVER EXECUTE THIS HISTORICAL SOURCE")\n'
        relative='takx/kernel-native/build.py';path=repo/relative;path.parent.mkdir(parents=True);path.write_bytes(prefix+body)
        subprocess.run(['git','-C',str(repo),'add','.'],check=True,capture_output=True)
        subprocess.run(['git','-c','user.name=Offline Fixture','-c','user.email=fixture@example.invalid','-C',str(repo),'commit','-qm','source fixture'],check=True,capture_output=True)
        commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        blob=subprocess.check_output(['git','-C',str(repo),'rev-parse',commit+':'+relative],text=True).strip()
        origin={'kind':'exact-license-prefix-preimage' if derived else 'git-blob','commit':commit,'repositoryPath':relative,'blobOID':blob,'blobSHA256':m.sha(prefix+body)}
        if derived:origin.update(removedPrefixUTF8=prefix.decode(),removedPrefixSHA256=m.sha(prefix))
        recipe={'build.py':m.sha(body)};recipe_bytes=(json.dumps(recipe,sort_keys=True,indent=2)+'\n').encode()
        recipe_sha=m.sha(json.dumps(recipe,sort_keys=True,separators=(',',':')).encode())
        manifest={'schema':1,'profile':'fixture','gitSourceCommit':commit,'sourceCount':1,'nativeRecipeSHA256':recipe_sha,
                  'files':[{'snapshotPath':'source/'+relative,'repositoryPath':relative,'receiptRecipePath':'build.py','sha256':m.sha(body),'bytes':len(body),'origin':origin}],
                  'recipeFile':{'path':'recipe.json','bytes':len(recipe_bytes),'sha256':m.sha(recipe_bytes)}}
        manifest_path=root/'manifest.json';manifest_path.write_text(json.dumps(manifest))
        known={m.sha(manifest_path.read_bytes()):{'profile':'fixture','git_source_commit':commit,'source_count':1,'native_recipe_sha256':recipe_sha}}
        return repo,manifest_path,known,body

    def test_real_git_blobs_and_exact_prefix_preimages_construct_identically(self):
        for derived in (False,True):
            with self.subTest(derived=derived),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);repo,manifest,known,body=self.fixture(root,derived)
                out=root/'bundle';record=m.materialize(repo,out,manifest,known)
                self.assertEqual((out/'source/takx/kernel-native/build.py').read_bytes(),body)
                self.assertEqual((out/'manifest.json').read_bytes(),manifest.read_bytes())
                self.assertFalse(record['historical_code_executed'])
                self.assertTrue(all(not p.stat().st_mode & (0o222 if p.is_dir() else 0o333) for p in [out,*out.rglob('*')]))
                with self.assertRaises(ValueError):m.materialize(repo,out,manifest,known)

    def test_unreviewed_manifest_rejected_before_git_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo,manifest,known,body=self.fixture(root,False)
            with self.assertRaisesRegex(ValueError,'consumer-reviewed'):m.materialize(repo,root/'out',manifest,{})
            self.assertFalse((root/'out').exists())

if __name__=='__main__':unittest.main()
