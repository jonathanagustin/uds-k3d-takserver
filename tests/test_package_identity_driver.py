# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline command and fail-closed guards; never live identity acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import stat
import time
import signal
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_trial',ROOT/'tests/workload-identities/package_roundtrip.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)

class PackageGuards(unittest.TestCase):
    def test_identity_wait_timeout_journals_only_fixed_reason_and_preserves_failure(self):
        for raw, code in [('workload template drift', 'workload-template-drift'),
                          ('inconsistent workload service account alias', 'inconsistent-service-account-alias'),
                          ('private secret server-address value', 'other-invariant')]:
            with self.subTest(code=code):
                trial = object.__new__(P.PackageTrial)
                entries = []
                trial.journal = lambda stage, **fields: entries.append({'stage': stage, **fields})
                def identities(expected):
                    self.assertEqual(expected, 'dedicated')
                    raise ValueError(raw)
                trial.identities = identities
                def wait(callback):
                    try: callback()
                    except ValueError: pass
                    raise ValueError('convergence timeout: ' + raw)
                trial.wait = wait
                with self.assertRaisesRegex(ValueError, 'convergence timeout'):
                    trial.wait_identities('dedicated', 'transition')
                self.assertEqual(entries, [{'stage':'package-identity-timeout', 'phase':'transition', 'diagnostic':code}])
                self.assertNotIn(raw, json.dumps(entries))
        trial = object.__new__(P.PackageTrial)
        trial.identities = lambda expected: ['unchanged-result']
        trial.wait = lambda callback: callback()
        trial.journal = lambda *args, **kwargs: self.fail('successful wait must not journal timeout')
        self.assertEqual(trial.wait_identities('shared', 'rollback'), ['unchanged-result'])
        trial.wait = lambda callback: (_ for _ in ()).throw(ValueError('guard budget exhausted'))
        with self.assertRaisesRegex(ValueError, 'guard budget exhausted'):
            trial.wait_identities('shared', 'rollback')

    def test_identity_timeout_companion_projects_only_fixed_diagnostic(self):
        spec=importlib.util.spec_from_file_location('timeout_projection',ROOT/'.github/scripts/staged-migrations.py')
        publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'IDENTITY_METHOD':'package', 'GITHUB_SHA':'a'*40, 'GITHUB_RUN_ID':'123', 'GITHUB_RUN_ATTEMPT':'1'}):
            root=Path(directory);folder=root/'package-identity';folder.mkdir()
            trial=object.__new__(P.PackageTrial);trial.evidence=folder/'journal.json'
            trial.state={'schema':1,'stages':[], 'guard':{'sourceSHA':'a'*40,'runID':'123','runAttempt':'1'}}
            trial.identities=lambda expected: (_ for _ in ()).throw(ValueError('PRIVATE_UNKNOWN_SENTINEL'))
            def wait(callback):
                try: callback()
                except ValueError: pass
                raise ValueError('convergence timeout: PRIVATE_UNKNOWN_SENTINEL')
            trial.wait=wait
            with self.assertRaises(ValueError):trial.wait_identities('dedicated','transition')
            public=publisher.identity_progress(root)['package']
            self.assertEqual(public['status'],'observed')
            self.assertEqual(public['stages'],[{'stage':'package-identity-timeout','phase':'transition','diagnostic':'other-invariant'}])
            self.assertNotIn('PRIVATE_UNKNOWN_SENTINEL',json.dumps(public))
            for phase in ('shared','transition','strict','rollback'):
                trial.state['stages']=[]
                with self.assertRaises(ValueError):trial.wait_identities('dedicated',phase)
                projected=publisher.identity_progress(root)['package']
                self.assertEqual(projected['status'],'observed')
                self.assertEqual(projected['stages'][0]['phase'],phase)
                self.assertEqual(projected['stages'][0]['diagnostic'],'other-invariant')
            # Even a source/run-bound companion must reject an arbitrary diagnostic.
            trial.journal('package-identity-timeout',phase='transition',diagnostic='PRIVATE_UNKNOWN_SENTINEL')
            public=publisher.identity_progress(root)['package']
            self.assertEqual(public['status'],'unavailable')
            self.assertNotIn('PRIVATE_UNKNOWN_SENTINEL',json.dumps(public))

    def test_retained_validation_capture_is_typed_first_and_preserves_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);folder.chmod(0o700)
            trial=object.__new__(P.PackageTrial);trial.evidence=folder/'journal.json'
            trial.state={'schema':1,'accepted':False,'method':'package','stages':[],
                         'guard':{'sourceSHA':'a'*40,'runID':'123','runAttempt':'1'}}
            snapshot={'schema':1,'baseline':None,'observed':None,'baselineObjects':None,'observedObjects':None,
                      'diagnostic':{'hook':'inventory','category':'inventory','fieldClass':'inventory'}}
            original=ValueError('original retained validation failed')
            def verify(driver,proof):
                driver._retained_source_failure=snapshot
                raise original
            with patch.object(P.R,'verify',side_effect=verify):
                with self.assertRaises(ValueError) as failure:trial.retained_verify({},'transition')
            self.assertIs(failure.exception,original)
            private=folder/P.VALIDATION_FAILURE;plain=private.read_bytes();payload=json.loads(plain)
            self.assertEqual(payload['type'],'retained-source-validation')
            self.assertEqual(payload['kind'],'stored-hooks-drift');self.assertEqual(payload['snapshot'],snapshot)
            self.assertNotIn('stdout',payload);self.assertNotIn('exitStatus',payload)
            self.assertEqual(private.stat().st_mode&0o777,0o600)
            self.assertEqual(trial.state['firstPrivateFailure']['kind'],'retained-source-validation')
            trial.capture_retained_validation(snapshot,'rollback')
            self.assertTrue(private.read_bytes()==plain)
            self.assertIsNone(trial._retained_source_failure)
        with tempfile.TemporaryDirectory() as directory:
            trial=object.__new__(P.PackageTrial);trial.evidence=Path(directory)/'journal.json'
            trial.state={'packageCommandFailure':{'file':P.PACKAGE_FAILURE}}
            trial.capture_retained_validation(snapshot,'transition')
            self.assertFalse((Path(directory)/P.VALIDATION_FAILURE).exists())

    @unittest.skipUnless(__import__('shutil').which('helm'),'existing Helm required for real hook source render')
    def test_real_retained_verify_journal_companion_public_projection_never_exports_hook_bodies(self):
        import copy
        spec=importlib.util.spec_from_file_location('retained_projection',ROOT/'.github/scripts/staged-migrations.py')
        publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        raw=subprocess.check_output(['helm','template','uds-takserver-config',str(ROOT/'charts/takserver'),
                                     '--namespace','takserver'],timeout=20)
        objects=[obj for obj in yaml.safe_load_all(raw) if isinstance(obj,dict) and
                 obj.get('metadata',{}).get('annotations',{}).get('helm.sh/hook')]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'IDENTITY_METHOD':'package',
                'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}):
            root=Path(directory);folder=root/'package-identity';folder.mkdir(mode=0o700)
            trial=object.__new__(P.PackageTrial);trial.evidence=folder/'journal.json'
            trial.state={'schema':1,'method':'package','accepted':False,'stages':[],
                         'guard':{'sourceSHA':'a'*40,'runID':'123','runAttempt':'1'}}
            trial.command=lambda *args,**kwargs:yaml.safe_dump_all(objects)
            baseline=P.R.hooks(trial)
            # Seed only the ephemeral body cache populated by capture(); no cluster/PVC work.
            trial._retained_hook_baseline={'inventorySHA256':P.R.sha(baseline['hookInventory']),
                                          'objects':copy.deepcopy(objects)}
            changed=copy.deepcopy(objects)
            job=next(obj for obj in changed if obj['kind']=='Job')
            job['spec']['template']['spec']['containers'][0]['image']='PRIVATE_HOOK_IMAGE_SENTINEL'
            trial.command=lambda *args,**kwargs:yaml.safe_dump_all(changed)
            with self.assertRaisesRegex(ValueError,'stored source generator/hook changed'):
                trial.retained_verify({'source':baseline,'records':[]},'transition')
            private=(folder/P.VALIDATION_FAILURE).read_text()
            self.assertIn('PRIVATE_HOOK_IMAGE_SENTINEL',private)
            result=publisher.identity_progress(root)['package']
            self.assertEqual(result['status'],'observed')
            self.assertEqual(result['stages'],[{'stage':'retained-hook-drift','hook':'cert-job',
                                               'category':'generator','fieldClass':'job-spec'}])
            for value in (trial.evidence.read_text(),(folder/'journal-progress.json').read_text(),json.dumps(result)):
                self.assertNotIn('PRIVATE_HOOK_IMAGE_SENTINEL',value)
                self.assertNotIn('baselineObjects',value);self.assertNotIn('observedObjects',value)
            for field in ('hook','category','fieldClass'):
                trial.state['stages']=[]
                diagnostic={'hook':'cert-job','category':'generator','fieldClass':'job-spec'}
                diagnostic[field]='PRIVATE_PROJECTION_SENTINEL'
                trial.journal('retained-hook-drift',**diagnostic)
                rejected=publisher.identity_progress(root)['package']
                self.assertEqual(rejected['status'],'unavailable')
                self.assertNotIn('PRIVATE_PROJECTION_SENTINEL',json.dumps(rejected))
            trial.state['stages']=[]
            trial.journal('retained-hook-drift',hook='cert-job',category='credential',fieldClass='job-spec')
            self.assertEqual(publisher.identity_progress(root)['package']['status'],'unavailable')

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.phase_directory=Path(directory.name)
        self.charts=P.D.render_inputs.baseline_chart_values({},lambda path:{})
        self.charts['takserver']['takserver']={'postgresql':{'primary':{'persistence':{'size':'1Gi'},'resources':{'limits':{'memory':'512Mi'}}}}}
        self.phase_values={}
        for phase in P.D.PHASES:
            path=self.phase_directory/(phase+'.yaml')
            path.write_text(yaml.safe_dump({'chartOverrides':self.charts,'tak':{'workloadIdentityPhase':phase}}));path.chmod(0o600)
            self.phase_values[phase]={'path':str(path),'sha256':P.digest(path)}

    def bound(self):return {'archive':'/owned/zarf-package-takserver-amd64-dev-upstream.tar.zst','archiveSHA256':'a'*64,'planSHA256':'b'*64,'configSHA256':'c'*64,
                           'chartBinding':{'chartOverrides':self.charts,'chartOverridesSHA256':P.D.render_inputs.digest(self.charts)},'phaseValues':self.phase_values,
                           'variables':{'DOMAIN':'uds.dev','TAK_IMAGE_TAG':'reviewed','FILESYSTEM_BACKUP':'true','POSTGRES_STORAGE_CLASS':'local-path-local','CLOUDTAK_STORAGE_CLASS':'local-path-local'}}
    def test_exec_dispatches_bound_application_namespace_and_container(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.guard=lambda:None
            instance.get=lambda *a,**kw:{'metadata':{},'spec':{'containers':[{'name':'postgres'}]}}
            with patch.object(P.D.subprocess,'run') as run:
                for namespace in ('takserver','cloudtak'):
                    instance.exec('db-0','postgres',['true'],namespace=namespace)
                    argv=run.call_args.args[0]
                    self.assertEqual(argv[argv.index('-n')+1],namespace)
                    self.assertEqual(argv[argv.index('-c')+1],'postgres')
                instance.exec('db-0','postgres',['true'])
                self.assertEqual(run.call_args.args[0][9],'takserver')
                before=run.call_count
                for namespace,container in [('kube-system','postgres'),('cloudtak','unknown')]:
                    with self.assertRaises(ValueError):instance.exec('db-0',container,['true'],namespace=namespace)
                self.assertEqual(run.call_count,before)

    def test_bounded_package_subprocess_limits_output_and_marks_timeout(self):
        result=P.bounded_package_run([sys.executable,'-c',"import sys;sys.stdout.write('SECRET'*20000);sys.stderr.write('private failure');sys.exit(7)"],5)
        self.assertEqual(result['exitStatus'],7);self.assertTrue(result['stdoutTruncated']);self.assertLessEqual(len(result['stdout']),16384)
        timeout=P.bounded_package_run([sys.executable,'-c','import time;time.sleep(5)'],0.01)
        self.assertTrue(timeout['timedOut']);self.assertNotEqual(timeout['exitStatus'],0)

    def test_package_output_replacement_remains_bounded_after_utf8_encoding(self):
        result=P.bounded_package_run([sys.executable,'-c',"import os;os.write(1,bytes([255])*16384)"],5)
        self.assertEqual(result['exitStatus'],0);self.assertTrue(result['stdoutTruncated'])
        self.assertLessEqual(len(result['stdout'].encode('utf-8')),16384)
        self.assertTrue(result['stdout']);self.assertEqual(set(result['stdout']),{'\ufffd'})

    def test_package_timeout_bounds_escaped_pipe_holder_and_closed_pipe_child(self):
        # Start the production timeout only once the owned escaped pipe holder
        # exists. Interpreter startup time is not the behavior under test.
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/'pid'
            script="import time; time.sleep(10)"
            launcher=("import subprocess,sys,time,pathlib; child=subprocess.Popen([sys.executable,'-c',"+
                      repr(script)+"],start_new_session=True); pathlib.Path("+repr(str(pidfile))+
                      ").write_text(str(child.pid)); time.sleep(10)")
            original=P.subprocess.Popen;ready=[];owned=[]
            def start_ready(*args,**kwargs):
                child=original(*args,**kwargs)
                try:
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        value=pidfile.read_text().strip() if pidfile.exists() else ''
                        if value.isdigit():
                            owned.append(int(value));ready.append(time.monotonic());return child
                        time.sleep(0.01)
                    self.fail('owned detached pipe holder did not become ready')
                except BaseException:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    child.wait(timeout=5)
                    for stream in (child.stdout,child.stderr):stream.close()
                    raise
            try:
                with patch.object(P.subprocess,'Popen',side_effect=start_ready):
                    result=P.bounded_package_run([sys.executable,'-c',launcher],0.5)
                self.assertTrue(result['timedOut']);self.assertLess(time.monotonic()-ready[0],2)
                self.assertEqual(os.getpgid(owned[0]),owned[0])
                os.kill(owned[0],0)
                self.assertNotEqual(Path('/proc/'+str(owned[0])+'/stat').read_text().split(') ',1)[1].split()[0],'Z')
            finally:
                if owned:
                    try:os.kill(owned[0],signal.SIGKILL)
                    except ProcessLookupError:pass
        started=time.monotonic()
        result=P.bounded_package_run([sys.executable,'-c','import os,time;os.close(1);os.close(2);time.sleep(10)'],0.05)
        self.assertTrue(result['timedOut']);self.assertNotEqual(result['exitStatus'],0)
        self.assertLess(time.monotonic()-started,2)

    def test_package_command_failure_private_first_only_and_fixed_public_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700)
            instance=P.PackageTrial(root/'journal.json',self.bound())
            instance.state['guard']={'sourceSHA':'a'*40,'runID':'1','runAttempt':'1'}
            instance.guard=lambda:None;instance.inputs_unchanged=lambda:None;instance.core_unchanged=lambda:None
            instance.command=lambda *a,**kw:P.D.CONTEXT
            result={'exitStatus':7,'timedOut':False,'stdout':'SECRET_OUT','stderr':'UPGRADE FAILED SECRET_ERROR',
                    'stdoutTruncated':False,'stderrTruncated':False}
            with patch.object(P,'bounded_package_run',return_value=result):
                with self.assertRaises(ValueError):instance.run_package(P.deploy_command(instance.bound,'transition'),5)
            target=root/P.PACKAGE_FAILURE;first=target.read_bytes();payload=json.loads(first)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600);self.assertEqual(payload['binding'],instance.state['guard'])
            self.assertEqual(payload['stderr'],result['stderr']);self.assertLessEqual(len(first),65536)
            stage=instance.state['stages'][-1];self.assertEqual(stage['category'],'helm-upgrade');self.assertNotIn('SECRET',json.dumps(stage))
            self.assertNotIn('SECRET',(root/'journal-progress.json').read_text())
            result['stderr']='DIFFERENT'
            with patch.object(P,'bounded_package_run',return_value=result):
                with self.assertRaises(ValueError):instance.run_package(P.deploy_command(instance.bound,'strict'),5)
            self.assertEqual(target.read_bytes(),first)
            target.unlink();foreign=root/'foreign';foreign.write_text('untouched');target.symlink_to(foreign)
            with patch.object(P,'bounded_package_run',return_value=result):
                with self.assertRaises(ValueError):instance.run_package(P.deploy_command(instance.bound,'strict'),5)
            self.assertEqual(foreign.read_text(),'untouched')

    def test_only_legacy_upstream_chart_uses_client_side_apply_compatibility(self):
        package=yaml.safe_load((ROOT/'common/zarf.yaml').read_text())
        charts=[chart for component in package['components'] for chart in component.get('charts',[])]
        legacy=[chart for chart in charts if chart.get('serverSideApply')=='false']
        self.assertEqual(len(legacy),1)
        chart=legacy[0]
        self.assertEqual((chart['name'],chart['namespace'],chart['releaseName']),('takserver','takserver','takserver'))
        self.assertEqual(chart['url'],'https://github.com/TAK-Product-Center/Server.git')
        self.assertEqual(chart['version'],'5.7-RELEASE-14')
        self.assertTrue(all('serverSideApply' not in item for item in charts if item is not chart))
        self.assertIs(type(chart['serverSideApply']),str)
        for phase in P.PHASES:self.assertNotIn('--force-conflicts',P.deploy_command(self.bound(),phase))

    def test_same_archive_and_values_only_phase_changes(self):
        commands=[P.deploy_command(self.bound(),phase) for phase in P.PHASES]
        stripped=[]
        for command in commands:
            command=command.copy();command[command.index('--values')+1]='bound-phase-file';stripped.append(command)
        self.assertTrue(all(c==stripped[0] for c in stripped));self.assertTrue(all(c[4]==self.bound()['archive'] for c in commands))
        for command,phase in zip(commands,P.PHASES):
            value=yaml.safe_load(Path(command[command.index('--values')+1]).read_text())
            self.assertEqual(value,{'chartOverrides':self.charts,'tak':{'workloadIdentityPhase':phase}})
        self.assertNotIn('--set-values',commands[0])
        self.assertNotIn('--force-conflicts',commands[0])
        with self.assertRaises(ValueError):P.deploy_command(self.bound(),'unknown')
    def test_cli_capabilities_fail_before_any_deployment(self):
        calls=[]
        def help(argv):
            calls.append(argv)
            return (ROOT/'tests/workload-identities/fixtures'/('uds-0.41.0-'+argv[3]+'-flags.txt')).read_text()
        P.cli_preflight(help);self.assertEqual([x[3] for x in calls],['deploy','remove'])
        self.assertTrue(all(x[-1]=='--help' for x in calls))
        with self.assertRaisesRegex(ValueError,'--features, --values'):P.cli_preflight(lambda argv:'  -c, --confirm  Confirms\n      --set-variables stringToString Variables\n')
        with self.assertRaisesRegex(ValueError,'--values'):
            P.cli_preflight(lambda argv:'\n'.join(line for line in help(argv).splitlines() if ', --values ' not in line))

    def test_phase_file_hash_and_private_modes_are_checked_without_rewriting(self):
        bound=self.bound();path=Path(bound['phaseValues']['strict']['path']);raw=path.read_bytes()
        path.chmod(0o644)
        with self.assertRaises(ValueError):P.deploy_command(bound,'strict')
        path.chmod(0o600);path.parent.chmod(0o755)
        with self.assertRaises(ValueError):P.deploy_command(bound,'strict')
        path.parent.chmod(0o700);path.unlink();foreign=path.parent/'foreign';foreign.write_bytes(raw);path.symlink_to(foreign)
        with self.assertRaises(ValueError):P.deploy_command(bound,'strict')
        self.assertTrue(path.is_symlink());self.assertEqual(foreign.read_bytes(),raw)

    def test_real_package_capture_preserves_config_binding_through_public_replay(self):
        from tests.test_identity_phase_evidence import fixture,evidence
        from tests.test_identity_public_evidence import IdentityPublicationTests
        from tests.test_staged_migrations import S
        bind,data=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);capture_dir=root/'captured';capture_dir.mkdir(mode=0o700)
            bound=self.bound();bound.update(archiveSHA256='d'*64,planSHA256='e'*64,configSHA256='f'*64)
            instance=P.PackageTrial(capture_dir/'journal.json',bound)
            instance.state.update(guard={k:bind[k] for k in ('sourceSHA','runID','runAttempt','clusterUID')},
                meshConfigUID=bind['meshConfigUID'],meshConfigHash=bind['meshConfigHash'],baselineNetwork=data['baseline_network'],
                deploymentUIDs=data['baseline_uids'],templateFingerprints=data['template_fingerprints'],
                peprUIDs=data['pepr_uids'],peprTemplateFingerprints=data['pepr_template_fingerprints'],
                packagePhases=['shared','transition'],zarfDomainBinding={'configSHA256':bound['configSHA256']})
            instance._last_policy_observation={key:data[key] for key in ('package','policies','network_policies','policy_lists')}
            instance._last_identity_observation={key:data[key] for key in ('deployments','replicasets','pods')}
            instance._last_pepr_observation=data['pepr']
            instance.wait=lambda callback:callback();instance.policies=lambda:None;instance.identities=lambda account:None;instance.observe_pepr=lambda phase:None
            instance.observe_render_inputs=lambda:data['render_inputs']
            verdict=instance.capture_phase('strict','dedicated')
            self.assertTrue(verdict['accepted']);self.assertEqual(verdict['binding']['baselineValuesSHA256'],bound['configSHA256'])
            self.assertNotEqual(verdict['binding']['baselineValuesSHA256'],bound['chartBinding']['chartOverridesSHA256'])
            self.assertEqual(instance.state['baselineChartValuesSHA256'],bound['chartBinding']['chartOverridesSHA256'])
            reference=instance.state['phaseEvidence'][0]['reference'];snapshot=evidence.read_phase(capture_dir/'phases',reference)
            self.assertTrue(evidence.validate_phase(snapshot,P.D.guard_api())['accepted'])
            fixture_case=IdentityPublicationTests()
            with fixture_case.env(),patch.dict(os.environ,{'IDENTITY_METHOD':'package'}),patch.object(S.platform,'machine',return_value='x86_64'):
                journal=fixture_case.package_journal(root)
                journal['packageDriverSHA256']=S.sha(ROOT/'tests/workload-identities/package_roundtrip.py')
                entry=next(entry for entry in journal['phaseEvidence'] if entry['phase']=='strict')
                folder=root/'package-identity';(folder/'phases'/entry['reference']['file']).unlink()
                entry['reference']=evidence.write_phase(folder/'phases',snapshot)
                (folder/'journal.json').write_text(json.dumps(journal))
                receipt=S.publish(root,root/'public','amd64')
                self.assertTrue(receipt['accepted']);S.verify(root/'public/receipts')

    def test_actual_deploy_path_dispatches_supported_command_then_observes(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.bound['archiveSHA256']='a'*64
            calls=[];seen=[];instance.guard=lambda:None;instance.inputs_unchanged=lambda:None;instance.core_unchanged=lambda:None;instance.journal=lambda *a,**k:None
            instance.command=lambda argv,**kw:(calls.append(argv) or (P.D.CONTEXT if argv[0]=='kubectl' else ''))
            instance.observe=seen.append
            with patch.object(P,'bounded_package_run',return_value={'exitStatus':0,'timedOut':False,'stdout':'','stderr':'','stdoutTruncated':False,'stderrTruncated':False}) as execute:
                instance.deploy('rollback')
            self.assertEqual(execute.call_args.args[0],P.deploy_command(instance.bound,'rollback'))
            self.assertEqual(seen,['rollback'])
    def test_direct_phase_mutations_cannot_run_in_package_path(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound())
            for operation in [lambda:instance.stage_config('strict'),lambda:instance.stage_admission('strict'),lambda:instance.patch('package',{},'/spec/network/allow',[])]:
                with self.assertRaises(ValueError):operation()
    def test_retained_state_refuses_fresh_install_without_deleting_it(self):
        for kind in ['persistentvolumeclaims','secrets','configmaps','serviceaccounts','deployments']:
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'retained application state'):
                P.require_clean_objects('takserver',kind,[{'metadata':{'name':'retained'}}])
        with self.assertRaises(ValueError):P.require_clean_objects('takserver','configmaps',[{'metadata':{'name':'kube-root-ca.crt'}}])
        P.require_clean_objects('pepr-system','deployments',[{'metadata':{'name':'unrelated-core'}}])
    def test_changed_bound_config_or_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GITHUB_SHA':'a'*40}):
            root=Path(directory);archive=root/'zarf-package-takserver-amd64-dev-upstream.tar.zst';archive.write_bytes(b'owned archive identity fixture, not package')
            config=root/'config.yaml';config.write_text(yaml.safe_dump({'variables':{'takserver':self.bound()['variables']}}));plan=root/'plan.json';plan.write_text(json.dumps({'schema':1,'sourceSHA':'a'*40,'files':{'config':{'path':config.name,'sha256':P.digest(config)}}}))
            expected=P.digest(archive)
            with patch.object(P.D.render_inputs,'bind_chart_overrides',return_value=self.bound()['chartBinding']):
                bound=P.bind_inputs(archive,expected,plan)
            path=Path(bound['phaseValues']['strict']['path']);original=path.read_bytes();path.write_text('tampered')
            with self.assertRaises(ValueError):P.deploy_command(bound,'strict')
            self.assertEqual(path.read_text(),'tampered','command must not regenerate tampered values')
            path.write_bytes(original)
            config.write_text('changed')
            with self.assertRaises(ValueError):P.bind_inputs(archive,expected,plan)
            archive.write_bytes(b'changed')
            with self.assertRaises(ValueError):P.bind_inputs(archive,expected,plan)

    def test_pinned_slim_core_snapshot_preserves_every_observed_identity(self):
        namespaces=['default','kube-system','istio-system','pepr-system','keycloak','velero','takserver','cloudtak']
        app_agent={'metadata':{'name':'node-agent','uid':'app-agent','annotations':{
            'meta.helm.sh/release-name':'uds-takserver-config','meta.helm.sh/release-namespace':'takserver'}}}
        def get(kind,name=None,namespace=None):
            if kind=='namespaces':return {'items':[{'metadata':{'name':ns}} for ns in namespaces]}
            if kind=='namespace':return {'metadata':{'uid':'ns-'+name}}
            if kind=='configmap':return {'data':{'mesh':'bound mesh'}}
            objects=[]
            if kind=='deployments':objects=[{'metadata':{'name':'controller','uid':namespace+'-controller'}}]
            if kind=='daemonsets' and namespace=='velero':objects=[app_agent,{'metadata':{'name':'core-agent','uid':'core-agent'}}]
            return {'items':objects}
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.get=get
            snapshot=instance.core_snapshot()
            self.assertNotIn('namespace/uds-system',snapshot)
            for ns in ('default','kube-system','istio-system','pepr-system','keycloak','velero'):
                self.assertEqual(snapshot['namespace/'+ns],'ns-'+ns)
                self.assertEqual(snapshot[ns+'/deployments/controller'],ns+'-controller')
            self.assertNotIn('velero/daemonsets/node-agent',snapshot)
            self.assertEqual(snapshot['velero/daemonsets/core-agent'],'core-agent')
            self.assertEqual(snapshot['mesh'],P.D.sha({'mesh':'bound mesh'}))
            namespaces.remove('velero')
            self.assertNotIn('namespace/velero',instance.core_snapshot())
            for required in ('kube-system','istio-system','pepr-system','keycloak'):
                namespaces.remove(required)
                with self.subTest(missing=required),self.assertRaisesRegex(ValueError,'required Core namespaces missing'):
                    instance.core_snapshot()
                namespaces.append(required)
            namespaces.append('velero');app_agent['metadata']['annotations']['meta.helm.sh/release-name']='foreign'
            self.assertEqual(instance.core_snapshot()['velero/daemonsets/node-agent'],'app-agent')

    def test_core_identity_change_refuses_before_any_package_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.guard=lambda:None;instance.inputs_unchanged=lambda:None
            instance.state['coreSnapshot']={'namespace/kube-system':'original'}
            instance.core_snapshot=lambda:{'namespace/kube-system':'replacement'}
            calls=[];instance.command=lambda *a,**kw:calls.append(a)
            with self.assertRaisesRegex(ValueError,'Core identity'):instance.run_package(['uds','zarf','package','remove','takserver','--confirm'],900)
            self.assertEqual(calls,[])

    def test_manual_is_default_and_package_is_explicit_identities_only(self):
        spec=importlib.util.spec_from_file_location('selection_guard',ROOT/'.github/scripts/staged-migrations.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main','GITHUB_REPOSITORY':'jonathanagustin/uds-takserver','SCENARIO':'identities','ARCHITECTURE':'amd64'}
        with patch.dict(os.environ,env,clear=True):self.assertEqual(m.selection(),(['identities'],['amd64']))
        for method in ('package','combined'):
            with patch.dict(os.environ,{**env,'IDENTITY_METHOD':method,'FRESH_STRICT':'true'},clear=True):self.assertEqual(m.selection(),(['identities'],['amd64']))
            with patch.dict(os.environ,{**env,'IDENTITY_METHOD':method,'SCENARIO':'all'},clear=True),self.assertRaises(ValueError):m.selection()
        with patch.dict(os.environ,{**env,'FRESH_STRICT':'true'},clear=True),self.assertRaises(ValueError):m.selection()

    def test_workflow_remains_manual_and_preflight_precedes_cluster_bootstrap(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/staged-migrations.yaml').read_text())
        self.assertEqual(set(workflow.get('on',workflow.get(True))),{'workflow_dispatch'})
        inputs=workflow.get('on',workflow.get(True))['workflow_dispatch']['inputs']
        self.assertEqual(inputs['identity_method']['default'],'manual');self.assertFalse(inputs['fresh_strict']['default'])
        shell=(ROOT/'.github/scripts/staged-migrations.sh').read_text()
        self.assertLess(shell.index('package_roundtrip.py preflight'),shell.index('ephemeral-cluster.py bootstrap'))

    def test_observer_keeps_strict_semantics_separate_from_evidence_alias(self):
        for fresh in (False,True):
            with self.subTest(fresh=fresh),tempfile.TemporaryDirectory() as directory:
                instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.state['packagePhases']=['shared','transition'];instance.state['initializingFresh']=fresh
                package={'spec':{'network':{'allow':[]}}};instance.render=lambda phase:(package,[]);instance.get=lambda *a,**k:package
                instance.policies=lambda:None;instance.observe_pepr=lambda phase:None;instance.identities=lambda expected:[];instance.wait=lambda callback:callback();instance.core_unchanged=lambda:None
                instance.command=lambda *a,**k:'{"workloadIdentityPhase":"strict"}'
                calls=[];instance.traffic=lambda identities,phase,**kw:calls.append((phase,kw['evidence_phase']))
                instance.application_checks=lambda **kw:None;instance.capture_phase=lambda *a:None;events=[];instance.journal=lambda *a,**k:events.append((a,k))
                instance.state['dataInvariants']={}
                with patch.object(P.R,'capture',return_value={}),patch.object(P.R,'verify'):
                    instance.observe('strict')
                self.assertEqual(calls,[('strict','package-fresh-strict' if fresh else 'package-strict')])
                self.assertEqual(sum(args[0]=='package-application-checks' for args,kw in events),1)

    def test_actual_cloudtak_task_is_required_at_baseline_strict_and_fresh_strict(self):
        for phase in ('baseline','strict','fresh-strict'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as directory:
                instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.guard=lambda:None;instance.require_cloudtak=lambda:{'namespace':'same','deployment':'same','package':'same'}
                calls=[];events=[];instance.command=lambda argv,**kw:(calls.append(argv) or '')
                instance.journal=lambda stage,**kw:events.append((stage,kw))
                instance.application_checks(phase)
                self.assertIn(['uds','run','test:cloudtak','--no-progress'],calls)
                self.assertIn(('cloudtak-basemap-application-checks',{'phase':phase,'passed':True}),events)
    def test_cloudtak_missing_or_existing_task_skip_cannot_establish_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.guard=lambda:None
            instance.require_cloudtak=lambda:{'namespace':'same'}
            instance.command=lambda argv,**kw:'The cloudtak component is not deployed. Skipping.'
            with self.assertRaisesRegex(ValueError,'skipped'):instance.application_checks('strict')
            instance.require_cloudtak=lambda:(_ for _ in ()).throw(ValueError('missing component'))
            with self.assertRaisesRegex(ValueError,'missing'):instance.application_checks('strict')

    def test_actual_pinned_help_declares_canonical_variables_not_hidden_alias(self):
        root=ROOT/'tests/workload-identities/fixtures';proof=json.loads((root/'uds-0.41.0-help-provenance.json').read_text())
        self.assertEqual(proof['version'],'0.41.0');self.assertEqual(proof['embeddedZarfVersion'],'0.89.0')
        for op,item in proof['commands'].items():self.assertEqual(P.digest(root/item['fixture']),item['fixtureSHA256'])
        actual=P.declared_flags((root/'uds-0.41.0-deploy-flags.txt').read_text())
        self.assertEqual(actual,{'--confirm','--features','--values','--set-values','--set-variables'})
        self.assertNotIn('--set',actual)
        command=P.deploy_command(self.bound(),'strict')
        self.assertNotIn('--set',command);self.assertEqual(command.count('--set-variables'),len(self.bound()['variables'])+1)

    def test_flag_parser_rejects_suffixes_prefixes_prose_and_examples(self):
        for text in ['      --set-variables-extra value','      --set-variablesX value','x--set-variables value','_--set-variables value',
                     'Example: deploy --set-variables NAME=value','Supported option --set-variables']:
            with self.subTest(text=text):self.assertNotIn('--set-variables',P.declared_flags(text))
        for text in ['      --set-variables stringToString variables','  -s, --set-variables stringToString variables','      --set-variables=value']:
            with self.subTest(text=text):self.assertIn('--set-variables',P.declared_flags(text))
        self.assertEqual(P.declared_flags('      --set-values-extra value'),{'--set-values-extra'})
