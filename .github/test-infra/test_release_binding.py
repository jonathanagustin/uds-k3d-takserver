# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline policy controls; no cryptographic or publication success is simulated."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('binding', Path(__file__).with_name('release-binding.py'))
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.index = {'schemaVersion': 2, 'mediaType': B.INDEX_TYPE, 'manifests': [
            {'mediaType': B.MANIFEST_TYPE, 'digest': 'sha256:'+letter*64, 'size': 32306,
             'platform': {'architecture': arch, 'os': 'multi'}}
            for arch, letter in [('amd64', 'a'), ('arm64', 'b')]]}
        self.metadata = {'repository': B.REPO,
            'release': {'tag': 'v0.14.0', 'id': '123', 'applicationCommit': '1'*40},
            'workflow': {'commit': '2'*40, 'runID': '456', 'runAttempt': '1', 'ref': 'refs/heads/main'},
            'indexDigest': ''}
        self.bind()

    def bind(self):
        self.raw = json.dumps(self.index).encode()
        self.metadata['indexDigest'] = 'sha256:'+hashlib.sha256(self.raw).hexdigest()

    def output(self):
        w = self.metadata['workflow'];identity = B.WORKFLOW+'@'+w['ref']
        # Field names match the actual verified 0.13 recovery specimen.
        cert = {'issuer': 'https://token.actions.githubusercontent.com',
            'subjectAlternativeName': identity, 'buildSignerURI': identity,
            'buildSignerDigest': w['commit'], 'sourceRepositoryURI': B.REPOSITORY,
            'sourceRepositoryDigest': w['commit'], 'sourceRepositoryIdentifier': '1427088300',
            'sourceRepositoryOwnerIdentifier': '5193877',
            'runInvocationURI': B.REPOSITORY+'/actions/runs/456/attempts/1'}
        return [{'verificationResult': {'signature': {'certificate': cert},
            'verifiedTimestamps': [{'type': 'transparency-log'}], 'statement': {
                '_type': 'https://in-toto.io/Statement/v1', 'predicateType': B.PREDICATE,
                'subject': [{'name': B.SUBJECT, 'digest': {'sha256': self.metadata['indexDigest'][7:]}}],
                'predicate': B.predicate(self.metadata, self.raw)}}}]

    def test_recovery_distinguishes_application_from_certified_workflow(self):
        B.verify_verified_output(self.output(), self.metadata, self.raw)
        self.assertNotEqual(self.metadata['release']['applicationCommit'], self.metadata['workflow']['commit'])

    def test_ordinary_tag_caller_and_public_backfill_are_read_only(self):
        self.metadata['workflow']['commit'] = self.metadata['release']['applicationCommit']
        self.metadata['workflow']['ref'] = 'refs/tags/v0.14.0'
        B.verify_verified_output(self.output(), self.metadata, self.raw)
        # Draft/public state is checked upstream; neither policy path mutates it.
        self.assertNotIn('draft', B.predicate(self.metadata, self.raw)['release'])

    def test_partial_invalid_or_unknown_identity_rejected(self):
        for section, key, bad in [('release','id',''), ('release','tag','v1.2'),
                ('release','applicationCommit','x'*40), ('workflow','runAttempt','0'),
                ('workflow','ref','refs/heads/untrusted')]:
            changed = copy.deepcopy(self.metadata);changed[section][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):B.predicate(changed,self.raw)
        changed = copy.deepcopy(self.metadata);changed['unchecked'] = True
        with self.assertRaises(ValueError):B.predicate(changed,self.raw)

    def test_changed_tag_source_release_id_and_arch_binding_rejected(self):
        output = self.output()
        for section,key,value in [('release','id','124'),('release','tag','v0.15.0'),
                ('release','applicationCommit','3'*40),('workflow','commit','4'*40),
                ('workflow','runAttempt','2')]:
            changed = copy.deepcopy(self.metadata);changed[section][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):B.verify_verified_output(output,changed,self.raw)
        self.index['manifests'][0]['digest']='sha256:'+'c'*64;self.bind()
        with self.assertRaises(ValueError):B.verify_verified_output(output,self.metadata,self.raw)

    def test_missing_duplicate_unknown_architecture_and_unknown_fields_rejected(self):
        original=copy.deepcopy(self.index)
        for manifests in [original['manifests'][:1], original['manifests']*2,
                original['manifests']+[{'unexpected':True}]]:
            self.index['manifests']=manifests;self.bind()
            with self.assertRaises(ValueError):B.predicate(self.metadata,self.raw)
        self.index=original;self.index['manifests'][1]['platform']['architecture']='riscv64';self.bind()
        with self.assertRaises(ValueError):B.predicate(self.metadata,self.raw)

    def test_only_explicit_typed_attestation_for_known_architecture_allowed(self):
        extra={'mediaType':B.MANIFEST_TYPE,'digest':'sha256:'+'c'*64,'size':123,
            'platform':{'architecture':'unknown','os':'unknown'},
            'annotations':{'vnd.docker.reference.type':'attestation-manifest',
                           'vnd.docker.reference.digest':'sha256:'+'a'*64}}
        self.index['manifests'].append(extra);self.bind()
        self.assertEqual(len(B.predicate(self.metadata,self.raw)['architectures']),2)
        for key,bad in [('vnd.docker.reference.type','other'),('vnd.docker.reference.digest','sha256:'+'d'*64)]:
            old=extra['annotations'][key];extra['annotations'][key]=bad;self.bind()
            with self.assertRaises(ValueError):B.predicate(self.metadata,self.raw)
            extra['annotations'][key]=old

    def test_exact_raw_index_digest_and_duplicate_json_keys(self):
        with self.assertRaises(ValueError):B.predicate(self.metadata,self.raw+b'\n')
        with self.assertRaises(ValueError):B.decode(b'{"id":1,"id":2}')
        with self.assertRaises(ValueError):B.decode(b' '* (B.LIMIT+1))

    def test_certificate_subject_schema_issuer_and_signer_controls(self):
        baseline=self.output()
        cert=baseline[0]['verificationResult']['signature']['certificate']
        for key in cert:
            changed=copy.deepcopy(baseline);changed[0]['verificationResult']['signature']['certificate'][key]='wrong'
            with self.subTest(key=key),self.assertRaises(ValueError):B.verify_verified_output(changed,self.metadata,self.raw)
        for key,value in [('predicateType','wrong'),('_type','wrong'),('subject',[]),('predicate',{})]:
            changed=copy.deepcopy(baseline);changed[0]['verificationResult']['statement'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):B.verify_verified_output(changed,self.metadata,self.raw)
        changed=copy.deepcopy(baseline)
        changed[0]['verificationResult']['statement']['predicate']['schemaVersion']=True
        with self.assertRaises(ValueError):B.verify_verified_output(changed,self.metadata,self.raw)
        for output in [[],baseline*2]:
            with self.assertRaises(ValueError):B.verify_verified_output(output,self.metadata,self.raw)

    def test_cli_generate_and_safe_invalid_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);meta=root/'metadata.json';index=root/'index.json'
            meta.write_text(json.dumps(self.metadata));index.write_bytes(self.raw)
            command=[sys.executable,str(Path(B.__file__)),'generate','--metadata',str(meta),'--index',str(index)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout),B.predicate(self.metadata,self.raw))
            meta.write_text('{"private-secret":true}')
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertNotIn('private-secret',result.stderr)


if __name__ == '__main__':unittest.main()
