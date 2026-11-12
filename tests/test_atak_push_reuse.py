# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise decision policy with authenticated API-shaped fixtures, not live CI."""
import copy
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('push_reuse', ROOT/'atak/ci/push-reuse.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SHA, BEFORE, HEAD, TREE, CHECKOUT = [c*40 for c in 'abcde']


class Admission(unittest.TestCase):
    def setUp(self):
        self.pr = {'number': 42, 'merged_at': 'now', 'merge_commit_sha': SHA, 'base': {'ref': 'main', 'repo': {'full_name': m.REPO}}, 'head': {'sha': HEAD, 'repo': {'full_name': m.REPO}}}
        self.run = {'id': 12, 'run_attempt': 2, 'head_sha': HEAD, 'event': 'pull_request', 'path': m.WORKFLOW, 'repository': {'full_name': m.REPO}, 'head_repository': {'full_name': m.REPO}, 'pull_requests': [{'number':42}], 'status': 'completed', 'conclusion': 'success'}
        names = ['Deploy UDS Core slim and TAK Server', 'ATAK device end to end', 'Record the tested checkout and scenario', 'Upload the tested checkout proof']
        self.job = {'name':'e2e','status':'completed','conclusion':'success','steps':[{'name':n,'status':'completed','conclusion':'success'} for n in names]}
        self.proof = {'schema':m.SCHEMA,'repository':m.REPO,'runId':12,'runAttempt':2,'event':'pull_request','pr':42,'sourceHead':HEAD,'checkoutCommit':CHECKOUT,'checkoutTree':TREE,'keys':{'x':'y'},'scenarioStatus':m.STATUS,'phases':m.PHASES,'cleanupVerified':True}
        self.env = {'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/main','GITHUB_REPOSITORY':m.REPO,'RELEASE_TAG':'5.5.1.10','UDS_VERSION':'v0.41.0'}
    def api(self,path):
        if path.startswith('commits/'): return [self.pr]
        if path.startswith('actions/workflows/'): return {'total_count':1,'workflow_runs':[self.run]}
        if path.startswith('actions/runs/'): return {'total_count':1,'jobs':[self.job]}
        if path.startswith('git/commits/'): return {'tree':{'sha':TREE}}
        raise AssertionError(path)
    def git(self,*args):
        if args == ('rev-parse','HEAD'): return SHA
        if args == ('rev-parse','HEAD^1'): return BEFORE
        if args == ('rev-parse','HEAD^{tree}'): return TREE
        if args[0]=='ls-tree': return 'stable producer semantics'
        raise AssertionError(args)
    def decide(self, event=None):
        with patch.dict(os.environ,self.env),patch.object(m,'api',side_effect=self.api),patch.object(m,'git',side_effect=self.git),patch.object(m,'keys',return_value={'x':'y'}),patch.object(m,'read_artifact',return_value=self.proof),patch.object(m,'release_current') as registry:
            result=m.decide(event or {'after':SHA,'before':BEFORE,'forced':False})
            return result,registry.called
    def test_exact_tested_tree_and_completed_scenario_reuse(self):
        self.assertEqual(self.decide(),(True,True))
        self.assertNotEqual(self.proof['checkoutCommit'],self.run['head_sha'])
    def test_pr_manual_wrongrepo_wrongref_are_full_without_registry(self):
        for field,value in [('GITHUB_EVENT_NAME','pull_request'),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REPOSITORY','fork/repo'),('GITHUB_REF','refs/heads/dev')]:
            with self.subTest(field=field,value=value):
                old=self.env[field];self.env[field]=value;self.assertEqual(self.decide(),(False,False));self.env[field]=old
    def test_failed_queued_or_old_attempt_baseline_cannot_reuse(self):
        for field,value in [('status','queued'),('conclusion','failure'),('run_attempt',3),('head_sha',BEFORE),('path','other.yaml')]:
            old=self.run[field];self.run[field]=value
            try:
                with self.subTest(field=field):
                    try:result=self.decide()[0]
                    except ValueError:result=False
                    self.assertFalse(result)
            finally:self.run[field]=old
    def test_missing_skipped_failed_or_duplicate_actual_step_full(self):
        for status in ['skipped','failure']:
            self.job['steps'][1]['conclusion']=status;self.assertEqual(self.decide(),(False,False))
        self.job['steps'][1]['conclusion']='success';self.job['steps'].append(copy.deepcopy(self.job['steps'][1]));self.assertFalse(self.decide()[0])
    def test_different_checkout_tree_head_keys_and_cleanup_reject(self):
        for field,value in [('checkoutTree',BEFORE),('sourceHead',BEFORE),('keys',{}),('cleanupVerified',False),('phases',[])]:
            p=copy.deepcopy(self.proof);p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate_proof(p,self.run,self.pr,TREE,{'x':'y'})
    def test_producer_changes_and_artifact_keys_before_after_full(self):
        with patch.object(self,'git',side_effect=lambda *a: 'before' if BEFORE in a else ('after' if a[0]=='ls-tree' else SHA)):
            self.assertFalse(self.decide()[0])
        with patch.object(m,'keys',side_effect=[{'x':'y'},{'x':'z'}]),patch.dict(os.environ,self.env),patch.object(m,'api',side_effect=self.api),patch.object(m,'git',side_effect=self.git):
            self.assertFalse(m.decide({'after':SHA,'before':BEFORE,'forced':False}))
    def test_direct_push_or_ambiguous_pr_full(self):
        self.assertFalse(self.decide({'after':SHA,'before':BEFORE,'forced':True})[0])
        self.pr['merge_commit_sha']=BEFORE;self.assertFalse(self.decide()[0])
    def test_registry_check_is_readonly_and_requires_exact_digests(self):
        identity={f: 'ghcr.io/'+m.REPO+'/'+n+':5.5.1.10-'+'a'*12 for f,n in [('APK_IMAGE_KEYED','atak-civ-apk'),('DRIVER_IMAGE_KEYED','atak-driver'),('VM_IMAGE_KEYED','atak-civ-vm'),('VIEWER_IMAGE_KEYED','atak-viewer')]}
        identity['PKG_REF']='ghcr.io/'+m.REPO+'/packages/atak-device:5.5.1.10-'+'b'*12
        with patch.object(m,'command',return_value=('sha256:'+'c'*64+'\n').encode()) as cmd:
            m.release_current(identity,'5.5.1.10')
            self.assertEqual(cmd.call_count,9)
            self.assertTrue(all(c.args[0][:5]==['uds','zarf','tools','registry','digest'] for c in cmd.call_args_list))
        with patch.object(m,'command',side_effect=[('sha256:'+'c'*64).encode(),('sha256:'+'c'*64).encode(),('sha256:'+'d'*64).encode()]),self.assertRaises(ValueError):m.release_current(identity,'5.5.1.10')
    def test_gate_only_diff_preserves_original_image_and_package_keys(self):
        # Execute the genuine identity script with complete git index at both
        # revisions, regardless of this lightweight sparse working tree.
        self.assertEqual(hashlib.sha256((ROOT/'atak/ci/device-images.sh').read_bytes()).hexdigest(), 'b8ad0327bbb49fa8615e112dbbb52d7c31539cfa252ea4a084036f45dd1278b3')
        with tempfile.TemporaryDirectory() as d:
            env=os.environ.copy();env['UDS_VERSION']='v0.41.0';env['ATAK_VERSION']='5.5.1.10';env['GIT_INDEX_FILE']=d+'/index'
            subprocess.run(['git','read-tree','HEAD'],cwd=ROOT,env=env,check=True)
            before=subprocess.check_output(['bash','atak/ci/device-images.sh','keys'],cwd=ROOT,env=env)
            subprocess.run(['git','update-index','--force-remove','atak/ci/push-reuse.py','.github/workflows/atak-e2e.yaml','.github/workflows/unit-tests.yaml','tests/test_atak_push_reuse.py','atak/scenarios/README.md'],cwd=ROOT,env=env,check=True)
            after=subprocess.check_output(['bash','atak/ci/device-images.sh','keys'],cwd=ROOT,env=env)
            self.assertEqual(before,after)

class ArtifactAndWorkflow(unittest.TestCase):
    def archive(self, names=('tested-checkout.json',)):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name in names:z.writestr(name,'{}')
        return stream.getvalue()
    def test_exact_digest_bounded_single_file_archive(self):
        raw=self.archive();meta={'total_count':1,'artifacts':[{'id':3,'name':m.ARTIFACT,'expired':False,'size_in_bytes':len(raw),'workflow_run':{'id':12},'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}]}
        with patch.object(m,'api',return_value=meta),patch.object(m,'command',return_value=raw):self.assertEqual(m.read_artifact({'id':12}),{})
        for field,value in [('expired',True),('digest','sha256:'+'0'*64),('size_in_bytes',16385),('workflow_run',{'id':13})]:
            changed=copy.deepcopy(meta);changed['artifacts'][0][field]=value
            with self.subTest(field=field),patch.object(m,'api',return_value=changed),patch.object(m,'command',return_value=raw),self.assertRaises(ValueError):m.read_artifact({'id':12})
        for names in [('other.json',),('tested-checkout.json','extra.json')]:
            raw=self.archive(names);meta['artifacts'][0]['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
            with patch.object(m,'api',return_value=meta),patch.object(m,'command',return_value=raw),self.assertRaises(ValueError):m.read_artifact({'id':12})
    def test_admission_exception_outputs_full_without_raw_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'event').write_text('{}')
            with patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(p/'event'),'GITHUB_OUTPUT':str(p/'output')}),patch('sys.argv',['reuse','admit']),patch.object(m,'decide',side_effect=ValueError('secret-sensitive-network-error')),patch('sys.stdout',new_callable=io.StringIO) as out:
                m.main();self.assertEqual((p/'output').read_text(),'reuse=false\n');self.assertNotIn('sensitive',out.getvalue())
    def test_workflow_readonly_gate_and_fallback_dependency_contract(self):
        import yaml
        jobs=yaml.safe_load((ROOT/'.github/workflows/atak-e2e.yaml').read_text())['jobs']
        self.assertTrue(all(v=='read' for v in jobs['admission']['permissions'].values()))
        self.assertNotIn('packages: write',str(jobs['admission']))
        for name in ['images','e2e']:
            self.assertEqual(jobs[name]['needs'],'admission');self.assertIn('!cancelled()',jobs[name]['if']);self.assertIn("outputs.reuse != 'true'",jobs[name]['if'])
        self.assertEqual(jobs['e2e']['permissions']['packages'],'write')

if __name__=='__main__':unittest.main()
