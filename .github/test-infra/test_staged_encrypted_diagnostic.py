# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guards; genuine age proof is opt-in and keeps keys outside Git."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('staged_age', HERE / 'staged-encrypted-diagnostic.py')
AGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGE)
PUBLIC = 'age1' + 'q' * 58  # Format fixture; official age validates the checksum.


def fixture(root):
    private = root / 'staged-migrations/owner/PRIVATE-command-failure.txt'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private fixture bytes')
    private.chmod(0o600)
    output = root / 'github-output'
    output.touch()
    identity = {'sourceSHA': 'a' * 40, 'runID': '123', 'runAttempt': '1'}
    (private.parent / 'journal.json').write_text(json.dumps({'schema': 1, 'accepted': False,
        'cluster': identity, 'steps': [{'name': 'bootstrap-exemption', 'status': 'failed'}]}))
    return private, output, {'STAGED_AGE_RECIPIENT': PUBLIC, 'STAGED_TRIAL_OUTCOME': 'failure',
                             'RUNNER_TEMP': str(root), 'GITHUB_OUTPUT': str(output),
                             'GITHUB_SHA': identity['sourceSHA'], 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


def package_fixture(root):
    owner, output, env = fixture(root)
    env.update(SCENARIO='identities', IDENTITY_METHOD='package')
    folder = root / 'staged-migrations/package-identity'
    folder.mkdir(mode=0o700)
    identity = {key: env[name] for key, name in [('sourceSHA', 'GITHUB_SHA'), ('runID', 'GITHUB_RUN_ID'),
                                               ('runAttempt', 'GITHUB_RUN_ATTEMPT')]}
    hashes = {key: AGE.digest((AGE.ROOT / relative).read_bytes()) for key, relative in [
        ('packageDriverSHA256', 'tests/workload-identities/package_roundtrip.py'),
        ('driverSHA256', 'tests/workload-identities/drive.py')]}
    payload = dict(schema=1, binding=identity, role='deploy', phase='transition', exitStatus=1, timedOut=False,
                   stdout='PRIVATE_SECRET_STDOUT', stderr='PRIVATE_SECRET_STDERR', stdoutTruncated=False,
                   stderrTruncated=False, **hashes)
    journal = dict(schema=1, accepted=False, method='package', guard=identity, **hashes,
                   stages=[dict(stage='package-command-failed', role='deploy', phase='transition', exitStatus=1, timedOut=False)])
    save_package(folder, payload, journal)
    return folder, output, env, payload, journal, owner


def save_package(folder, payload, journal):
    private = folder / AGE.PACKAGE_NAME
    private.write_text(json.dumps(payload)); private.chmod(0o600)
    journal['packageCommandFailure'] = dict(file=AGE.PACKAGE_NAME, sha256=AGE.digest(private.read_bytes()), bytes=private.stat().st_size)
    path = folder / 'journal.json'
    path.write_text(json.dumps(journal)); path.chmod(0o600)
    progress = dict(schema=1, guard=journal['guard'], journalSHA256=AGE.digest(path.read_bytes()))
    companion = folder / 'journal-progress.json'
    companion.write_text(json.dumps(progress)); companion.chmod(0o600)


def validation_fixture(root):
    folder,output,env,_command,journal,owner=package_fixture(root)
    codes={'keystore':('metadata','credential-data','object-fields'),
           'cert-network':('metadata','network-policy','object-fields'),
           'cert-account':('metadata','identity-spec','object-fields'),
           'cert-role':('metadata','rbac','object-fields'),'cert-binding':('metadata','rbac','object-fields'),
           'cert-job':('metadata','job-spec','object-fields')}
    source_names=('pepr/capabilities/workload.ts','pepr/capabilities/cloudtak-admin.ts','pepr/capabilities/takclient-credentials.ts')
    def sha(value):return AGE.digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    def meta(name):return {'name':name,'namespace':'takserver','annotations':{'helm.sh/hook':'pre-install,pre-upgrade'}}
    objects=[{'apiVersion':'v1','kind':'Secret','metadata':meta('takserver-keystore'),'data':{'KEYSTORE_SOURCE':'PRIVATE_KEYSTORE_SOURCE'}},
        {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':meta('takserver-cert-init-kube-api'),'spec':{'podSelector':{}}},
        {'apiVersion':'v1','kind':'ServiceAccount','metadata':meta('takserver-cert-init'),'automountServiceAccountToken':False},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':meta('takserver-cert-init'),'rules':[]},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':meta('takserver-cert-init'),'roleRef':{},'subjects':[]},
        {'apiVersion':'batch/v1','kind':'Job','metadata':meta('takserver-cert-init'),'spec':{'template':{'spec':{'containers':[
            {'name':'cert-init','image':'PRIVATE_JOB_IMAGE:fixture','command':['/bin/sh','-c','PRIVATE_JOB_COMMAND'],
             'env':[{'name':'FIXTURE','value':'PRIVATE_JOB_ENV_'+('x'*32768)}]}]}}}}]
    groups={'metadata':{'metadata'},'credential-data':{'data','stringData','type','immutable'},'job-spec':{'spec'},
            'rbac':{'rules','roleRef','subjects'},'network-policy':{'spec'},
            'identity-spec':{'automountServiceAccountToken','secrets','imagePullSecrets'}}
    def origin_for(bodies):
        inventory={}
        for (code,classes),obj in zip(codes.items(),bodies):
            used=set();fields={}
            for group in classes[:-1]:
                names=groups[group];used|=names;fields[group]=sha({key:obj[key] for key in names if key in obj})
            fields['object-fields']=sha({key:value for key,value in obj.items() if key not in used})
            inventory[code]={'sha256':sha(obj),'fieldSHA256':fields}
        return {'sourceFilesSHA256':{name:'a'*64 for name in source_names},'storedHooksSHA256':'a'*64,
                'sourceGeneratorJobSHA256':sha(bodies[-1]),'keystoreHookSHA256':sha(bodies[0]),
                'hookInventory':{'schema':1,'objects':inventory}}
    observed_objects=copy.deepcopy(objects);observed_objects[0]['data']['KEYSTORE_SOURCE']='PRIVATE_CHANGED_KEYSTORE'
    snapshot={'schema':1,'baseline':origin_for(objects),'observed':origin_for(observed_objects),
              'baselineObjects':objects,'observedObjects':observed_objects,
              'diagnostic':{'hook':'keystore','category':'credential','fieldClass':'credential-data'}}
    payload={'schema':1,'type':'retained-source-validation','kind':'stored-hooks-drift','binding':journal['guard'],
             'phase':'transition','snapshot':snapshot,**{key:journal[key] for key in ('packageDriverSHA256','driverSHA256')},
             'retainedSourceSHA256':AGE.digest((AGE.ROOT/'tests/workload-identities/retained_state.py').read_bytes())}
    journal.pop('packageCommandFailure');journal['retainedSourceSHA256']=payload['retainedSourceSHA256']
    journal['stages']=[{'stage':'retained-source-validation-failed','phase':'transition'}]
    save_validation(folder,payload,journal)
    return folder,output,env,payload,journal,owner


def save_validation(folder,payload,journal):
    private=folder/AGE.VALIDATION_NAME;private.write_text(json.dumps(payload));private.chmod(0o600)
    reference={'file':AGE.VALIDATION_NAME,'sha256':AGE.digest(private.read_bytes()),'bytes':private.stat().st_size}
    previous=journal.get('retainedSourceValidationFailure')
    first=journal.get('firstPrivateFailure')
    journal['retainedSourceValidationFailure']=reference
    if previous is None:
        journal.setdefault('firstPrivateFailure',{'schema':1,'kind':'retained-source-validation','reference':reference})
    elif isinstance(first,dict) and first.get('reference')==previous:
        first['reference']=reference
    path=folder/'journal.json';path.write_text(json.dumps(journal));path.chmod(0o600)
    companion=folder/'journal-progress.json'
    companion.write_text(json.dumps({'schema':1,'guard':journal['guard'],'journalSHA256':AGE.digest(path.read_bytes())}));companion.chmod(0o600)


class EncryptedDiagnosticGuards(unittest.TestCase):
    def test_core_validation_is_sealed_and_rejects_raw_or_forged_inventory(self):
        for mutation in ('valid','raw-body','unknown-key','diagnostic','unchanged','operation','kind-alias'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);folder,_output,env,payload,journal,_owner=validation_fixture(root)
                payload['kind']='core-inventory-drift'
                payload['snapshot']={'schema':1,'operation':'application-removed',
                    'baseline':{'namespace/kube-system':'original-uid','mesh':'a'*64},
                    'observed':{'namespace/kube-system':'replacement-uid','mesh':'a'*64},
                    'diagnostic':{'category':'namespace','change':'changed'}}
                if mutation=='raw-body':payload['snapshot']['observed']['namespace/kube-system']={'data':'PRIVATE_CORE_SENTINEL'}
                elif mutation=='unknown-key':payload['snapshot']['observed']['secrets/private']='PRIVATE_CORE_SENTINEL'
                elif mutation=='diagnostic':payload['snapshot']['diagnostic']['category']='mesh'
                elif mutation=='unchanged':payload['snapshot']['observed']=copy.deepcopy(payload['snapshot']['baseline'])
                elif mutation=='operation':payload['snapshot']['operation']='PRIVATE_CORE_SENTINEL'
                elif mutation=='kind-alias':payload['kind']='stored-hooks-drift'
                save_validation(folder,payload,journal)
                with patch.dict(os.environ,env,clear=True),patch.object(AGE,'reviewed_source_hash',side_effect=lambda name:AGE.digest((AGE.ROOT/name).read_bytes())):
                    if mutation=='valid':
                        descriptor=AGE.package_input(root)
                        try:
                            self.assertEqual(os.read(descriptor,AGE.VALIDATION_INPUT_LIMIT+1),(folder/AGE.VALIDATION_NAME).read_bytes())
                            with self.assertRaises(OSError):os.write(descriptor,b'foreign')
                        finally:os.close(descriptor)
                    else:
                        with self.assertRaises(ValueError):AGE.package_input(root)

    def test_application_check_binding_selection_and_private_schema(self):
        for mutation in ('valid','task','phase','binding','hash','stage','earlier','missing-first','link','mode'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);folder,_out,env,payload,journal,_owner=package_fixture(root)
                payload.pop('role');payload['check']='api-smoke'
                journal.pop('packageCommandFailure')
                journal['stages']=[dict(stage='application-check-failed',check='api-smoke',phase='transition',exitStatus=1,timedOut=False)]
                if mutation=='task':payload['check']='arbitrary'
                if mutation=='phase':payload['phase']='arbitrary'
                if mutation=='binding':payload['binding']={**payload['binding'],'runID':'999'}
                if mutation=='hash':payload['driverSHA256']='0'*64
                if mutation=='stage':journal['stages'][0]['check']='flows'
                if mutation=='earlier':journal['stages'].insert(0,{'stage':'package-command-failed'})
                private=folder/AGE.APPLICATION_NAME;private.write_text(json.dumps(payload));private.chmod(0o600)
                reference=dict(file=AGE.APPLICATION_NAME,sha256=AGE.digest(private.read_bytes()),bytes=private.stat().st_size)
                journal['applicationCheckFailure']=reference
                journal['firstPrivateFailure']=dict(schema=1,kind='application-check',reference=dict(reference))
                if mutation=='missing-first':journal.pop('firstPrivateFailure')
                path=folder/'journal.json';path.write_text(json.dumps(journal));path.chmod(0o600)
                companion=folder/'journal-progress.json'
                companion.write_text(json.dumps(dict(schema=1,guard=journal['guard'],journalSHA256=AGE.digest(path.read_bytes()))));companion.chmod(0o600)
                if mutation=='mode':private.chmod(0o644)
                if mutation=='link':
                    original=folder/'foreign';private.rename(original);private.symlink_to(original)
                with patch.dict(os.environ,env,clear=True),patch.object(AGE,'reviewed_source_hash',side_effect=lambda name:AGE.digest((AGE.ROOT/name).read_bytes())):
                    if mutation=='valid':
                        descriptor=AGE.package_input(root)
                        try:
                            self.assertEqual(os.read(descriptor,AGE.INPUT_LIMIT+1),private.read_bytes())
                            with self.assertRaises(OSError):os.write(descriptor,b'foreign')
                        finally:os.close(descriptor)
                    else:
                        with self.assertRaises((ValueError,OSError)):AGE.package_input(root)

    def test_typed_validation_is_sealed_and_later_command_does_not_replace_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder,_output,env,payload,journal,_owner=validation_fixture(root)
            journal['packageCommandFailure']={'file':AGE.PACKAGE_NAME,'sha256':'f'*64,'bytes':1}
            journal['stages'].append({'stage':'package-command-failed','role':'remove','phase':'shared','exitStatus':1,'timedOut':False})
            save_validation(folder,payload,journal)
            original=(folder/AGE.VALIDATION_NAME).read_bytes()
            with patch.dict(os.environ,env,clear=True),patch.object(AGE,'reviewed_source_hash',side_effect=lambda name:AGE.digest((AGE.ROOT/name).read_bytes())):
                descriptor=AGE.package_input(root)
            try:
                self.assertTrue(os.read(descriptor,AGE.VALIDATION_INPUT_LIMIT+1)==original)
                with self.assertRaises(OSError):os.write(descriptor,b'foreign')
            finally:os.close(descriptor)

    def test_explicit_command_first_remains_selected_and_legacy_schema_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder,_output,env,command,journal,_owner=package_fixture(root)
            original=(folder/AGE.PACKAGE_NAME).read_bytes()
            self.assertEqual(set(command),{'schema','binding','role','phase','exitStatus','timedOut','stdout','stderr',
                                          'stdoutTruncated','stderrTruncated','packageDriverSHA256','driverSHA256'})
            journal['firstPrivateFailure']={'schema':1,'kind':'package-command','reference':dict(journal['packageCommandFailure'])}
            journal['retainedSourceValidationFailure']={'file':AGE.VALIDATION_NAME,'sha256':'f'*64,'bytes':1}
            journal['stages'].append({'stage':'retained-source-validation-failed','phase':'shared'})
            save_package(folder,command,journal)
            with patch.dict(os.environ,env,clear=True),patch.object(AGE,'reviewed_source_hash',side_effect=lambda name:AGE.digest((AGE.ROOT/name).read_bytes())):
                descriptor=AGE.package_input(root)
            try:self.assertTrue(os.read(descriptor,AGE.INPUT_LIMIT+1)==original)
            finally:os.close(descriptor)

    def test_validation_malformed_alias_oversize_binding_order_and_private_paths_rejected(self):
        cases=('missing-first','ambiguous-first','first-schema','reference-alias','earlier-command','schema','type','kind',
               'source','run','attempt','phase','stage','source-hash','snapshot-key','inventory-code','diagnostic','oversize',
               'private-link','private-mode','duplicate-key','body-alias','body-field','body-duplicate')
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);folder,output,env,payload,journal,_owner=validation_fixture(root)
                if case=='missing-first':journal.pop('firstPrivateFailure')
                elif case=='ambiguous-first':journal['firstPrivateFailure']['kind']='unknown'
                elif case=='first-schema':journal['firstPrivateFailure']['schema']=True
                elif case=='reference-alias':journal['firstPrivateFailure']['reference']={**journal['retainedSourceValidationFailure'],'file':AGE.PACKAGE_NAME}
                elif case=='earlier-command':journal['stages'].insert(0,{'stage':'package-command-failed'})
                elif case in ('schema','type','kind'):payload[case]='PRIVATE_SENTINEL'
                elif case in ('source','run','attempt'):payload['binding'][{'source':'sourceSHA','run':'runID','attempt':'runAttempt'}[case]]='PRIVATE_SENTINEL'
                elif case=='phase':payload['phase']='baseline'
                elif case=='stage':journal['stages'][0]['phase']='strict'
                elif case=='source-hash':payload['retainedSourceSHA256']=journal['retainedSourceSHA256']='0'*64
                elif case=='snapshot-key':payload['snapshot']['raw']='PRIVATE_SENTINEL'
                elif case=='inventory-code':payload['snapshot']['baseline']['hookInventory']['objects']['unknown']=payload['snapshot']['baseline']['hookInventory']['objects'].pop('keystore')
                elif case=='diagnostic':payload['snapshot']['diagnostic']['category']='PRIVATE_SENTINEL'
                elif case=='body-alias':payload['snapshot']['baselineObjects']=payload['snapshot']['observedObjects']
                elif case=='body-field':payload['snapshot']['observedObjects'][-1]['spec']['template']['spec']['containers'][0]['image']='PRIVATE_SENTINEL'
                elif case=='body-duplicate':payload['snapshot']['observedObjects'].append(copy.deepcopy(payload['snapshot']['observedObjects'][0]))
                elif case=='oversize':payload['snapshot']['raw']='PRIVATE_SENTINEL'*6000
                save_validation(folder,payload,journal)
                private=folder/AGE.VALIDATION_NAME
                if case=='private-link':private.unlink();private.symlink_to(root/'foreign')
                elif case=='private-mode':private.chmod(0o644)
                elif case=='duplicate-key':
                    data=private.read_text().replace('"schema": 1','"schema": 1, "schema": 1',1);private.write_text(data)
                captured=io.StringIO()
                with patch.dict(os.environ,env,clear=True),patch.object(AGE,'context'), \
                     patch.object(AGE,'reviewed_source_hash',side_effect=lambda name:AGE.digest((AGE.ROOT/name).read_bytes())), \
                     patch.object(AGE,'acquire_age',side_effect=AssertionError('must not acquire')) as acquire, \
                     contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
                    self.assertEqual(AGE.main(),1)
                acquire.assert_not_called();self.assertEqual(output.read_bytes(),b'')
                self.assertFalse((root/AGE.OUTPUT_NAME).exists());self.assertNotIn('PRIVATE_SENTINEL',captured.getvalue())

    def test_package_only_validated_snapshot_reaches_ciphertext_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder, output, env, _payload, _journal, _owner = package_fixture(root)
            original = (folder / AGE.PACKAGE_NAME).read_bytes()
            observed = []
            def encrypt(_binary, _pin, descriptor, _recipient):
                # Changing the pathname after authentication cannot replace the
                # sealed snapshot passed to age, nor can it be overwritten.
                (folder / AGE.PACKAGE_NAME).write_text('changed after authentication')
                with self.assertRaises(OSError):
                    os.write(descriptor, b'foreign')
                observed.append(os.read(descriptor, AGE.INPUT_LIMIT + 1))
                return b'age-encryption.org/v1\nfixture-ciphertext'
            captured = io.StringIO()
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', return_value=(root/'age', AGE.PINS['x86_64'])), \
                    patch.object(AGE, 'encrypt_private', side_effect=encrypt), \
                    contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                self.assertEqual(AGE.main(), 0)
            self.assertEqual(observed, [original])
            self.assertEqual(output.read_bytes(), b'ready=true\n')
            destination = root / AGE.OUTPUT_NAME
            self.assertEqual([p.name for p in destination.iterdir()], ['first-failure.age'])
            self.assertNotIn(b'PRIVATE_SECRET', (destination/'first-failure.age').read_bytes())
            self.assertNotIn('PRIVATE_SECRET', captured.getvalue())

    def test_package_tamper_cross_source_or_missing_inputs_never_acquire_age(self):
        cases = ('source', 'run', 'attempt', 'driver', 'package-driver', 'accepted', 'stage', 'role', 'phase',
                 'exit', 'timeout-type', 'schema-bool', 'extra-key', 'oversized-stream', 'private-hash',
                 'companion-hash', 'companion-guard', 'missing-private', 'missing-companion', 'private-mode',
                 'parent-mode', 'private-link', 'parent-link', 'fifo', 'oversized-file', 'journal-bound')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder, output, env, payload, journal, _owner = package_fixture(root)
                if case in ('source', 'run', 'attempt'):
                    payload['binding'][{'source':'sourceSHA', 'run':'runID', 'attempt':'runAttempt'}[case]] = 'PRIVATE_SECRET'
                elif case in ('driver', 'package-driver'):
                    key = 'driverSHA256' if case == 'driver' else 'packageDriverSHA256'
                    payload[key] = journal[key] = '0' * 64
                elif case == 'accepted': journal['accepted'] = True
                elif case == 'stage': journal['stages'][0]['exitStatus'] = 2
                elif case == 'role': payload['role'] = 'PRIVATE_SECRET'
                elif case == 'phase': payload['phase'] = 'PRIVATE_SECRET'
                elif case == 'exit': payload['exitStatus'] = 0
                elif case == 'timeout-type': payload['timedOut'] = 1
                elif case == 'schema-bool': payload['schema'] = True
                elif case == 'extra-key': payload['argv'] = ['PRIVATE_SECRET']
                elif case == 'oversized-stream': payload['stderr'] = 'PRIVATE_SECRET' * 2048
                save_package(folder, payload, journal)
                private = folder / AGE.PACKAGE_NAME
                if case == 'private-hash': private.write_text('PRIVATE_SECRET')
                elif case == 'companion-hash': (folder/'journal.json').write_text('{}')
                elif case == 'companion-guard':
                    path = folder/'journal-progress.json'; value = json.loads(path.read_text()); value['guard']['runID'] = '999'; path.write_text(json.dumps(value))
                elif case == 'missing-private': private.unlink()
                elif case == 'missing-companion': (folder/'journal-progress.json').unlink()
                elif case == 'private-mode': private.chmod(0o644)
                elif case == 'parent-mode': folder.chmod(0o755)
                elif case == 'private-link': private.unlink(); private.symlink_to(root/'foreign')
                elif case == 'parent-link':
                    for path in folder.iterdir(): path.unlink()
                    folder.rmdir(); folder.symlink_to(root)
                elif case == 'fifo': private.unlink(); os.mkfifo(private)
                elif case == 'oversized-file':
                    with private.open('wb') as stream: stream.truncate(AGE.INPUT_LIMIT + 1)
                elif case == 'journal-bound':
                    with (folder/'journal.json').open('wb') as stream: stream.truncate(AGE.PACKAGE_JOURNAL_LIMIT + 1)
                captured = io.StringIO()
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')) as acquire, \
                        contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    self.assertEqual(AGE.main(), 1)
                acquire.assert_not_called()
                self.assertEqual(output.read_bytes(), b'')
                self.assertFalse((root/AGE.OUTPUT_NAME).exists())
                self.assertNotIn('PRIVATE_SECRET', captured.getvalue())

    def test_all_scenario_ignores_passed_owner_but_refuses_two_failed_channels(self):
        for owner_failed in (False, True):
            with self.subTest(owner_failed=owner_failed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _folder, output, env, _payload, _journal, owner = package_fixture(root)
                env.update(SCENARIO='all', IDENTITY_METHOD='combined')
                path = owner.parent/'journal.json'; value = json.loads(path.read_text()); value['accepted'] = not owner_failed; path.write_text(json.dumps(value))
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', return_value=(root/'age', AGE.PINS['x86_64'])) as acquire, \
                        patch.object(AGE, 'encrypt_private', return_value=b'age-encryption.org/v1\ncipher'):
                    self.assertEqual(AGE.main(), 1 if owner_failed else 0)
                self.assertEqual(acquire.call_count, 0 if owner_failed else 1)
                self.assertEqual(output.read_bytes(), b'' if owner_failed else b'ready=true\n')

    def test_reviewed_source_hash_checks_actual_head_and_worktree_without_network(self):
        relative = 'tests/workload-identities/drive.py'
        self.assertEqual(AGE.reviewed_source_hash(relative), AGE.digest((AGE.ROOT/relative).read_bytes()))
        with patch.object(AGE, 'bounded_process', return_value=b'changed source'), self.assertRaises(ValueError):
            AGE.reviewed_source_hash(relative)

    def test_default_empty_and_nonfailure_download_and_install_nothing(self):
        for env in ({}, {'STAGED_AGE_RECIPIENT': ''},
                    {'STAGED_AGE_RECIPIENT': PUBLIC, 'STAGED_TRIAL_OUTCOME': 'success'}):
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')), \
                    patch.object(AGE.tempfile, 'TemporaryDirectory', side_effect=AssertionError('install')):
                self.assertEqual(AGE.main(), 0)

    def test_recipient_and_fixed_private_file_guards_fail_before_download(self):
        for case in ('private-key', 'plugin', 'newline', 'missing', 'oversized', 'symlink', 'parent-link', 'fifo'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                private, output, env = fixture(root)
                if case == 'private-key':
                    env['STAGED_AGE_RECIPIENT'] = 'AGE-SECRET-KEY-DO_NOT_ECHO'
                elif case == 'plugin':
                    env['STAGED_AGE_RECIPIENT'] = 'age1plugin1DO_NOT_ECHO'
                elif case == 'newline':
                    env['STAGED_AGE_RECIPIENT'] += '\nDO_NOT_ECHO'
                elif case == 'oversized':
                    private.write_bytes(b'x' * 65537)
                elif case == 'symlink':
                    private.unlink(); private.symlink_to(root / 'foreign')
                elif case == 'parent-link':
                    private.unlink(); (private.parent / 'journal.json').unlink()
                    private.parent.rmdir(); private.parent.symlink_to(root)
                else:
                    private.unlink()
                    if case == 'fifo':
                        os.mkfifo(private)
                captured = io.StringIO()
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')), \
                        contextlib.redirect_stderr(captured):
                    self.assertEqual(AGE.main(), 1)
                self.assertEqual(output.read_bytes(), b'')
                self.assertFalse((root / AGE.OUTPUT_NAME).exists())
                self.assertNotIn('DO_NOT_ECHO', captured.getvalue())

    def test_stale_source_run_or_successful_owner_journal_cannot_encrypt(self):
        for field in ('sourceSHA', 'runID', 'runAttempt', 'accepted'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                private, output, env = fixture(root)
                journal = private.parent / 'journal.json'
                data = json.loads(journal.read_text())
                if field == 'accepted':
                    data['accepted'] = True
                else:
                    data['cluster'][field] = 'different'
                journal.write_text(json.dumps(data))
                with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                        patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')):
                    self.assertEqual(AGE.main(), 1)
                self.assertEqual(output.read_bytes(), b'')

    def test_identity_requires_same_repository_manual_main_actual_checkout(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=AGE.ROOT).decode().strip()
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_REPOSITORY': 'jonathanagustin/uds-takserver', 'GITHUB_SHA': head,
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        with patch.dict(os.environ, env, clear=True):
            AGE.context()
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/other'),
                           ('GITHUB_REPOSITORY', 'fork/repo'), ('GITHUB_SHA', '0' * 40),
                           ('GITHUB_RUN_ID', 'invalid'), ('GITHUB_RUN_ATTEMPT', '0')]:
            with self.subTest(key=key), patch.dict(os.environ, {**env, key: value}, clear=True), \
                    self.assertRaises(ValueError):
                AGE.context()

    def test_archive_checksum_and_nonregular_members_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                AGE.extract_age(b'corrupt', AGE.PINS['x86_64'], root)
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                member = tarfile.TarInfo('age/age')
                member.type = tarfile.SYMTYPE
                member.linkname = '/foreign'
                archive.addfile(member)
            raw = stream.getvalue()
            with self.assertRaises(ValueError):
                AGE.extract_age(raw, ('amd64', len(raw), AGE.digest(raw), 0, 'unused'), root)
            self.assertEqual(list(root.iterdir()), [])

    def test_optional_errors_preserve_existing_output_and_never_mark_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, env = fixture(root)
            destination = root / AGE.OUTPUT_NAME
            destination.mkdir()
            preserved = destination / 'first-failure.age'
            preserved.write_bytes(b'previous output')
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', side_effect=AssertionError('download')):
                self.assertEqual(AGE.main(), 1)
            self.assertEqual(preserved.read_bytes(), b'previous output')
            preserved.unlink(); destination.rmdir()
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', side_effect=RuntimeError('DO_NOT_ECHO')), \
                    patch.object(AGE, 'bounded_process', side_effect=AssertionError('host-tool fallback')) as child:
                self.assertEqual(AGE.main(), 1)
            child.assert_not_called()
            self.assertEqual(output.read_bytes(), b'')
            self.assertFalse(destination.exists())

    def test_encryption_failure_and_partial_output_are_not_uploadable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output, env = fixture(root)
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', return_value=(root / 'age', AGE.PINS['x86_64'])), \
                    patch.object(AGE, 'encrypt_private', side_effect=RuntimeError('DO_NOT_ECHO')):
                self.assertEqual(AGE.main(), 1)
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'context'), \
                    patch.object(AGE, 'acquire_age', return_value=(root / 'age', AGE.PINS['x86_64'])), \
                    patch.object(AGE, 'encrypt_private', return_value=b'age-encryption.org/v1\nfixture-cipher'), \
                    patch.object(AGE.os, 'write', return_value=0):
                self.assertEqual(AGE.main(), 1)
            self.assertEqual(output.read_bytes(), b'')
            self.assertFalse((root / AGE.OUTPUT_NAME).exists())

    def test_real_process_output_stderr_and_lifetime_are_bounded(self):
        for code, limit, seconds in [('print("x"*10000)', 100, 2),
                                     ('import sys;sys.stderr.write("x"*5000)', 100, 2),
                                     ('import time;time.sleep(30)', 100, 0.1)]:
            started = time.monotonic()
            with self.assertRaises(ValueError):
                AGE.bounded_process([sys.executable, '-c', code], limit=limit, seconds=seconds)
            self.assertLess(time.monotonic() - started, 5)

    def test_workflow_only_uploads_ciphertext_after_failed_trial_successful_encryption(self):
        # String checks keep this Unit step stdlib-only.
        workflow = (AGE.ROOT / '.github/workflows/staged-migrations.yaml').read_text()
        self.assertIn('diagnostic_recipient:', workflow)
        self.assertIn('default: ""', workflow.split('diagnostic_recipient:', 1)[1].split('permissions:', 1)[0])
        encrypt = workflow.split('- name: Encrypt optional first failure diagnostic', 1)[1]
        self.assertIn("steps.staged-trial.outcome == 'failure' && inputs.diagnostic_recipient != ''", encrypt)
        self.assertIn('STAGED_AGE_RECIPIENT: ${{ inputs.diagnostic_recipient }}', encrypt)
        upload = encrypt.split('- name: Upload only encrypted first failure diagnostic', 1)[1].split('  summary:', 1)[0]
        self.assertIn("steps.encrypt-first-failure.outcome == 'success'", upload)
        self.assertIn("steps.encrypt-first-failure.outputs.ready == 'true'", upload)
        self.assertIn('path: ${{ runner.temp }}/staged-encrypted-diagnostic/first-failure.age', upload)
        self.assertNotIn('PRIVATE-command-failure.txt', upload)
        self.assertNotIn('**', upload)


@unittest.skipUnless(os.environ.get('STAGED_AGE_ARCHIVE') and os.environ.get('STAGED_AGE_KEYGEN'),
                     'opt-in official age archive/keygen required for genuine roundtrip')
class GenuineAgeProof(unittest.TestCase):
    def test_real_official_validation_collector_roundtrip_wrong_key_and_integrity(self):
        keygen=Path(os.environ['STAGED_AGE_KEYGEN']);binary=keygen.with_name('age');pin=AGE.PINS['x86_64']
        self.assertEqual(AGE.digest(binary.read_bytes()),pin[4])
        self.assertEqual(AGE.digest(keygen.read_bytes()),'0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899')
        with tempfile.TemporaryDirectory(prefix='validation-age-proof-') as temporary:
            root=Path(temporary);folder,output,env,payload,journal,_owner=validation_fixture(root)
            head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=AGE.ROOT).decode().strip()
            # Persist through the real producer, then authenticate/encrypt that file.
            from tests.test_package_identity_driver import P
            for child in folder.iterdir():child.unlink()
            trial=object.__new__(P.PackageTrial);trial.evidence=folder/'journal.json'
            trial.state={'schema':1,'method':'package','accepted':False,'stages':[],
                         'guard':{'sourceSHA':head,'runID':'123','runAttempt':'1'}}
            trial.capture_retained_validation(payload['snapshot'],'transition')
            plain=(folder/AGE.VALIDATION_NAME).read_bytes()
            journal_text=trial.evidence.read_text()
            for value in ('PRIVATE_JOB_IMAGE','PRIVATE_JOB_COMMAND','PRIVATE_JOB_ENV','PRIVATE_KEYSTORE_SOURCE'):
                self.assertNotIn(value,journal_text)
                self.assertNotIn(value,(folder/'journal-progress.json').read_text())
            for name in ('correct','wrong'):
                subprocess.run([str(keygen),'-o',str(root/(name+'.key'))],capture_output=True,timeout=10,check=True)
            recipient=subprocess.run([str(keygen),'-y',str(root/'correct.key')],capture_output=True,timeout=10,check=True).stdout.decode().strip()
            env.update(STAGED_AGE_RECIPIENT=recipient,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF='refs/heads/main',
                       GITHUB_REPOSITORY='jonathanagustin/uds-takserver',GITHUB_SHA=head)
            captured=io.StringIO()
            with patch.dict(os.environ,env,clear=True),patch.object(AGE,'acquire_age',return_value=(binary,pin)), \
                    contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
                self.assertEqual(AGE.main(),0)
            cipher=root/AGE.OUTPUT_NAME/'first-failure.age'
            self.assertEqual(output.read_bytes(),b'ready=true\n')
            self.assertEqual([item.name for item in cipher.parent.iterdir()],['first-failure.age'])
            self.assertEqual(cipher.stat().st_mode&0o777,0o600)
            decrypted=subprocess.run([str(binary),'--decrypt','-i',str(root/'correct.key'),str(cipher)],capture_output=True,timeout=10)
            self.assertEqual(decrypted.returncode,0);self.assertTrue(decrypted.stdout==plain)
            restored=json.loads(decrypted.stdout)
            job=restored['snapshot']['baselineObjects'][-1]['spec']['template']['spec']['containers'][0]
            self.assertEqual(job['image'],'PRIVATE_JOB_IMAGE:fixture')
            self.assertEqual(job['command'],['/bin/sh','-c','PRIVATE_JOB_COMMAND'])
            self.assertTrue(job['env'][0]['value'].startswith('PRIVATE_JOB_ENV_'))
            self.assertEqual(restored['snapshot']['baselineObjects'][0]['data']['KEYSTORE_SOURCE'],'PRIVATE_KEYSTORE_SOURCE')
            self.assertGreater(len(plain),AGE.INPUT_LIMIT)
            self.assertLessEqual(len(plain),AGE.VALIDATION_INPUT_LIMIT)
            self.assertLessEqual(cipher.stat().st_size,AGE.VALIDATION_CIPHER_LIMIT)
            for value in ('PRIVATE_JOB_IMAGE','PRIVATE_JOB_COMMAND','PRIVATE_JOB_ENV','PRIVATE_KEYSTORE_SOURCE'):
                self.assertNotIn(value,captured.getvalue())
            wrong=subprocess.run([str(binary),'--decrypt','-i',str(root/'wrong.key'),str(cipher)],capture_output=True,timeout=10)
            self.assertNotEqual(wrong.returncode,0);self.assertEqual(wrong.stdout,b'')
            damaged=bytearray(cipher.read_bytes());damaged[-3]^=1;cipher.write_bytes(damaged)
            altered=subprocess.run([str(binary),'--decrypt','-i',str(root/'correct.key'),str(cipher)],capture_output=True,timeout=10)
            self.assertNotEqual(altered.returncode,0)
            self.assertTrue((folder/AGE.VALIDATION_NAME).read_bytes()==plain)
            self.assertNotIn('stored-hooks-drift',captured.getvalue())

    def test_real_application_collector_encryption_roundtrip(self):
        from tests.test_package_identity_driver import P
        pin=AGE.PINS['x86_64'];keygen=Path(os.environ['STAGED_AGE_KEYGEN'])
        binary=keygen.with_name('age');self.assertEqual(AGE.digest(binary.read_bytes()),pin[4])
        with tempfile.TemporaryDirectory(prefix='application-age-proof-') as temporary:
            root=Path(temporary);folder,output,env,_payload,journal,_owner=package_fixture(root)
            for child in folder.iterdir():child.unlink()
            head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=AGE.ROOT).decode().strip()
            trial=object.__new__(P.PackageTrial);trial.evidence=folder/'journal.json'
            trial.state={**journal,'guard':{**journal['guard'],'sourceSHA':head},'stages':[]}
            trial.state.pop('packageCommandFailure');trial.guard=lambda:None;trial.deadline=P.time.monotonic()+60
            result=dict(exitStatus=3,timedOut=False,stdout='PRIVATE_APPLICATION_STDOUT',stderr='PRIVATE_APPLICATION_STDERR',
                        stdoutTruncated=False,stderrTruncated=False)
            with patch.object(P,'bounded_package_run',return_value=result):
                with self.assertRaises(ValueError):trial.run_application_check('api-smoke','transition')
            plain=(folder/AGE.APPLICATION_NAME).read_bytes()
            subprocess.run([str(keygen),'-o',str(root/'key')],capture_output=True,timeout=10,check=True)
            recipient=subprocess.run([str(keygen),'-y',str(root/'key')],capture_output=True,timeout=10,check=True).stdout.decode().strip()
            env.update(STAGED_AGE_RECIPIENT=recipient,GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REF='refs/heads/main',
                       GITHUB_REPOSITORY='jonathanagustin/uds-takserver',GITHUB_SHA=head)
            captured=io.StringIO()
            with patch.dict(os.environ,env,clear=True),patch.object(AGE,'acquire_age',return_value=(binary,pin)), \
                    contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
                self.assertEqual(AGE.main(),0)
            cipher=root/AGE.OUTPUT_NAME/'first-failure.age'
            decrypted=subprocess.run([str(binary),'--decrypt','-i',str(root/'key'),str(cipher)],capture_output=True,timeout=10,check=True)
            self.assertEqual(decrypted.stdout,plain)
            for text in (trial.evidence.read_text(),(folder/'journal-progress.json').read_text(),captured.getvalue()):
                self.assertNotIn('PRIVATE_APPLICATION_',text)
            self.assertEqual(output.read_bytes(),b'ready=true\n')

    def test_real_official_package_collector_roundtrip_and_wrong_key(self):
        pin = AGE.PINS['x86_64']
        archive = Path(os.environ['STAGED_AGE_ARCHIVE']).read_bytes()
        keygen = Path(os.environ['STAGED_AGE_KEYGEN'])
        keygen_hash = '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899'
        self.assertEqual(AGE.digest(keygen.read_bytes()), keygen_hash)
        with tempfile.TemporaryDirectory(prefix='staged-package-age-proof-') as temporary:
            root = Path(temporary)
            self.assertNotIn(AGE.ROOT, root.parents)
            folder, output, env, payload, journal, _owner = package_fixture(root)
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=AGE.ROOT).decode().strip()
            payload['binding']['sourceSHA'] = journal['guard']['sourceSHA'] = head
            save_package(folder, payload, journal)
            private = folder / AGE.PACKAGE_NAME
            plain = private.read_bytes()
            self.assertIn(b'PRIVATE_SECRET_STDOUT', plain)
            self.assertIn(b'PRIVATE_SECRET_STDERR', plain)
            for name in ('correct', 'wrong'):
                key = root / (name + '.key')
                subprocess.run([str(keygen), '-o', str(key)], capture_output=True, timeout=10, check=True)
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            recipient = subprocess.run([str(keygen), '-y', str(root/'correct.key')],
                                       capture_output=True, timeout=10, check=True).stdout.decode().strip()
            self.assertTrue(AGE.RECIPIENT.fullmatch(recipient))
            env.update(STAGED_AGE_RECIPIENT=recipient, GITHUB_EVENT_NAME='workflow_dispatch',
                       GITHUB_REF='refs/heads/main', GITHUB_REPOSITORY='jonathanagustin/uds-takserver',
                       GITHUB_SHA=head)
            def acquire(directory):
                return AGE.extract_age(archive, pin, directory), pin
            captured = io.StringIO()
            # Actual context, source checks, sealed snapshot and encryption run;
            # only the official archive's network acquisition is replaced.
            with patch.dict(os.environ, env, clear=True), patch.object(AGE, 'acquire_age', side_effect=acquire), \
                    contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                self.assertEqual(AGE.main(), 0)
            cipher = root / AGE.OUTPUT_NAME / 'first-failure.age'
            self.assertEqual(output.read_bytes(), b'ready=true\n')
            self.assertEqual([path.name for path in cipher.parent.iterdir()], ['first-failure.age'])
            self.assertEqual(cipher.stat().st_mode & 0o777, 0o600)
            self.assertLessEqual(cipher.stat().st_size, AGE.CIPHER_LIMIT)
            self.assertTrue(private.read_bytes() == plain)
            self.assertNotIn('PRIVATE_SECRET', captured.getvalue())
            tools = root / 'decrypt-tools'; tools.mkdir()
            binary = AGE.extract_age(archive, pin, tools)
            decrypted = subprocess.run([str(binary), '--decrypt', '-i', str(root/'correct.key'), str(cipher)],
                                       capture_output=True, timeout=10, check=True)
            # Boolean comparison prevents secret-bearing bytes in a failed diff.
            self.assertTrue(decrypted.stdout == plain)
            wrong = subprocess.run([str(binary), '--decrypt', '-i', str(root/'wrong.key'), str(cipher)],
                                   capture_output=True, timeout=10)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertEqual(wrong.stdout, b'')
            self.assertEqual(AGE.digest(keygen.read_bytes()), keygen_hash)

    def test_real_official_keygen_encrypt_decrypt_wrong_key_and_integrity(self):
        pin = AGE.PINS['x86_64']
        archive = Path(os.environ['STAGED_AGE_ARCHIVE']).read_bytes()
        keygen = Path(os.environ['STAGED_AGE_KEYGEN'])
        self.assertEqual(AGE.digest(keygen.read_bytes()),
                         '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899')
        with tempfile.TemporaryDirectory(prefix='staged-age-proof-') as temporary:
            root = Path(temporary)
            self.assertNotIn(AGE.ROOT, root.parents)
            private, output, env = fixture(root)
            plain = (b'fixture private failure\x00' * 3000)[:AGE.INPUT_LIMIT]
            private.write_bytes(plain)
            for name in ('correct', 'wrong'):
                key = root / (name + '.key')
                subprocess.run([str(keygen), '-o', str(key)], capture_output=True, timeout=10, check=True)
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            recipient = subprocess.run([str(keygen), '-y', str(root / 'correct.key')],
                                       capture_output=True, timeout=10, check=True).stdout.decode().strip()
            self.assertTrue(AGE.RECIPIENT.fullmatch(recipient))
            env['STAGED_AGE_RECIPIENT'] = recipient
            env.update(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
                       GITHUB_REPOSITORY='jonathanagustin/uds-takserver',
                       GITHUB_SHA=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=AGE.ROOT).decode().strip())
            journal = private.parent / 'journal.json'
            metadata = json.loads(journal.read_text())
            metadata['cluster']['sourceSHA'] = env['GITHUB_SHA']
            journal.write_text(json.dumps(metadata))
            def acquire(directory):
                return AGE.extract_age(archive, pin, directory), pin
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(AGE, 'acquire_age', side_effect=acquire):
                self.assertEqual(AGE.main(), 0)
            cipher = root / AGE.OUTPUT_NAME / 'first-failure.age'
            self.assertEqual(output.read_bytes(), b'ready=true\n')
            self.assertEqual(cipher.stat().st_mode & 0o777, 0o600)
            self.assertLessEqual(cipher.stat().st_size, AGE.CIPHER_LIMIT)
            self.assertEqual(private.read_bytes(), plain)
            self.assertEqual([p.name for p in cipher.parent.iterdir()], ['first-failure.age'])
            tools = root / 'decrypt-tools'; tools.mkdir()
            binary = AGE.extract_age(archive, pin, tools)
            decrypted = subprocess.run([str(binary), '--decrypt', '-i', str(root / 'correct.key'), str(cipher)],
                                       capture_output=True, timeout=10, check=True)
            self.assertTrue(decrypted.stdout == plain)
            wrong = subprocess.run([str(binary), '--decrypt', '-i', str(root / 'wrong.key'), str(cipher)],
                                   capture_output=True, timeout=10)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertEqual(wrong.stdout, b'')
            self.assertEqual(AGE.digest(keygen.read_bytes()),
                             '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899')
            changed = bytearray(binary.read_bytes()); changed[-1] ^= 1
            binary.write_bytes(changed)
            fd = AGE.regular_descriptor(private, AGE.INPUT_LIMIT)
            try:
                with self.assertRaises(ValueError), patch.object(AGE, 'bounded_process', side_effect=AssertionError('execute')):
                    AGE.encrypt_private(binary, pin, fd, recipient)
            finally:
                os.close(fd)


if __name__ == '__main__':
    unittest.main()
