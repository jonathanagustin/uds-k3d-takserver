# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline command and fail-closed guards; never live identity acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_trial',ROOT/'tests/workload-identities/package_roundtrip.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)

class PackageGuards(unittest.TestCase):
    def bound(self):return {'archive':'/owned/zarf-package-takserver-amd64-dev-upstream.tar.zst','archiveSHA256':'a'*64,'planSHA256':'b'*64,'configSHA256':'c'*64,'variables':{'DOMAIN':'uds.dev','TAK_IMAGE_TAG':'reviewed','FILESYSTEM_BACKUP':'true','POSTGRES_STORAGE_CLASS':'local-path-local','CLOUDTAK_STORAGE_CLASS':'local-path-local'}}
    def test_same_archive_and_values_only_phase_changes(self):
        commands=[P.deploy_command(self.bound(),phase) for phase in P.PHASES]
        stripped=[c[:-1] for c in commands]
        self.assertTrue(all(c==stripped[0] for c in stripped));self.assertTrue(all(c[4]==self.bound()['archive'] for c in commands))
        self.assertEqual([c[-1] for c in commands],['tak.workloadIdentityPhase='+x for x in P.PHASES])
        self.assertEqual(commands[0].count('--set-values'),1)
        self.assertNotIn('--force-conflicts',commands[0])
        with self.assertRaises(ValueError):P.deploy_command(self.bound(),'unknown')
    def test_cli_capabilities_fail_before_any_deployment(self):
        calls=[]
        def help(argv):
            calls.append(argv)
            return (ROOT/'tests/workload-identities/fixtures'/('uds-0.41.0-'+argv[3]+'-flags.txt')).read_text()
        P.cli_preflight(help);self.assertEqual([x[3] for x in calls],['deploy','remove'])
        self.assertTrue(all(x[-1]=='--help' for x in calls))
        with self.assertRaisesRegex(ValueError,'--features, --set-values'):P.cli_preflight(lambda argv:'  -c, --confirm  Confirms\n      --set-variables stringToString Variables\n')
    def test_actual_deploy_path_dispatches_supported_command_then_observes(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=P.PackageTrial(Path(directory)/'journal',self.bound());instance.bound['archiveSHA256']='a'*64
            calls=[];seen=[];instance.guard=lambda:None;instance.inputs_unchanged=lambda:None;instance.core_unchanged=lambda:None;instance.journal=lambda *a,**k:None
            instance.command=lambda argv,**kw:(calls.append(argv) or (P.D.CONTEXT if argv[0]=='kubectl' else ''))
            instance.observe=seen.append;instance.deploy('rollback')
            self.assertEqual(calls[-1],P.deploy_command(instance.bound,'rollback'));self.assertEqual(seen,['rollback'])
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
            expected=P.digest(archive);P.bind_inputs(archive,expected,plan)
            config.write_text('changed')
            with self.assertRaises(ValueError):P.bind_inputs(archive,expected,plan)
            archive.write_bytes(b'changed')
            with self.assertRaises(ValueError):P.bind_inputs(archive,expected,plan)

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
        self.assertEqual(actual,{'--confirm','--features','--set-values','--set-variables'})
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
