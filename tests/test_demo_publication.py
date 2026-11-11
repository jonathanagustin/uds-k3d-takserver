# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline publication policy/state-machine controls; no real signing or publication."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import warnings
import contextlib
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import yaml

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('publication',ROOT/'demo/publication.py')
P=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(P)
SHA='a'*40


def run(attempt=2):
    repository={'full_name':P.REPO,'id':1427088300,'owner':{'id':5193877}}
    return {'id':123,'run_attempt':attempt,'head_sha':SHA,'workflow_id':7,'path':P.WORKFLOW,
            'status':'completed','conclusion':'success','event':'workflow_dispatch','head_branch':'main',
            'repository':repository,'head_repository':copy.deepcopy(repository)}


class Fake:
    def __init__(self):self.run=run();self.output=None;self.fail_crypto=False;self.cosign_calls=[];self.commands=[]
    def api(self,path):
        if '/actions/workflows/' in path:return {'id':7,'path':P.WORKFLOW}
        return copy.deepcopy(self.run)
    def command(self,command,*args,**kwargs):
        self.commands.append(command)
        if self.fail_crypto:raise ValueError('fixed crypto failure')
        return self.output
    def cosign(self,command):self.cosign_calls.append(command)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.gh=Fake()
        environment={'DEMO_VERSION':'0.14.1','ATAK':'false','UPGRADE':'false'}
        environment.update({'DEMO_'+key.upper()+'_HOSTS':' '.join(hosts) for key,hosts in P.TARGETS.items()})
        environment_patch=patch.dict(os.environ,environment);environment_patch.start();self.addCleanup(environment_patch.stop)

    def candidate(self):
        outputs=[]
        for name in ['demo-deploy.mp4','demo-operate-and-trust.mp4','demo-clip-sso.mp4','demo-deploy.jpg']:
            (self.root/name).write_bytes(('fixture '+name).encode());outputs.append(P.info(self.root/name))
            if name.endswith('.mp4'):(self.root/(name+'.sigstore.json')).write_bytes(b'fixture cosign bundle')
        originals=[]
        for item in outputs:
            original=dict(item);original['file']={'demo-deploy.mp4':'demo.mp4','demo-operate-and-trust.mp4':'demo-operate.mp4',
                'demo-clip-sso.mp4':'clips/demo-clip-sso.mp4'}.get(item['file'],item['file']);originals.append(original)
        value={'schema':1,'capture':{'schema':1,'capture':P.identity(123,1,SHA),'applicationCommit':'b'*40,'outputs':originals,**P.capture_context()},
               'signing':P.identity(123,2,SHA),'outputs':outputs}
        (self.root/P.MANIFEST).write_text(json.dumps(value))
        subjects=[{'name':item['file'],'digest':{'sha256':item['sha256']}} for item in outputs if item['file'].endswith('.mp4')]
        subjects.append({'name':P.MANIFEST,'digest':{'sha256':P.sha(self.root/P.MANIFEST)}})
        invocation='https://github.com/'+P.REPO+'/actions/runs/123/attempts/2'
        statement={'_type':'https://in-toto.io/Statement/v1','predicateType':'https://slsa.dev/provenance/v1','subject':subjects,
            'predicate':{'buildDefinition':{'buildType':'https://actions.github.io/buildtypes/workflow/v1',
                'externalParameters':{'workflow':{'ref':P.REF,'repository':'https://github.com/'+P.REPO,'path':P.WORKFLOW}},
                'internalParameters':{'github':{'event_name':'workflow_dispatch','repository_id':'1427088300','repository_owner_id':'5193877'}},
                'resolvedDependencies':[{'uri':'git+https://github.com/'+P.REPO+'@'+P.REF,'digest':{'gitCommit':SHA}}]},
                'runDetails':{'builder':{'id':P.IDENTITY},'metadata':{'invocationId':invocation}}}}
        certificate={'issuer':'https://token.actions.githubusercontent.com','buildSignerURI':P.IDENTITY,'buildSignerDigest':SHA,
                     'sourceRepositoryDigest':SHA,'sourceRepositoryIdentifier':'1427088300','sourceRepositoryOwnerIdentifier':'5193877',
                     'runInvocationURI':invocation}
        envelope={'payloadType':'application/vnd.in-toto+json','payload':base64.b64encode(json.dumps(statement).encode()).decode(),'signatures':[]}
        (self.root/P.BUNDLE).write_text(json.dumps({'dsseEnvelope':envelope}))
        (self.root/P.INTOTO).write_text(json.dumps(envelope)+'\n')
        self.gh.output=[{'verificationResult':{'statement':statement,'signature':{'certificate':certificate}}}]
        return value

    def test_mode_never_implicitly_mutates_historical_demo(self):
        self.assertEqual(P.mode('','',False,P.REF),'record')
        self.assertEqual(P.mode('123','2',False,P.REF),'publish')
        for args in [('','',True,P.REF),('123','',False,P.REF),('demo','2',False,P.REF),('123','2',False,'refs/heads/other')]:
            with self.subTest(args=args),self.assertRaises(ValueError):P.mode(*args)
        self.assertEqual(P.tag(P.identity(123,2,SHA)),'demo-run-123-attempt-2')
        self.assertNotEqual(P.tag(P.identity(123,1,SHA)),P.tag(P.identity(123,2,SHA)))

    def test_capture_records_real_attempt_app_source_and_streamed_hashes(self):
        for name in ['demo.mp4','demo-operate.mp4']:(self.root/name).write_bytes(b'small fixture')
        env={'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA}
        with patch.dict(os.environ,env):P.capture(self.root,'b'*40)
        receipt=json.loads((self.root/'capture.json').read_text())
        self.assertEqual(receipt['capture']['attempt'],'1');self.assertEqual(receipt['applicationCommit'],'b'*40)
        P.check_inventory(self.root,receipt['outputs'],('capture.json',))
        (self.root/'unexpected').write_text('extra')
        with self.assertRaises(ValueError):P.check_inventory(self.root,receipt['outputs'],('capture.json',))

    def test_unknown_clip_extension_or_basename_rejected_before_capture_upload(self):
        for name in ('demo.mp4','demo-operate.mp4'):(self.root/name).write_bytes(b'fixture')
        (self.root/'clips').mkdir()
        for name in ('demo-clip-sso.mp4','demo-clip-sso.jpg','demo-clip-operator.txt','demo-clip-secrets.json'):
            (self.root/'clips'/name).write_bytes(b'fixture')
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA}),self.assertRaises(ValueError):P.capture(self.root,'b'*40)
        self.assertFalse((self.root/'capture.json').exists())
        (self.root/'clips/demo-clip-operator.txt').unlink();(self.root/'clips/demo-clip-secrets.json').unlink()
        unknown=self.root/'clips/demo-clip-unknown.mp4';unknown.write_bytes(b'fixture')
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA}),self.assertRaises(ValueError):P.capture(self.root,'b'*40)
        unknown.unlink()
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA}):P.capture(self.root,'b'*40)
        receipt=json.loads((self.root/'capture.json').read_text())
        names={item['file'] for item in receipt['outputs']}
        self.assertIn('clips/demo-clip-sso.mp4',names);self.assertIn('clips/demo-clip-sso.jpg',names)
        self.assertNotIn('clips/demo-clip-operator.txt',names);self.assertNotIn('clips/demo-clip-secrets.json',names)
        value=self.candidate()
        value['capture']['outputs'].append({'file':'clips/demo-clip-operator.txt','bytes':7,'sha256':'0'*64})
        (self.root/P.MANIFEST).write_text(json.dumps(value))
        with self.assertRaises(ValueError):P.manifest(self.root)

    def test_capture_version_targets_and_requested_options_are_not_success_claims(self):
        for name in ('demo.mp4','demo-operate.mp4'):(self.root/name).write_bytes(b'fixture')
        environment={'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA,'ATAK':'true','UPGRADE':'true'}
        with patch.dict(os.environ,environment):P.capture(self.root,'b'*40)
        receipt=json.loads((self.root/'capture.json').read_text())
        self.assertEqual(receipt['packageVersion'],'0.14.1');self.assertEqual(receipt['recordingTargets'],P.TARGETS)
        self.assertEqual(receipt['requested'],{'atak':True,'upgrade':True})
        self.assertEqual({item['file'] for item in receipt['outputs']},{'demo.mp4','demo-operate.mp4'})
        for key,bad in [('DEMO_VERSION','unknown'),('DEMO_PRIMARY_HOSTS','private.other.invalid'),('ATAK','yes')]:
            with patch.dict(os.environ,{**environment,key:bad}),self.subTest(key=key),self.assertRaises(ValueError):P.capture(self.root,'b'*40)
        value=self.candidate();value['capture']['recordingTargets']['primary']=['other.invalid']
        (self.root/P.MANIFEST).write_text(json.dumps(value))
        with self.assertRaises(ValueError):P.manifest(self.root)

    def test_signed_candidate_keeps_capture_attempt_distinct_from_signing(self):
        value=self.candidate();actual=P.verify_candidate(self.gh,self.root,run())
        self.assertEqual(actual,value);self.assertEqual(actual['capture']['capture']['attempt'],'1')
        self.assertEqual(actual['signing']['attempt'],'2');self.assertEqual(len(self.gh.cosign_calls),3)
        self.assertTrue(all('--bundle' in cmd and '--source-digest' in cmd for cmd in self.gh.commands))

    def test_tampered_capture_mapping_and_output_or_signature_inventory_fail(self):
        value=self.candidate();value['capture']['outputs'][0]['sha256']='0'*64
        (self.root/P.MANIFEST).write_text(json.dumps(value))
        with self.assertRaises(ValueError):P.manifest(self.root)
        self.candidate();(self.root/'demo-deploy.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):P.verify_candidate(self.gh,self.root,run())
        self.candidate();(self.root/'extra.mp4').write_bytes(b'extra')
        with self.assertRaises(ValueError):P.verify_candidate(self.gh,self.root,run())

    def test_crypto_failure_wrong_certificate_subject_and_invocation_fail_closed(self):
        self.candidate();self.gh.fail_crypto=True
        with self.assertRaises(ValueError):P.verify_candidate(self.gh,self.root,run())
        self.gh.fail_crypto=False
        baseline=copy.deepcopy(self.gh.output)
        for key in baseline[0]['verificationResult']['signature']['certificate']:
            self.gh.output=copy.deepcopy(baseline);self.gh.output[0]['verificationResult']['signature']['certificate'][key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):P.verify_candidate(self.gh,self.root,run())
        self.gh.output=copy.deepcopy(baseline);self.gh.output[0]['verificationResult']['statement']['subject'].pop()
        with self.assertRaises(ValueError):P.verify_candidate(self.gh,self.root,run())

    def test_fork_pr_failed_uncompleted_or_attempt_mismatch_source_rejected(self):
        self.assertEqual(P.run_identity(self.gh,123,2)['head_sha'],SHA)
        for key,value in [('event','pull_request'),('head_branch','branch'),('conclusion','failure'),('status','in_progress'),('run_attempt',1),('path','other')]:
            self.gh.run=run();self.gh.run[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):P.run_identity(self.gh,123,2)
        self.gh.run=run();self.gh.run['head_repository']['id']=1
        with self.assertRaises(ValueError):P.run_identity(self.gh,123,2)

    def test_asset_collisions_duplicate_unknown_unverifiable_refused(self):
        (self.root/'demo-deploy.mp4').write_bytes(b'fixture');files={'demo-deploy.mp4':P.info(self.root/'demo-deploy.mp4')}
        asset={'id':9,'name':'demo-deploy.mp4','state':'uploaded','size':7,'digest':'sha256:'+files['demo-deploy.mp4']['sha256']}
        self.gh.pages=lambda path:[[asset]]
        self.assertEqual(P.assets(self.gh,1,files),{'demo-deploy.mp4':9})
        for key,value in [('digest',None),('size',8),('name','historical.mp4'),('state','new')]:
            prior=asset[key];asset[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):P.assets(self.gh,1,files)
            asset[key]=prior
        self.gh.pages=lambda path:[[asset,asset]]
        with self.assertRaises(ValueError):P.assets(self.gh,1,files)

    def test_streamed_artifact_digest_inventory_symlink_and_size_controls(self):
        def zipped(entries):
            stream=io.BytesIO()
            with warnings.catch_warnings(),zipfile.ZipFile(stream,'w') as archive:
                warnings.simplefilter('ignore',UserWarning)
                for entry,data in entries:archive.writestr(entry,data)
            return stream.getvalue()
        blob=zipped([('fixture.mp4',b'fixture')])
        asset={'id':3,'name':'candidate','expired':False,'size_in_bytes':len(blob),'digest':'sha256:'+hashlib.sha256(blob).hexdigest(),
               'workflow_run':{'id':123,'repository_id':1427088300,'head_repository_id':1427088300,'head_branch':'main','head_sha':SHA}}
        self.gh.pages=lambda path:[{'artifacts':[asset]}]
        self.gh.command=lambda args,out,limit:out.write(blob)
        with patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()):
            P.extract(self.gh,run(),'candidate',self.root)
        self.assertEqual((self.root/'fixture.mp4').read_bytes(),b'fixture')
        # Separate fresh extraction directories for each actual malformed ZIP.
        for entries in [[('../escape',b'x')],[('same',b'x'),('same',b'y')]]:
            blob=zipped(entries);asset['size_in_bytes']=len(blob);asset['digest']='sha256:'+hashlib.sha256(blob).hexdigest()
            with tempfile.TemporaryDirectory() as temp,patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()),self.assertRaises(ValueError):
                P.extract(self.gh,run(),'candidate',temp)
        for file_type in (stat.S_IFLNK,stat.S_IFIFO,stat.S_IFSOCK,stat.S_IFCHR):
            special=zipfile.ZipInfo('special.mp4');special.create_system=3;special.external_attr=(file_type|0o777)<<16
            blob=zipped([(special,b'outside')]);asset['size_in_bytes']=len(blob);asset['digest']='sha256:'+hashlib.sha256(blob).hexdigest()
            with self.subTest(file_type=file_type),tempfile.TemporaryDirectory() as temp,patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()),self.assertRaises(ValueError):
                P.extract(self.gh,run(),'candidate',temp)
        blob=zipped([('fixture.mp4',b'fixture')]);asset['size_in_bytes']=len(blob);asset['digest']='sha256:'+hashlib.sha256(blob).hexdigest()
        with tempfile.TemporaryDirectory() as temp,patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()),patch.object(P,'FILE',4),self.assertRaises(ValueError):
            P.extract(self.gh,run(),'candidate',temp)
        with tempfile.TemporaryDirectory() as temp,patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':2*1024**3})()),self.assertRaises(ValueError):
            P.extract(self.gh,run(),'candidate',temp)
        asset['digest']='sha256:'+'0'*64
        with tempfile.TemporaryDirectory() as temp,patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()),self.assertRaises(ValueError):
            P.extract(self.gh,run(),'candidate',temp)

    def test_signer_retry_reuses_explicit_earlier_capture_and_never_relabels_it(self):
        for name in ('demo.mp4','demo-operate.mp4'):(self.root/name).write_bytes(b'capture fixture')
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':SHA}):P.capture(self.root,'b'*40)
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as zipped:
            for path in self.root.iterdir():zipped.writestr(path.name,path.read_bytes())
        blob=archive.getvalue()
        asset={'id':3,'name':'demo-video-attempt-1','expired':False,'size_in_bytes':len(blob),
            'digest':'sha256:'+hashlib.sha256(blob).hexdigest(),
            'workflow_run':{'id':123,'repository_id':1427088300,'head_repository_id':1427088300,'head_branch':'main','head_sha':SHA}}
        self.gh.run['status']='in_progress';self.gh.run['conclusion']=None
        self.gh.pages=lambda path:[{'jobs':[{'name':'record','conclusion':'success'}]}] if '/jobs?' in path else [{'artifacts':[asset]}]
        self.gh.command=lambda args,out,limit:out.write(blob)
        environment={'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'2','GITHUB_SHA':SHA,'CAPTURE_ATTEMPT':'1'}
        with tempfile.TemporaryDirectory() as destination,patch.dict(os.environ,environment),patch.object(P.shutil,'disk_usage',return_value=type('Disk',(),{'free':10*1024**3})()):
            P.prepare_sign(self.gh,destination);value=P.manifest(destination)
            self.assertEqual(value['capture']['capture']['attempt'],'1');self.assertEqual(value['signing']['attempt'],'2')
            self.assertEqual(value['capture']['applicationCommit'],'b'*40)
        environment['CAPTURE_ATTEMPT']='2'
        with tempfile.TemporaryDirectory() as destination,patch.dict(os.environ,environment),self.assertRaises(ValueError):P.prepare_sign(self.gh,destination)

    def test_partial_publication_retry_reuses_original_signed_bytes_and_public_noop(self):
        self.candidate();test=self
        class Publisher(Fake):
            def __init__(self):
                super().__init__();self.output=test.gh.output;self.release=None;self.ref=None;self.stored={};self.fail_second=True;self.uploads=0
            def api(self,path):
                if '/git/matching-refs/' in path:return []
                if '/git/ref/tags/' in path:return {'object':{'type':'commit','sha':self.ref}}
                if '/releases/tags/' in path:raise ValueError('draft tag lookup forbidden')
                if path.endswith('/releases/77'):return copy.deepcopy(self.release)
                return super().api(path)
            def pages(self,path):
                if '/assets?' in path:return [[{'id':item['id'],'name':name,'state':'uploaded','size':len(item['data']),
                      'digest':'sha256:'+hashlib.sha256(item['data']).hexdigest()} for name,item in self.stored.items()]]
                return [[self.release] if self.release else []]
            def command(self,command,output=None,limit=P.JSON_LIMIT,**kwargs):
                self.commands.append(command)
                if command[:2]==['api','--method'] and command[3].endswith('/git/refs'):
                    self.ref=SHA;return {}
                if command[:2]==['api','--method'] and command[3].endswith('/releases'):
                    self.release={'id':77,'tag_name':'demo-run-123-attempt-2','prerelease':True,'draft':True,'target_commitish':SHA};return copy.deepcopy(self.release)
                if command[:2]==['release','upload']:
                    self.uploads+=1
                    if self.fail_second and self.uploads==2:raise ValueError('simulated interrupted upload')
                    path=Path(command[3]);test.assertNotIn(path.name,self.stored)
                    self.stored[path.name]={'id':100+len(self.stored),'data':path.read_bytes()};return b''
                if command[:3]==['api','--method','PATCH']:
                    test.assertEqual(command[3],'repos/'+P.REPO+'/releases/77')
                    test.assertIn('draft=false',command);test.assertIn('make_latest=false',command)
                    self.release['draft']=False;return copy.deepcopy(self.release)
                if command[0]=='api' and '/releases/assets/' in command[1]:
                    asset_id=int(command[1].split('/')[-1]);data=next(item['data'] for item in self.stored.values() if item['id']==asset_id)
                    output.write(data);output.flush();return None
                return self.output
        gh=Publisher()
        def extract(_gh,_run,name,destination):
            test.assertEqual(name,'demo-signed-attempt-2')
            for path in self.root.iterdir():shutil.copyfile(path,Path(destination)/path.name)
        with patch.object(P,'extract',side_effect=extract),patch.dict(os.environ,{'GITHUB_REF':P.REF}):
            with tempfile.TemporaryDirectory() as destination,self.assertRaises(ValueError):P.publish(gh,'123','2',destination)
            self.assertEqual(len(gh.stored),1);self.assertTrue(gh.release['draft'])
            saved=copy.deepcopy(gh.stored);gh.fail_second=False
            with tempfile.TemporaryDirectory() as destination:P.publish(gh,'123','2',destination)
            self.assertFalse(gh.release['draft'])
            self.assertEqual(gh.stored[next(iter(saved))],saved[next(iter(saved))])
            upload_count=gh.uploads
            with tempfile.TemporaryDirectory() as destination:P.publish(gh,'123','2',destination)
            self.assertEqual(gh.uploads,upload_count)
        self.assertTrue(all('--clobber' not in command for command in gh.commands))
        self.assertFalse(any('sign-blob' in command or 'assemble.sh' in command for command in gh.commands))
        self.assertEqual(set(gh.stored),{path.name for path in self.root.iterdir()})
        promotions=[command for command in gh.commands if command[:3]==['api','--method','PATCH']]
        self.assertEqual(len(promotions),1)
        self.assertEqual(promotions[0][3],'repos/'+P.REPO+'/releases/77')
        self.assertFalse(any(command[:2]==['release','edit'] for command in gh.commands))

    def test_real_subprocess_failure_never_exposes_private_child_output(self):
        binary=self.root/'gh'
        binary.write_text('#!'+sys.executable+'\nimport sys\nprint("PRIVATE_STDOUT")\nprint("https://download.invalid/file?sig=PRIVATE_TOKEN",file=sys.stderr)\nraise SystemExit(1)\n')
        binary.chmod(0o755)
        output,error=io.StringIO(),io.StringIO()
        with patch.dict(os.environ,{'PATH':str(self.root)+os.pathsep+os.environ['PATH']}),contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
            with self.assertRaisesRegex(ValueError,'policy rejected'):P.GitHub().command(['api','fixture'])
        self.assertEqual(output.getvalue(),'');self.assertEqual(error.getvalue(),'')

    def test_workflow_privileges_modes_artifacts_and_publication_are_separate(self):
        workflow=yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(),Loader=yaml.BaseLoader)
        self.assertNotIn('concurrency',workflow)
        jobs=workflow['jobs']
        self.assertEqual(jobs['record']['concurrency'],{'group':'demo-capture-main','queue':'max','cancel-in-progress':'false'})
        self.assertEqual(jobs['preflight']['concurrency'],{'group':'demo-preflight-${{ github.event.pull_request.number }}','cancel-in-progress':'true'})
        for name,hosts in P.TARGETS.items():
            self.assertEqual(jobs['record']['env']['DEMO_'+name.upper()+'_HOSTS'],' '.join(hosts))
        web_commands='\n'.join(step.get('run','') for step in jobs['record']['steps'])
        self.assertIn('./demo/record-web.sh 06-web tour.demo.ts "${DEMO_PRIMARY_HOSTS}"',web_commands)
        for variable in ('DEMO_CLOUDTAK_HOSTS','DEMO_ATAK_HOSTS','DEMO_SYNC_HOSTS'):
            self.assertIn('"${'+variable+'}"',web_commands)
        for name in ('record','preflight','mode'):
            self.assertNotIn('write',jobs[name]['permissions'].values())
        self.assertEqual(jobs['sign']['permissions']['contents'],'read')
        record_steps=jobs['record']['steps']
        upload=next(step for step in record_steps if step['name']=='Upload the demo video')
        clip_paths={path.strip() for path in upload['with']['path'].splitlines() if '/clips/' in path}
        self.assertEqual(clip_paths,{'demo/out/'+name for name in P.CLIP_FILES})
        self.assertEqual(set(P.CLIPS),set(re.findall(r'^chapter ([a-z0-9-]+) ',(ROOT/'demo/assemble.sh').read_text(),re.M)))
        self.assertLess(next(i for i,step in enumerate(record_steps) if step['name']=='Bind the actual capture source and attempt'),record_steps.index(upload))
        self.assertNotIn('id-token',jobs['publish']['permissions'])
        self.assertEqual(jobs['publish']['concurrency'],{'group':'immutable-demo-publication','queue':'max','cancel-in-progress':'false'})
        self.assertIn("needs.mode.outputs.mode == 'publish'",jobs['publish']['if'])
        self.assertIn("github.ref == 'refs/heads/main'",jobs['sign']['if'])
        publish=str(jobs['publish']['steps']);self.assertNotIn('sign-blob',publish);self.assertNotIn('assemble.sh',publish)
        self.assertNotIn('--clobber',(ROOT/'demo/publication.py').read_text())
        self.assertNotIn('release upload demo ',(ROOT/'.github/workflows/demo.yaml').read_text())
        units=(ROOT/'.github/workflows/unit-tests.yaml').read_text()
        self.assertIn('tests.test_demo_publication',units)
        sign_steps={step['name']:step for step in jobs['sign']['steps']}
        self.assertEqual(sign_steps['Validate and stage the existing capture']['env']['CAPTURE_ATTEMPT'],
                         '${{ needs.record.outputs.capture-attempt }}')


if __name__=='__main__':unittest.main()
