# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline failure observability; no cluster, commands, messages or manifests captured."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.test_package_identity_driver import P, ROOT
from tests.test_staged_migrations import S, ENV

F = P.F


def source_bytes(relative, *_args):
    if relative not in F.FILES:
        raise ValueError('unreviewed source')
    return (ROOT/relative).read_bytes()


def mocked_git(argv, **_kwargs):
    if argv[-2:] == ['rev-parse', 'HEAD']:
        return subprocess.CompletedProcess(argv, 0, (ENV['GITHUB_SHA']+'\n').encode(), b'')
    if argv[-1].startswith('HEAD:'):
        return subprocess.CompletedProcess(argv, 0, source_bytes(argv[-1][5:]), b'')
    raise AssertionError('unexpected subprocess')


class FailureEvidenceTests(unittest.TestCase):
    def test_retained_diagnostic_failure_is_separate_from_primary_and_revalidated(self):
        environment={**ENV,'SCENARIO':'identities','IDENTITY_METHOD':'package'}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,environment,clear=True), \
                patch.object(F.subprocess,'run',side_effect=mocked_git):
            root=Path(directory);folder=root/'package-identity';folder.mkdir(mode=0o700)
            bound={key:'a'*64 for key in ('archiveSHA256','planSHA256','configSHA256')}
            bound.update(chartBinding={'chartOverridesSHA256':'b'*64},
                         phaseValues={phase:{'sha256':'c'*64} for phase in P.D.PHASES})
            trial=P.PackageTrial(folder/'journal.json',bound)
            trial.state['guard']={key:ENV[env] for key,env in
                [('sourceSHA','GITHUB_SHA'),('runID','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
            trial.state['coreSnapshot']={'namespace/kube-system':'original-uid'}
            trial.core_snapshot=lambda:{'namespace/kube-system':'replacement-uid'}
            def failed_capture(*args,**kwargs):
                raise PermissionError('PRIVATE_DIAGNOSTIC_SENTINEL')
            trial.capture_retained_validation=failed_capture
            try:
                trial.core_unchanged()
            except ValueError as error:
                self.assertEqual(str(error),'retained Core identity/config changed')
                F.write(folder,error)
            else:self.fail('Core drift must fail')
            secondary=folder/'retained-diagnostic-callsite'/F.NAME
            original=secondary.read_bytes()
            self.assertEqual(secondary.stat().st_mode & 0o777,0o600)
            self.assertEqual(F.public(folder)['exceptionType'],'ValueError')
            self.assertEqual(F.public(secondary.parent)['exceptionType'],'PermissionError')
            result=S.failure_categories(root,{'ownerSteps':[]})
            self.assertEqual(result['identityFailures'][0]['category'],'guard-rejection')
            self.assertEqual(result['identityDiagnosticFailures'][0]['category'],'filesystem')
            self.assertNotIn('PRIVATE_DIAGNOSTIC_SENTINEL',json.dumps(result))
            self.assertIs(trial.state['accepted'],False)
            with self.assertRaises(ValueError):trial.core_unchanged()
            self.assertEqual(secondary.read_bytes(),original)
            payload=json.loads(original);payload['frames'][0]['sourceSHA256']='0'*64
            secondary.write_text(json.dumps(payload))
            self.assertNotIn('identityDiagnosticFailures',S.failure_categories(root,{'ownerSteps':[]}))
            self.assertEqual(F.public(folder)['exceptionType'],'ValueError')
            with patch.object(F,'write',side_effect=RuntimeError('PRIVATE_SECONDARY_SENTINEL')):
                with self.assertRaisesRegex(ValueError,'retained Core identity/config changed'):
                    trial.core_unchanged()

    def error(self):
        try:
            P.D.require(False, 'SECRET_SENTINEL https://private/?sig=SECRET_SENTINEL')
        except ValueError as error:
            return error

    def test_capture_contains_only_reviewed_lines_hashes_and_fixed_type(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=source_bytes):
            value = F.capture(self.error())
            self.assertEqual(value['status'], 'captured')
            self.assertEqual(value['exceptionType'], 'ValueError')
            self.assertTrue(value['frames'])
            self.assertNotIn('SECRET_SENTINEL', json.dumps(value))
            for frame in value['frames']:
                self.assertEqual(set(frame), {'file', 'line', 'sourceSHA256'})
                self.assertIn(frame['file'], F.FILES)
                self.assertEqual(frame['sourceSHA256'], hashlib.sha256(source_bytes(frame['file'])).hexdigest())

    def test_exception_str_is_never_called_and_unknown_type_is_fixed(self):
        class PrivateError(Exception):
            def __str__(self): raise AssertionError('exception string must not be evaluated')
        with patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=source_bytes):
            value = F.capture(PrivateError('SECRET_SENTINEL'))
            self.assertEqual(value['exceptionType'], 'Other')
            self.assertEqual(value['status'], 'unavailable')
            self.assertEqual(value['frames'], [])

    def test_first_private_capture_is_not_overwritten_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=source_bytes):
            root = Path(directory); root.chmod(0o700)
            F.write(root, self.error()); path = root/F.NAME; original = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            F.write(root, KeyError('other secret')); self.assertEqual(path.read_bytes(), original)
            self.assertEqual(F.public(root)['status'], 'captured')
            for defect in ('payload', 'line', 'hash', 'source', 'run', 'oversized', 'boolean-schema'):
                value = json.loads(original)
                if defect == 'boolean-schema': value['schema'] = True
                if defect == 'payload': value['secret'] = 'SECRET_SENTINEL'
                if defect == 'line': value['frames'][0]['line'] = 2**60
                if defect == 'hash': value['frames'][0]['sourceSHA256'] = '0'*64
                if defect == 'source': value['frames'][0]['file'] = '/private/SECRET_SENTINEL'
                if defect == 'run': value['runID'] = '999'
                path.write_text(' '*(F.LIMIT+1) if defect == 'oversized' else json.dumps(value))
                with self.assertRaises((ValueError, OSError)): F.public(root)
            path.write_bytes(original)
            path.unlink(); path.symlink_to('/dev/null')
            with self.assertRaises(ValueError): F.public(root)

    def test_reviewed_source_must_match_actual_HEAD_and_checkout(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(F.subprocess, 'run', side_effect=mocked_git):
            self.assertEqual(F.reviewed('tests/workload-identities/drive.py'), source_bytes('tests/workload-identities/drive.py'))
            with patch.object(F.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'other-source', b'')):
                with self.assertRaises(ValueError): F.reviewed('tests/workload-identities/drive.py')
        with patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=ValueError('SECRET_SENTINEL')):
            value = F.capture(self.error())
            self.assertEqual(value['status'], 'unavailable')
            self.assertNotIn('SECRET_SENTINEL', json.dumps(value))

    def test_wrapper_captures_preflight_before_trial_id_without_printing_cause(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=source_bytes), patch.object(P, 'cli_preflight', side_effect=ValueError('SECRET_SENTINEL')):
            path = Path(directory)/'journal.json'
            with patch('sys.argv', ['package_roundtrip.py', 'round-trip', '--evidence', str(path)]), self.assertRaises(SystemExit) as caught:
                P.main()
            self.assertNotIn('SECRET_SENTINEL', str(caught.exception))
            self.assertFalse(path.exists())
            self.assertEqual(F.public(path.parent)['status'], 'captured')

    def test_wrapper_does_not_resolve_symlink_parent_before_failure_guard(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True), patch.object(F, 'reviewed', side_effect=source_bytes), patch.object(P, 'cli_preflight', side_effect=ValueError('SECRET_SENTINEL')):
            root = Path(directory)
            outside = root/'outside'; outside.mkdir(mode=0o700)
            link = root/'linked'; link.symlink_to(outside, target_is_directory=True)
            with patch('sys.argv', ['package_roundtrip.py', 'round-trip', '--evidence', str(link/'journal.json')]), self.assertRaises(SystemExit):
                P.main()
            self.assertFalse((outside/F.NAME).exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_actual_shell_cheap_preflight_captures_before_any_cluster_action(self):
        # Real shell + Python wrapper + HEAD verification; only uds --help is a
        # fake capability peer. No chart, package, Kubernetes or cluster runs.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); binary = root/'bin'; binary.mkdir()
            calls = root/'uds-calls'
            uds = binary/'uds'
            uds.write_text('#!/usr/bin/env bash\nset -euo pipefail\nprintf "%s\\n" "$*" >> "${FAKE_UDS_CALLS}"\n'
                           '[[ "$*" == "zarf package deploy --help" ]] || exit 88\n'
                           'printf "  --confirm Confirms\\n  PRIVATE_HELP_SENTINEL\\n"\n')
            uds.chmod(0o700)
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            env = {**os.environ, **ENV, 'GITHUB_SHA': head, 'SCENARIO': 'identities',
                   'IDENTITY_METHOD': 'package', 'RUNNER_TEMP': str(root/'runner'),
                   'PATH': str(binary)+os.pathsep+os.environ['PATH'], 'FAKE_UDS_CALLS': str(calls)}
            child = subprocess.run(['bash', str(ROOT/'.github/scripts/staged-migrations.sh')],
                                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(child.returncode, 0)
            self.assertEqual(calls.read_text().splitlines(), ['zarf package deploy --help'])
            folder = root/'runner/staged-migrations/package-identity'
            self.assertFalse((folder/'journal.json').exists())
            self.assertTrue((folder/F.NAME).is_file())
            self.assertNotIn('PRIVATE_HELP_SENTINEL', child.stdout+child.stderr+(folder/F.NAME).read_text())
            with patch.dict(os.environ, env, clear=True):
                proof = F.public(folder)
                self.assertEqual(proof['status'], 'captured')
                self.assertTrue(any(frame['file'].endswith('package_roundtrip.py') for frame in proof['frames']))
                value = S.publish(folder.parent, root/'public', 'amd64')
            self.assertFalse(value['accepted'])
            diagnostic = json.loads((root/'public/proofs/amd64/failure-categories.json').read_text())
            self.assertEqual(diagnostic['identityFailures'][0]['callsite'], proof)
            self.assertNotIn('PRIVATE_HELP_SENTINEL', ''.join(p.read_text() for p in (root/'public').rglob('*.json')))

    def test_package_command_progress_never_exports_private_streams(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{**ENV,'IDENTITY_METHOD':'package'},clear=True):
            root=Path(directory);folder=root/'package-identity';folder.mkdir()
            instance=P.D.Driver(folder/'journal.json')
            instance.state['guard']={field:ENV[env] for field,env in [('sourceSHA','GITHUB_SHA'),('runID','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
            fixed={'role':'deploy','phase':'transition','exitStatus':7,'timedOut':False,'category':'unknown','stdoutPresent':True,'stderrPresent':True}
            instance.journal('package-command-failed',**fixed,stderr='SECRET',stdout='SECRET',argv='SECRET')
            value=S.identity_progress(root)['package']
            self.assertEqual(value['stages'],[{'stage':'package-command-failed',**fixed}]);self.assertNotIn('SECRET',json.dumps(value))
            for field,replacement in [('exitStatus',True),('category','SECRET'),('role','foreign'),('timedOut',1)]:
                instance.state['stages']=[];instance.journal('package-command-failed',**{**fixed,field:replacement})
                self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')

    def test_driver_journals_rejected_verdict_before_failclosed_guard(self):
        from tests.test_identity_phase_evidence import fixture
        bind,data=fixture()
        with tempfile.TemporaryDirectory() as directory:
            instance=P.D.Driver(Path(directory)/'journal.json')
            instance.state.update(guard={k:bind[k] for k in ('sourceSHA','runID','runAttempt','clusterUID')},
                meshConfigUID=bind['meshConfigUID'],meshConfigHash=bind['meshConfigHash'],baselineNetwork=data['baseline_network'],
                deploymentUIDs=data['baseline_uids'],templateFingerprints=data['template_fingerprints'],
                peprUIDs=data['pepr_uids'],peprTemplateFingerprints=data['pepr_template_fingerprints'])
            instance._last_policy_observation={key:data[key] for key in ('package','policies','network_policies','policy_lists')}
            instance._last_identity_observation={key:data[key] for key in ('deployments','replicasets','pods')}
            instance._last_pepr_observation=data['pepr']
            instance.wait=lambda callback:callback();instance.policies=lambda:None;instance.identities=lambda account:None;instance.observe_pepr=lambda phase:None
            instance.observe_render_inputs=lambda:data['render_inputs']
            diagnostic={'scope':'replay','step':'application_guard','reason':'guard_rejected'}
            with patch.object(P.D.phase_evidence,'validate_phase',return_value={'accepted':False,'diagnostic':diagnostic}):
                with self.assertRaisesRegex(ValueError,'typed identity phase evidence is insufficient'):instance.capture_phase('strict','dedicated')
            self.assertEqual(instance.state['stages'][-1],{'stage':'typed-phase-rejected','phase':'strict','diagnostic':diagnostic})
            self.assertFalse(instance.state['accepted']);self.assertFalse((Path(directory)/'phases').exists())

    def test_typed_phase_rejection_progress_exports_only_closed_helper_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{**ENV,'IDENTITY_METHOD':'package'},clear=True):
            root=Path(directory);folder=root/'package-identity';folder.mkdir()
            instance=P.D.Driver(folder/'journal.json')
            instance.state['guard']={field:ENV[env] for field,env in [('sourceSHA','GITHUB_SHA'),('runID','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
            diagnostic={'scope':'capture','step':'policy_projection','reason':'unsupported_policy_condition'}
            instance.journal('typed-phase-rejected',phase='baseline',diagnostic=diagnostic,private='SECRET')
            value=S.identity_progress(root)['package']
            self.assertEqual(value['stages'],[{'stage':'typed-phase-rejected','phase':'baseline','diagnostic':diagnostic}])
            self.assertNotIn('SECRET',json.dumps(value))
            for changed in [{**diagnostic,'reason':'PRIVATE_SECRET'},{**diagnostic,'scope':'foreign'},
                            {**diagnostic,'step':'PRIVATE_PATH'},{**diagnostic,'stderr':'PRIVATE_SECRET'}]:
                instance.state['stages']=[];instance.journal('typed-phase-rejected',phase='baseline',diagnostic=changed)
                value=S.identity_progress(root)['package']
                self.assertEqual(value['status'],'unavailable');self.assertNotIn('PRIVATE',json.dumps(value))

    def test_compact_progress_binds_large_private_journal_without_acceptance(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{**ENV,'IDENTITY_METHOD':'package'},clear=True):
            root=Path(directory);folder=root/'package-identity';folder.mkdir()
            instance=P.D.Driver(folder/'journal.json')
            instance.state['guard']={field:ENV[env] for field,env in [('sourceSHA','GITHUB_SHA'),('runID','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
            instance.state['private']='PRIVATE_SECRET'*30000
            for _ in range(130):instance.journal('preflight',private='SECRET')
            instance.journal('protocol-result',protocol='postgres',controlRole='wrong-identity',outerExit=0,stdoutCategory='transport-rejected',stderrPresent=False,stderr='SECRET')
            companion=folder/'journal-progress.json';saved=companion.read_text()
            self.assertGreater(instance.evidence.stat().st_size,256*1024);self.assertLess(companion.stat().st_size,256*1024)
            self.assertNotIn('SECRET',saved)
            value=S.identity_progress(root)['package']
            self.assertEqual(value['status'],'observed');self.assertTrue(value['truncated']);self.assertEqual(value['retainedCount'],128)
            self.assertEqual(value['lastProtocol']['protocol-result']['stdoutCategory'],'transport-rejected')
            for field in ('sourceSHA','runID'):
                value=json.loads(saved);value['guard'][field]='tampered';companion.write_text(json.dumps(value))
                self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')
            for key,replacement in [('schema',True),('totalCount',4097)]:
                value=json.loads(saved);value[key]=replacement;companion.write_text(json.dumps(value))
                self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')
            companion.unlink();target=folder/'other.json';target.write_text(saved);companion.symlink_to(target)
            self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')
            companion.unlink();companion.write_text(saved)
            with patch.object(S,'sha',side_effect=AssertionError('must reuse bounded streamed hash')):
                self.assertEqual(S.identity_progress(root)['package']['status'],'observed')
            companion.write_text(saved);instance.evidence.write_text(instance.evidence.read_text()+' ')
            self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')
            companion.unlink();self.assertEqual(S.identity_progress(root)['package']['status'],'unavailable')

    def test_sentinel_progress_exports_only_reviewed_typed_facts(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{**ENV,'IDENTITY_METHOD':'package'},clear=True):
            root=Path(directory);folder=root/'package-identity';folder.mkdir()
            guard={field:ENV[env] for field,env in [('sourceSHA','GITHUB_SHA'),('runID','GITHUB_RUN_ID'),('runAttempt','GITHUB_RUN_ATTEMPT')]}
            stage={'stage':'retained-sentinel-exec','operation':'create','namespace':'cloudtak','exitStatus':63,'stderrPresent':True}
            def progress(entries):
                (folder/'journal.json').write_text(json.dumps({'guard':guard,'stages':entries}))
                return S.identity_progress(root)['package']
            start={'stage':'retained-sentinel-start','operation':'create','namespace':'cloudtak'}
            leaked={**stage,**{key:'PRIVATE_SENTINEL' for key in ('pod','path','stdout','stderr','argv')}}
            self.assertEqual(progress([start,leaked])['stages'],[start,stage])
            for key,value in [('operation','foreign'),('namespace','kube-system'),('exitStatus',True),('exitStatus',256),('exitStatus','63'),('stderrPresent',1)]:
                with self.subTest(key=key,value=value):
                    self.assertEqual(progress([{**stage,key:value}]),{'status':'unavailable','stages':[],'reason':'invalid-stage-diagnostic'})
            self.assertEqual(progress([{**stage,'exitStatus':None}])['stages'][0]['exitStatus'],None)

    def test_package_failure_progress_and_callsites_publish_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {**ENV, 'SCENARIO': 'identities', 'IDENTITY_METHOD': 'package'}, clear=True), patch.object(S.platform, 'machine', return_value='x86_64'), patch.object(F, 'reviewed', side_effect=source_bytes):
            root = Path(directory); folder = root/'package-identity'; folder.mkdir(mode=0o700)
            journal = {'guard': {field: ENV[env] for field, env in [('sourceSHA', 'GITHUB_SHA'), ('runID', 'GITHUB_RUN_ID'), ('runAttempt', 'GITHUB_RUN_ATTEMPT')]},
                       'accepted': False, 'stages': [{'stage': 'created', 'private': 'SECRET_SENTINEL'} for _ in range(220)] + [{'stage': 'preflight'},
                         {'stage': 'package-deploy-start', 'phase': 'transition', 'secret': 'SECRET_SENTINEL'},
                         {'stage': 'stopped', 'message': 'SECRET_SENTINEL'}, {'stage': 'SECRET_SENTINEL'}]}
            (folder/'journal.json').write_text(json.dumps(journal)); F.write(folder, self.error())
            with patch.object(subprocess, 'run', side_effect=mocked_git):
                value = S.publish(root, root/'public', 'amd64')
            self.assertFalse(value['accepted'])
            progress = json.loads((root/'public/proofs/amd64/progress.json').read_text())
            self.assertEqual(progress['identityStages'], ['preflight', 'package-deploy-start', 'stopped'])
            self.assertEqual(progress['identityMethods']['package']['stages'][1], {'stage': 'package-deploy-start', 'phase': 'transition'})
            diagnostic = json.loads((root/'public/proofs/amd64/failure-categories.json').read_text())
            self.assertEqual(diagnostic['identityFailures'][0]['category'], 'guard-rejection')
            self.assertEqual(diagnostic['identityFailures'][0]['callsite']['frames'], F.capture(self.error())['frames'])
            self.assertFalse((root/'public/proofs/amd64/identity-phases.json').exists())
            self.assertNotIn('SECRET_SENTINEL', ''.join(p.read_text() for p in (root/'public').rglob('*.json')))

    def test_before_journal_failure_and_selected_method_progress_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {**ENV, 'SCENARIO': 'identities', 'IDENTITY_METHOD': 'combined'}, clear=True), patch.object(S.platform, 'machine', return_value='x86_64'), patch.object(F, 'reviewed', side_effect=source_bytes):
            root = Path(directory); folder = root/'package-identity'; folder.mkdir(mode=0o700); F.write(folder, self.error())
            with patch.object(subprocess, 'run', side_effect=mocked_git): value = S.publish(root, root/'public', 'amd64')
            progress = json.loads((root/'public/proofs/amd64/progress.json').read_text())
            self.assertEqual(set(progress['identityMethods']), {'manual', 'package'})
            self.assertTrue(all(m['status'] == 'unavailable' for m in progress['identityMethods'].values()))
            diagnostic = json.loads((root/'public/proofs/amd64/failure-categories.json').read_text())
            self.assertEqual([item['method'] for item in diagnostic['identityFailures']], ['package'])
            self.assertFalse(value['accepted'])
