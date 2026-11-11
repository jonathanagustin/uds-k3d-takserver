#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline policy/protocol fixtures; none claims a real fresh native build."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parent))
import draco as local
import fresh
import producer
import transport


def identity():
    tools = {n: {'path': '/test/'+n, 'sha256':'1'*64, 'version':'test-fixture'} for n in
             ('gcc','g++','cc1','cc1plus','as','ld','ar','ranlib','make','cmake','python3','readelf')}
    return {'schema':'uds-draco-inputs-v2','base_image':producer.LOCK['image'],
            'base_image_config':producer.LOCK['image_config'], 'source':producer.LOCK['source'],
            'source_inventory_sha256':'1'*64,'dependency_digests':[],'patches':[],
            'configure_command':['test-fixture'], 'environment':{'PATH':producer.PATH,'LANG':'C','LC_ALL':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'1704067200'},
            'compile_commands':[{'command':'test -std=gnu++11 -fPIC'}], 'recipes':{'test':'1'*64}, 'tools':tools,
            'abi':{'target':'x86_64-linux-gnu','pointer_bytes':'8','byte_order':'__ORDER_LITTLE_ENDIAN__',
                   'cxx11_abi':'1','exceptions':'1','rtti':'1','glibc':'2.36','cxx_standard':'201103L',
                   'providers':{'/test/libc.so.6':'1'*64}}}


class FreshGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {'GITHUB_REPOSITORY':transport.REPO,'GITHUB_REF':'refs/heads/main',
                    'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123'}

    def tearDown(self): self.tmp.cleanup()

    def capsule(self):
        prefix = self.root / 'prefix'; prefix.mkdir()
        for name in local.FIXED:
            p = prefix / name.removeprefix('prefix/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
        for i in range(201):
            p = prefix / f'include/draco/header{i}.h';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
        q = {'fresh_source_build':True,'codec':True,'pic':True,'object_count':1,
             'archive_object_sha256':'1'*64,'runtime_providers':{'/test/libc.so.6':'1'*64}}
        capsule = self.root / 'fixture.tar.gz';fresh.pack(prefix,identity(),q,capsule)
        return capsule,local.file_sha(capsule),fresh.key(identity())

    def test_fresh_key_requires_complete_known_base_tools_and_abi(self):
        original = identity(); k = fresh.key(original)
        for field in ('tools','abi','recipes','compile_commands'):
            changed = copy.deepcopy(original);changed[field] = {}
            with self.subTest(field=field),self.assertRaises(ValueError):fresh.key(changed)
        for field in ('base_image','source','schema'):
            changed = copy.deepcopy(original);changed[field] = 'old-local-receipt'
            with self.subTest(field=field),self.assertRaises(ValueError):fresh.key(changed)
        changed = copy.deepcopy(original);changed['tools']['cc1plus']['sha256']='2'*64
        self.assertNotEqual(k,fresh.key(changed))
        changed = copy.deepcopy(original);changed['compile_commands'][0]['command'] += ' -O1'
        self.assertNotEqual(k,fresh.key(changed))

    def test_fixture_capsule_and_oci_layout_bind_exact_bytes_and_media(self):
        capsule,sha,key = self.capsule()
        restored = self.root / 'restore';m = fresh.restore(capsule,sha,key,restored)
        self.assertEqual(len(m['files']),207)
        with self.assertRaises(ValueError):fresh.restore(capsule,sha,key,restored)
        layout = self.root / 'layout';digest = fresh.layout(capsule,sha,key,layout)
        raw = (layout/'blobs/sha256'/digest.split(':')[1]).read_bytes()
        self.assertEqual('sha256:'+local.sha(raw),digest)
        oci = json.loads(raw);transport.expected_oci(oci,digest,sha,key)
        for blob in [oci['config'],*oci['layers']]:
            data=(layout/'blobs/sha256'/blob['digest'].split(':')[1]).read_bytes()
            self.assertEqual(len(data),blob['size']);self.assertEqual(local.sha(data),blob['digest'].split(':')[1])
        oci['layers'][0]['mediaType']='application/x-untrusted'
        with self.assertRaises(ValueError):transport.expected_oci(oci,digest,sha,key)

    def test_fresh_capsule_rejects_wrong_digest_key_and_injected_private_payload(self):
        capsule,sha,key = self.capsule()
        with self.assertRaises(ValueError):fresh.verify(capsule,'0'*64,key)
        with self.assertRaises(ValueError):fresh.verify(capsule,sha,'local-v1-'+'0'*64)
        altered = self.root/'injected.tar.gz'
        with tarfile.open(capsule,'r:gz') as original,tarfile.open(altered,'w:gz') as target:
            for member in original:target.addfile(member,original.extractfile(member))
            m=tarfile.TarInfo('prefix/credentials.key');m.mode=0o644;m.size=1;target.addfile(m,io.BytesIO(b'x'))
        with self.assertRaises(ValueError):fresh.verify(altered,local.file_sha(altered),key)

    def test_manual_writer_rejects_pr_fork_branch_or_arbitrary_source(self):
        self.assertEqual(transport.context(self.env),('a'*40,'123'))
        for field,value in [('GITHUB_REPOSITORY','fork/repo'),('GITHUB_EVENT_NAME','pull_request'),
                            ('GITHUB_REF','refs/heads/feature'),('GITHUB_SHA','main'),('GITHUB_RUN_ID','unsafe')]:
            env={**self.env,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):transport.context(env)

    def test_verified_predicate_needs_expected_subject_type_and_claim(self):
        q={'claim':'exact'};digest='sha256:'+'a'*64
        statement={'predicateType':fresh.PREDICATE,'subject':[{'digest':{'sha256':'a'*64}}],'predicate':q}
        data=[{'verificationResult':{'statement':statement}}]
        transport.verified_statements(data,fresh.PREDICATE,q,digest)
        for kind,expected,subject in [(fresh.PREDICATE,{'claim':'changed'},digest),
                                      ('unexpected',q,digest),(fresh.PREDICATE,q,'sha256:'+'b'*64)]:
            with self.assertRaises(ValueError):transport.verified_statements(data,kind,expected,subject)

    def test_untrusted_attestation_prevents_fetch_and_native_execution(self):
        q={'subject_digest':'sha256:'+'a'*64}
        with patch.object(transport,'verify_attestations',side_effect=ValueError('untrusted')),patch.object(transport,'command') as command:
            with self.assertRaises(ValueError):transport.readback(q,self.root/'readback','a'*40)
            command.assert_not_called()

    def test_gh_policy_uses_api_current_repo_exact_workflow_source_and_hosted_runner(self):
        q={'source_commit':'a'*40,'repository':transport.REPO,'workflow':transport.WORKFLOW,'subject_digest':'sha256:'+'b'*64}
        calls=[]
        def command(args,*unused):
            calls.append(args);kind=args[args.index('--predicate-type')+1]
            return local.canonical([{'verificationResult':{'statement':{'predicateType':kind,
                'subject':[{'digest':{'sha256':'b'*64}}],'predicate':q}}}])
        with patch.dict(os.environ,self.env,clear=True),patch.object(transport,'command',side_effect=command):
            transport.verify_attestations(q,self.root,{},'a'*40)
        self.assertEqual(len(calls),2)
        for args in calls:
            self.assertIn('--deny-self-hosted-runners',args)
            self.assertEqual(args[args.index('--source-ref')+1],'refs/heads/main')
            self.assertEqual(args[args.index('--source-digest')+1],'a'*40)
            self.assertNotIn('--bundle',args);self.assertNotIn('--bundle-from-oci',args)

    def test_consumer_receipt_cannot_credit_a_different_capsule_with_same_key(self):
        q={'input_key':'same-key','capsule_sha256':'a'*64,'identity':identity()}
        receipt={'schema':'uds-draco-registry-consumer-v2','input_key':'same-key','capsule_sha256':'a'*64,
                 'identity_sha256':local.sha(local.canonical(q['identity'])),
                 'results':[{'codec':True,'pic':True},{'codec':True,'pic':True}]}
        transport.validate_consumer(receipt,q)
        for name,value in [('capsule_sha256','b'*64),('identity_sha256','b'*64),('input_key','other-key')]:
            changed={**receipt,name:value}
            with self.subTest(field=name),self.assertRaises(ValueError):transport.validate_consumer(changed,q)

    def test_low_space_vfs_stops_before_pull_or_download(self):
        usage=type('Usage',(),{'free':11*1024**3})()
        with patch.object(producer,'docker',return_value=b'vfs\n') as docker,patch.object(producer.shutil,'disk_usage',return_value=usage),patch.object(producer,'acquire_tools') as acquire:
            with self.assertRaisesRegex(ValueError,'no pull attempted'):
                producer.prepare(self.root/'source',self.root/'output',self.root/'cache')
            acquire.assert_not_called();self.assertEqual(docker.call_count,1)

    def test_native_command_deadline_survives_closed_streams(self):
        with self.assertRaisesRegex(ValueError,'bound'):
            producer.run([sys.executable,'-c','import os,time;os.close(1);os.close(2);time.sleep(10)'],self.root,'closed-stream',0.3)

    def test_live_disk_quota_stops_owned_command(self):
        code='import pathlib,time;pathlib.Path('+repr(str(self.root/'overflow'))+').write_bytes(b"x"*512);time.sleep(10)'
        with patch.object(producer,'MAX_OUTPUT',128),self.assertRaisesRegex(ValueError,'owned output'):
            producer.run([sys.executable,'-c',code],self.root,'disk-quota',2)

    def test_manual_workflow_has_no_automatic_writer_or_build_write_grant(self):
        document=yaml.safe_load((local.ROOT/'.github/workflows/native-cache.yaml').read_text())
        self.assertEqual(set(document.get('on',document.get(True))),{'workflow_dispatch'})
        self.assertEqual(document['permissions'],{'contents':'read'})
        build=document['jobs']['build'];publish=document['jobs']['publish']
        self.assertNotIn('permissions',build)
        self.assertEqual(build['timeout-minutes']+publish['timeout-minutes'],20)
        self.assertEqual(publish['needs'],'build')
        self.assertIn('inputs.publish',publish['if'])
        self.assertEqual(publish['permissions'],{'contents':'read','packages':'write','id-token':'write','attestations':'write'})
        self.assertFalse(any(str(s.get('uses','')).startswith('actions/attest@') for s in build['steps']))
        self.assertEqual([s['name'] for s in publish['steps']][-4:-1],
                         ['Authenticate and read back without registry credentials','Qualify the fetched capsule at two new prefixes','Promote only the verified subject'])


if __name__=='__main__':unittest.main()
