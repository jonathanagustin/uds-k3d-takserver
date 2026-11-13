# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline adversarial fixtures; none are live policy/traffic acceptance."""
import copy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('identity_driver', ROOT / 'tests/workload-identities/drive.py')
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def workload_fixture():
    deployments, replicasets, pods, uids = [], [], [], {}
    for index, app in enumerate(driver.APPS):
        uid = 'deployment-' + str(index)
        uids[app] = uid
        deployments.append({'metadata': {'name': app, 'uid': uid, 'resourceVersion': '5', 'generation': 2,
            'annotations': {'meta.helm.sh/release-name': 'takserver', 'meta.helm.sh/release-namespace': 'takserver'},
            'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
            'spec': {'replicas': 2, 'template': {'spec': {'serviceAccountName': app}}},
            'status': {'observedGeneration': 2, 'replicas': 2, 'updatedReplicas': 2, 'readyReplicas': 2, 'availableReplicas': 2}})
        replicasets.append({'metadata': {'name': app + '-rs', 'uid': app + '-rs',
            'ownerReferences': [{'uid': uid, 'controller': True}]},
            'spec': {'replicas': 2, 'template': {'spec': {'serviceAccountName': app}}}})
        for replica in range(2):
            pods.append({'metadata': {'name': app + '-' + str(replica), 'uid': app + '-uid-' + str(replica),
                'resourceVersion': '7', 'labels': {'app': app},
                'annotations': {'ambient.istio.io/redirection': 'enabled'},
                'ownerReferences': [{'uid': app + '-rs', 'controller': True}]},
                'spec': {'serviceAccountName': app},
                'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]}})
    return deployments, replicasets, pods, uids


def policy_fixture():
    selector = {'app': 'takserver-ignite'}
    package = {'metadata': {'name': 'takserver', 'uid': 'package', 'generation': 3},
               'status': {'phase': 'Ready', 'observedGeneration': 3},
               'spec': {'network': {'allow': [
                   {'direction': 'Ingress', 'selector': selector, 'port': 47100,
                    'remoteSelector': {'app': app}, 'remoteServiceAccount': app} for app in driver.APPS]}}}
    policies = [{'metadata': {'name': app, 'labels': {'uds/package': 'takserver', 'uds/generation': '3'}},
                 'spec': {'action': 'ALLOW', 'selector': {'matchLabels': selector}, 'rules': [
                     {'from': [{'source': {'principals': ['cluster.local/ns/takserver/sa/' + app]}}],
                      'to': [{'operation': {'ports': ['47100']}}]}]}} for app in driver.APPS]
    net = [{'metadata': {'name': 'ingress', 'labels': {'uds/package': 'takserver', 'uds/generation': '3'}},
            'spec': {'podSelector': {'matchLabels': selector}, 'policyTypes': ['Ingress'], 'ingress': []}}]
    return package, policies, net, [driver.sha(net[0]['spec'])]


def pepr_fixture(phase='strict'):
    deployments, replicasets, pods = {}, [], []
    for name in driver.PEPR:
        template = {'metadata': {'labels': {'app': name}},
                    'spec': {'serviceAccountName': name, 'containers': [
                        {'name': 'server', 'image': 'example/pepr@sha256:' + '1' * 64,
                         'env': [{'name': 'TAK_WORKLOAD_IDENTITY_PHASE', 'value': phase}]}]}}
        deployments[name] = {'metadata': {'name': name, 'uid': name + '-deployment', 'generation': 2,
            'annotations': {'meta.helm.sh/release-name': 'takserver-oidc', 'meta.helm.sh/release-namespace': 'pepr-system'},
            'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
            'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': name}}, 'template': template},
            'status': {'observedGeneration': 2, 'replicas': 1, 'updatedReplicas': 1,
                       'readyReplicas': 1, 'availableReplicas': 1}}
        replicasets.append({'metadata': {'name': name + '-rs', 'uid': name + '-rs',
            'ownerReferences': [{'controller': True, 'uid': name + '-deployment'}]},
            'spec': {'replicas': 1, 'template': copy.deepcopy(template)}})
        pods.append({'metadata': {'name': name + '-pod', 'uid': name + '-pod', 'labels': {'app': name},
            'ownerReferences': [{'controller': True, 'uid': name + '-rs'}]},
            'spec': copy.deepcopy(template['spec']),
            'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]}})
    return deployments, replicasets, pods


class IdentityFixtures(unittest.TestCase):
    def test_identity_fingerprint_normalizes_only_consistent_service_account_alias(self):
        baseline = {'spec': {'template': {'spec': {'containers': [{'name': 'app', 'image': 'same'}],
            'serviceAccountName': driver.LEGACY, 'serviceAccount': driver.LEGACY}}}}
        transition = copy.deepcopy(baseline)
        transition['spec']['template']['spec'].update(serviceAccountName=driver.APPS[0], serviceAccount=driver.APPS[0])
        self.assertEqual(driver.template_fingerprint(baseline), driver.template_fingerprint(transition))
        self.assertEqual(baseline['spec']['template']['spec']['serviceAccount'], driver.LEGACY)
        without_alias = copy.deepcopy(transition)
        without_alias['spec']['template']['spec'].pop('serviceAccount')
        self.assertEqual(driver.template_fingerprint(transition), driver.template_fingerprint(without_alias))
        for mutation in ('contradictory', 'missing-canonical'):
            invalid = copy.deepcopy(transition)
            if mutation == 'contradictory':
                invalid['spec']['template']['spec']['serviceAccount'] = driver.LEGACY
            else:
                invalid['spec']['template']['spec'].pop('serviceAccountName')
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'inconsistent workload service account alias'):
                driver.template_fingerprint(invalid)
        drift = copy.deepcopy(transition)
        drift['spec']['template']['spec']['containers'][0]['image'] = 'changed'
        self.assertNotEqual(driver.template_fingerprint(baseline), driver.template_fingerprint(drift))
        for options in ({'exact': True}, {'pepr': True}):
            self.assertNotEqual(driver.template_fingerprint(baseline, **options),
                                driver.template_fingerprint(transition, **options))
            alias_drift = copy.deepcopy(baseline)
            alias_drift['spec']['template']['spec']['serviceAccount'] = 'different'
            self.assertNotEqual(driver.template_fingerprint(baseline, **options),
                                driver.template_fingerprint(alias_drift, **options))

    @unittest.skipUnless(shutil.which('helm'), 'Helm required for actual source RBAC render')
    def test_disjoint_port_filter_cannot_hide_invalid_or_wildcard_branches(self):
        package,policies,network,baseline=policy_fixture()
        for rule in package['spec']['network']['allow']:rule['port']=5432
        for policy in policies:
            for rule in policy['spec']['rules']:
                for target in rule['to']:target['operation']['ports']=['5432']
        def check(branches):
            extra={'metadata':{'name':'foreign','namespace':'takserver','uid':'foreign','resourceVersion':'1'},
                   'spec':{'selector':copy.deepcopy(policies[0]['spec']['selector']),
                           'rules':[{'from':[{'source':{'principals':['cluster.local/ns/foreign/sa/foreign']}}],
                                     'to':[{'operation':{'ports':ports}} for ports in branches]}]}}
            return driver.validate_policies(package,policies+[extra],network,baseline)
        self.assertTrue(check([['443']]))
        for branches in [[['443','*']],[['443','invalid']],[['0']],[['65536']],['443'],[443],[[443]],
                         [['443'],['*']],[['443'],[]],[['443'],['5432']],[['5432']]]:
            with self.subTest(branches=branches),self.assertRaises(ValueError):check(branches)

    def test_actual_chart_rbac_contract_rejects_permission_expansion(self):
        rendered=subprocess.run(['helm','template','uds-takserver-config',str(ROOT/'charts/takserver'),
                                 '--namespace','takserver','--set','workloadIdentityPhase=transition'],
                                text=True,capture_output=True,check=True)
        resources=[r for r in driver.yaml.safe_load_all(rendered.stdout) if r and
                   (r['kind'],r['metadata']['name']) in driver.RBAC]
        driver.validate_rbac(resources)
        changed=copy.deepcopy(resources)
        role=next(r for r in changed if r['kind']=='Role')
        role['rules'].append({'apiGroups':[''],'resources':['secrets'],'verbs':['get']})
        with self.assertRaisesRegex(ValueError,'permissions changed'):driver.validate_rbac(changed)
        changed=copy.deepcopy(resources)
        binding=next(r for r in changed if r['kind']=='RoleBinding')
        binding['roleRef']['kind']='ClusterRole'
        with self.assertRaisesRegex(ValueError,'target changed'):driver.validate_rbac(changed)

    def test_every_replica_is_verified(self):
        deployments, rs, pods, uids = workload_fixture()
        result = driver.validate_workloads(deployments, rs, pods, 'dedicated', uids)
        self.assertEqual(len(result), 8)
        self.assertEqual({p['uid'] for p in result}, {p['metadata']['uid'] for p in pods})

    def test_stale_terminating_mixed_and_foreign_workloads_fail(self):
        mutations = [lambda d,r,p: d[0]['status'].update(observedGeneration=1),
                     lambda d,r,p: d[0]['status'].update(replicas=3),
                     lambda d,r,p: p[-1]['metadata'].update(deletionTimestamp='now'),
                     lambda d,r,p: p[-1]['spec'].update(serviceAccountName=driver.LEGACY),
                     lambda d,r,p: p[-1]['metadata'].update(ownerReferences=[]),
                     lambda d,r,p: p[-1]['metadata']['labels'].update(app='hidden-old-replica'),
                     lambda d,r,p: r[-1]['spec']['template']['spec'].update(serviceAccountName=driver.LEGACY),
                     lambda d,r,p: r.append({**copy.deepcopy(r[-1]), 'metadata': {**r[-1]['metadata'], 'uid': 'old-active'},
                                            'spec': {'replicas': 1, 'template': {'spec': {'serviceAccountName': driver.LEGACY}}}}),
                     lambda d,r,p: p[-1]['metadata']['annotations'].clear(),
                     lambda d,r,p: p.append(copy.deepcopy(p[-1]))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                d,r,p,u = workload_fixture(); mutate(d,r,p)
                with self.assertRaises(ValueError):
                    driver.validate_workloads(d,r,p,'dedicated',u)

    def test_ready_pod_of_inactive_owned_replicaset_is_not_converged(self):
        deployments, replicasets, pods, uids = workload_fixture()
        inactive = copy.deepcopy(replicasets[0])
        inactive['metadata']['uid'] = 'inactive-owned-replicaset'
        inactive['metadata']['name'] += '-inactive'
        inactive['spec']['replicas'] = 0
        replicasets.append(inactive)
        # Counters, readiness and account all match. Only controller ownership
        # exposes this stale Pod; the active ReplicaSet remains present.
        pods[0]['metadata']['ownerReferences'][0]['uid'] = inactive['metadata']['uid']
        with self.assertRaisesRegex(ValueError, 'inactive ReplicaSet'):
            driver.validate_workloads(deployments, replicasets, pods, 'dedicated', uids)

    def test_exact_current_policy_convergence_and_duplicate_network_rules(self):
        package, policies, net, baseline = policy_fixture()
        fingerprint = driver.validate_policies(package, policies, net, baseline)
        self.assertEqual(len(fingerprint), 64)
        duplicate = copy.deepcopy(net[0]); duplicate['metadata']['name'] = 'legacy-duplicate'
        driver.validate_policies(package, policies, net + [duplicate], baseline)

    def test_stale_missing_broad_and_extra_principals_fail(self):
        mutations = [lambda p,a,n: p['status'].update(observedGeneration=2),
                     lambda p,a,n: a[0]['metadata']['labels'].update({'uds/generation': '2'}),
                     lambda p,a,n: a.pop(),
                     lambda p,a,n: a[0]['spec']['rules'][0].pop('from'),
                     lambda p,a,n: a[0]['spec']['rules'][0].pop('to'),
                     lambda p,a,n: a[0]['spec']['rules'][0]['to'][0]['operation']['ports'].append('*'),
                     lambda p,a,n: a[0]['spec']['rules'][0]['to'][0]['operation']['ports'].append('9999'),
                     lambda p,a,n: a[0]['spec'].update(selector={}),
                     lambda p,a,n: a[0]['metadata'].update(namespace='istio-system'),
                     lambda p,a,n: a[0]['spec']['rules'][0]['from'][0]['source'].update(principals=['*']),
                     lambda p,a,n: a[0]['spec']['rules'][0]['from'][0]['source'].update(namespaces=['takserver']),
                     lambda p,a,n: a[0]['spec']['rules'][0]['from'][0]['source']['principals'].append('cluster.local/ns/takserver/sa/intruder'),
                     lambda p,a,n: n[0]['metadata'].update(deletionTimestamp='now'),
                     lambda p,a,n: n[0]['spec'].update(egress=[{}])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                p,a,n,b = policy_fixture(); mutate(p,a,n)
                with self.assertRaises(ValueError): driver.validate_policies(p,a,n,b)

    def test_root_allow_with_unknown_extra_destination_label_can_overlap(self):
        for selector in ({'app': 'takserver-ignite', 'extra-label': 'present-on-pod'}, {}, None):
            with self.subTest(selector=selector):
                package, policies, network, baseline = policy_fixture()
                policy = {'metadata': {'name': 'root-allow', 'namespace': 'istio-system'},
                          'spec': {'action': 'ALLOW', 'rules': [{}]}}
                if selector is not None:
                    policy['spec']['selector'] = {'matchLabels': selector}
                policies.append(policy)
                with self.assertRaisesRegex(ValueError, 'foreign overlapping policy'):
                    driver.validate_policies(package, policies, network, baseline)

    def test_root_allow_with_conflicting_known_destination_label_is_disjoint(self):
        package, policies, network, baseline = policy_fixture()
        expected = driver.validate_policies(package, policies, network, baseline)
        policies.append({'metadata': {'name': 'other-app', 'namespace': 'istio-system'},
                         'spec': {'action': 'ALLOW',
                                  'selector': {'matchLabels': {'app': 'unrelated', 'extra-label': 'anything'}},
                                  'rules': [{}]}})
        self.assertEqual(driver.validate_policies(package, policies, network, baseline), expected)

    def test_readonly_pepr_observer_checks_original_uid_template_and_phase(self):
        cases = ('valid', 'replacement', 'foreign-owner', 'template-drift', 'deployment-phase',
                 'replicaset-phase', 'inactive-replicaset-pod', 'pod-phase')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                instance = driver.Driver(Path(directory) / 'journal.json')
                deployments, replicasets, pods = pepr_fixture()
                instance.state.update(peprUIDs={name: d['metadata']['uid'] for name, d in deployments.items()},
                    peprTemplateFingerprints={name: driver.template_fingerprint(d, True) for name, d in deployments.items()})
                first = driver.PEPR[0]
                if case == 'replacement':
                    deployments[first]['metadata']['uid'] = 'replacement-deployment'
                    replicasets[0]['metadata']['ownerReferences'][0]['uid'] = 'replacement-deployment'
                elif case == 'foreign-owner':
                    deployments[first]['metadata']['annotations']['meta.helm.sh/release-name'] = 'foreign'
                elif case == 'template-drift':
                    deployments[first]['spec']['template']['spec']['containers'][0]['image'] = 'foreign/image'
                    replicasets[0]['spec']['template'] = copy.deepcopy(deployments[first]['spec']['template'])
                    pods[0]['spec'] = copy.deepcopy(deployments[first]['spec']['template']['spec'])
                elif case == 'deployment-phase':
                    deployments[first]['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'shared'
                elif case == 'replicaset-phase':
                    replicasets[0]['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'shared'
                elif case == 'inactive-replicaset-pod':
                    inactive = copy.deepcopy(replicasets[0])
                    inactive['metadata']['uid'] = 'inactive-pepr-rs'
                    inactive['spec']['replicas'] = 0
                    replicasets.append(inactive)
                    pods[0]['metadata']['ownerReferences'][0]['uid'] = 'inactive-pepr-rs'
                elif case == 'pod-phase':
                    pods[0]['spec']['containers'][0]['env'][0]['value'] = 'shared'
                def get(kind, name=None, namespace=None):
                    self.assertEqual(namespace, 'pepr-system')
                    return deployments[name] if kind == 'deployment' else {
                        'items': replicasets if kind == 'replicasets' else pods}
                instance.get = get
                instance.patch = MagicMock(side_effect=AssertionError('observer must not mutate'))
                if case == 'valid':
                    result = instance.observe_pepr('strict')
                    self.assertEqual({row[0] for row in result}, set(driver.PEPR))
                    self.assertEqual(instance._last_pepr_observation['pods'], pods)
                else:
                    with self.assertRaises(ValueError):
                        instance.observe_pepr('strict')
                instance.patch.assert_not_called()

    def test_pure_pepr_validator_needs_no_cluster_and_does_not_mutate_inputs(self):
        deployments, replicasets, pods = pepr_fixture()
        baseline_uids = {name: d['metadata']['uid'] for name, d in deployments.items()}
        fingerprints = {name: driver.template_fingerprint(d, True) for name, d in deployments.items()}
        inputs = (list(deployments.values()), replicasets, pods)
        original = copy.deepcopy(inputs)
        result = driver.validate_pepr(*inputs, 'strict', baseline_uids, fingerprints)
        self.assertEqual(len(result), len(driver.PEPR))
        self.assertEqual(inputs, original)
        with self.assertRaisesRegex(ValueError, 'two exact Pepr Deployments'):
            driver.validate_pepr(inputs[0] * 2, replicasets, pods, 'strict', baseline_uids, fingerprints)

    def test_raw_policy_lists_preserve_server_revision_and_reject_partial_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'journal.json')
            policy={'apiVersion':'security.istio.io/v1','kind':'AuthorizationPolicy','metadata':{
                'namespace':'takserver','name':'policy','uid':'policy-uid','resourceVersion':'123'},'spec':{}}
            raw={'apiVersion':'security.istio.io/v1','kind':'AuthorizationPolicyList',
                 'metadata':{'resourceVersion':'124'},'items':[policy]}
            commands=[]
            def load(value):
                instance.kube=lambda *argv:(commands.append(argv) or json.dumps(value))
                return instance.authorization_policy_list('takserver')
            self.assertEqual(load(raw),raw)
            self.assertEqual(commands[-1],('get','--raw','/apis/security.istio.io/v1/namespaces/takserver/authorizationpolicies'))
            bad=[]
            for meta in [{},{'resourceVersion':''},{'resourceVersion':'124','continue':'next'},
                         {'resourceVersion':'124','remainingItemCount':1},{'resourceVersion':'124','remainingItemCount':True}]:
                bad.append({**raw,'metadata':meta})
            bad += [{**raw,'kind':'List','apiVersion':'v1','metadata':{'resourceVersion':''}},
                    {**raw,'items':[policy,policy]},
                    {**raw,'items':[policy,{**policy,'metadata':{**policy['metadata'],'name':'different'}}]},
                    {**raw,'items':[policy,{**policy,'metadata':{**policy['metadata'],'uid':'different'}}]},
                    {**raw,'items':'malformed'},
                    {**raw,'items':[{**policy,'metadata':{**policy['metadata'],'namespace':'istio-system'}}]},
                    {**raw,'items':[{**policy,'spec':None}]}]
            for value in bad:
                with self.subTest(value=value),self.assertRaises(ValueError):load(value)
            instance.kube=lambda *argv:(commands.append(argv) or json.dumps({**raw,'items':[]}))
            self.assertEqual(instance.authorization_policy_list('istio-system')['items'],[])
            self.assertEqual(commands[-1],('get','--raw','/apis/security.istio.io/v1/namespaces/istio-system/authorizationpolicies'))
            with self.assertRaises(ValueError):instance.authorization_policy_list('foreign')

    def test_requested_policy_observation_refuses_concurrent_uid_or_rule_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'journal.json')
            package,policies,network,baseline=policy_fixture()
            mesh={'metadata':{'uid':'mesh'},'data':{'mesh':'rootNamespace: istio-system'}}
            instance.state.update(meshConfigUID='mesh',meshConfigHash=driver.sha(mesh['data']['mesh']),
                                  packageUID=package['metadata']['uid'],currentAllow=copy.deepcopy(package['spec']['network']['allow']),
                                  packageInvariant=driver.package_invariant(package),baselineNetwork=baseline)
            def get(kind,*args,**kwargs):
                if kind=='package':return package
                if kind=='configmap':return mesh
                if kind.startswith('authorization') and kwargs.get('namespace')=='istio-system':return {'items':[]}
                return {'items':policies if kind.startswith('authorization') else network}
            instance.get=get
            instance.authorization_policy_list=lambda namespace:{'metadata':{'resourceVersion':'100'},'items':policies if namespace=='takserver' else []}
            instance.policies()
            package['metadata']['uid']='replacement'
            with self.assertRaisesRegex(ValueError,'requested Package'):instance.policies()
            package['metadata']['uid']='package'
            package['spec']['network']['allow'][0]['remoteServiceAccount']='intruder'
            with self.assertRaisesRegex(ValueError,'requested Package'):instance.policies()

    def test_patch_is_guarded_and_uses_atomic_uid_version_and_old_value(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = driver.Driver(Path(directory) / 'journal.json')
            obj = {'metadata': {'name': 'takserver', 'uid': 'one', 'resourceVersion': '8'},
                   'spec': {'network': {'allow': ['old']}}}
            events = []
            instance.guard = lambda: events.append('guard')
            def command(args, payload=None, timeout=45):
                events.append('command'); return json.dumps(obj)
            instance.command = command
            instance.patch('package', obj, '/spec/network/allow', ['new'])
            self.assertEqual(events, ['guard','command'])
            with patch.object(instance, 'kube', return_value=json.dumps(obj)) as kube:
                instance.patch('package', obj, '/spec/network/allow', ['new'])
                args = kube.call_args.args
                operations = json.loads(args[args.index('-p') + 1])
                self.assertEqual(operations[:3], [
                    {'op':'test','path':'/metadata/uid','value':'one'},
                    {'op':'test','path':'/metadata/resourceVersion','value':'8'},
                    {'op':'test','path':'/spec/network/allow','value':['old']}])
            with self.assertRaises(ValueError): instance.patch('package', obj, '/spec/network', {})
            with self.assertRaises(ValueError): instance.patch('package', obj, '/spec/network/allow', [], 'production')

    def test_probe_pods_keep_real_job_controller_and_selector_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'journal.json')
            instance.state['trialID']='identity-fixture'
            job={'metadata':{'name':'identity-fixture-control','uid':'job-owned'},
                 'spec':{'selector':{'matchLabels':{'batch.kubernetes.io/controller-uid':'job-owned'}}}}
            pod={'metadata':{'name':'identity-fixture-control-abcde','uid':'pod-owned',
                'labels':{'app':'identity-control','batch.kubernetes.io/controller-uid':'job-owned',
                          'batch.kubernetes.io/job-name':'identity-fixture-control','uds.dev/identity-trial':'identity-fixture'},
                'ownerReferences':[{'kind':'Job','uid':'job-owned','controller':True}]},'status':{'phase':'Running'}}
            requested=[]
            instance.create=lambda obj: requested.append(obj) or copy.deepcopy(job)
            instance.get=lambda kind,*a,**k: {'items':[pod]} if kind=='pods' else copy.deepcopy(pod)
            instance.wait=lambda callback,*a: callback()
            def apply_labels(kind,obj,path,value,**kwargs):
                result=copy.deepcopy(obj);result['metadata']['labels']=value;return result
            instance.patch=apply_labels
            manifest={'metadata':{'name':'identity-fixture-control','labels':{'app':'identity-control'}},
                      'spec':{'restartPolicy':'Never','containers':[{'name':'probe','image':'image@sha256:test'}]}}
            protected,_=instance.control_job(manifest,{'app':'takserver-api','pod-template-hash':'a-real-replicaset-hash',
                                                      'batch.kubernetes.io/controller-uid':'spoofed'})
            self.assertEqual(requested[0]['kind'],'Job')
            self.assertEqual(requested[0]['spec']['template']['metadata']['labels']['app'],'identity-control')
            self.assertEqual(protected['metadata']['ownerReferences'],[{'kind':'Job','uid':'job-owned','controller':True}])
            self.assertEqual(protected['metadata']['labels']['app'],'takserver-api')
            self.assertEqual(protected['metadata']['labels']['batch.kubernetes.io/controller-uid'],'job-owned')
            self.assertNotIn('pod-template-hash',protected['metadata']['labels'])
            pod['metadata']['ownerReferences']=[{'kind':'ReplicaSet','uid':'foreign','controller':True}]
            with self.assertRaisesRegex(ValueError,'not owned'):instance.control_job(manifest,{'app':'takserver-api'})

    def test_cleanup_uses_deleteoptions_uid_and_version_not_blind_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'journal.json')
            instance.state.update(trialID='identity-fixture', created=[{'kind':'Pod','name':'identity-fixture-control','uid':'owned'}])
            obj={'metadata':{'name':'identity-fixture-control','uid':'owned','resourceVersion':'9',
                             'labels':{'uds.dev/identity-trial':'identity-fixture'}}}
            instance.get=lambda *a,**k: obj
            instance.guard=lambda: {}
            config={'clusters':[{'cluster':{'server':'https://127.0.0.1:6443','certificate-authority-data':'Zml4dHVyZQ=='}}],
                    'users':[{'user':{'client-certificate-data':'Zml4dHVyZQ==','client-key-data':'Zml4dHVyZQ=='}}]}
            instance.command=lambda *a,**k: json.dumps(config)
            calls=[]
            def kube(*args,**kwargs):
                calls.append(args)
                return json.dumps(obj) if len(calls)==1 else ''
            instance.kube=kube
            instance.wait=lambda callback,*a: callback()
            opener=MagicMock();opener.open.return_value.__enter__.return_value.status=200
            with patch.object(driver.ssl,'create_default_context',return_value=MagicMock()), patch.object(
                    driver.urllib.request,'build_opener',return_value=opener):
                instance.delete_created('Pod','identity-fixture-control')
            request=opener.open.call_args.args[0]
            self.assertEqual(request.method,'DELETE')
            self.assertEqual(request.full_url,'https://127.0.0.1:6443/api/v1/namespaces/takserver/pods/identity-fixture-control')
            self.assertEqual(json.loads(request.data)['preconditions'],{'uid':'owned','resourceVersion':'9'})
            instance.state['created'][0]['deleted']=False
            instance.kube=lambda *a,**k: ''
            with patch.object(driver.urllib.request,'build_opener') as network:
                instance.delete_created('Pod','identity-fixture-control')
                network.assert_not_called()
            self.assertTrue(instance.state['created'][0]['deleted'])
            instance.state['created'][0]['deleted']=False
            obj['metadata']['uid']='replacement'
            instance.kube=lambda *a,**k: json.dumps(obj)
            with patch.object(driver.urllib.request,'build_opener') as network:
                with self.assertRaises(ValueError): instance.delete_created('Pod','identity-fixture-control')
                network.assert_not_called()

    def test_reverse_converges_dual_policy_before_identity_and_shared_last(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'journal.json')
            instance.state.update(packageUID='package',phaseRules={'strict':['strict'],'shared':['shared']},baselineAllow=['shared'],
                                  originalTrialAnnotations={app:None for app in driver.APPS})
            events=[]
            instance.get=lambda kind,name: ({'metadata':{'uid':'package'},'spec':{'network':{'allow':['strict']}}}
                                           if kind=='package' else {'metadata':{'annotations':{}}})
            instance.stage_config=lambda phase: events.append(('config',phase))
            instance.stage_admission=lambda phase: events.append(('admission',phase)) or []
            instance.traffic=lambda identities,phase: events.append(('traffic',phase))
            instance.capture_phase=lambda phase,account: events.append(('evidence',phase,account))
            instance.patch=lambda *a,**k: None
            instance.wait=lambda callback: callback()
            instance.identities=lambda account: []
            instance.policies=lambda: 'policy-fingerprint'
            # Final API observation must report the baseline after phase requests.
            original_get=instance.get
            def get(kind,name):
                value=original_get(kind,name)
                if kind=='package' and ('config','shared') in events:value['spec']['network']['allow']=['shared']
                return value
            instance.get=get
            instance.reverse()
            self.assertEqual(events,[('config','rollback'),('admission','rollback'),('traffic','rollback'),('evidence','rollback','shared'),
                                     ('config','shared'),('admission','shared'),('traffic','shared'),('evidence','shared','shared')])
            self.assertTrue(instance.state['completed'])
            self.assertFalse(instance.state['accepted'], 'completion alone cannot manufacture missing forward acceptance')
            events.clear();instance.state['completed']=False
            instance.stage_config=lambda phase: (_ for _ in ()).throw(ValueError('policy did not converge'))
            with self.assertRaises(ValueError):instance.reverse()
            self.assertEqual(events,[])
            self.assertFalse(instance.state['completed'])

    def test_staged_helper_refuses_tampering_and_symlink_reuse(self):
        with tempfile.TemporaryDirectory(prefix='identity-probe-fixture-') as directory:
            parent=Path(directory)
            instance=driver.Driver(parent/'journal.json')
            instance.state.update(trialID=parent.name+'/probe',probeClassSHA256=hashlib.sha256(b'fixture class').hexdigest())
            instance.probe_class=base64.b64encode(b'fixture class').decode()
            instance.exec=lambda pod,container,args,payload=None: subprocess.run(args,input=payload,text=True,capture_output=True)
            output=Path(instance.install_probe('fixture','fixture'))
            self.assertEqual((output/'ProtocolProbe.class').read_bytes(),b'fixture class')
            instance.install_probe('fixture','fixture')
            (output/'ProtocolProbe.class').write_bytes(b'tampered')
            with self.assertRaises(ValueError):instance.install_probe('fixture','fixture')
            (output/'ProtocolProbe.class').unlink();output.rmdir()
            target=parent/'other';target.mkdir();(target/'ProtocolProbe.class').write_bytes(b'fixture class')
            output.symlink_to(target,target_is_directory=True)
            with self.assertRaises(ValueError):instance.install_probe('fixture','fixture')

    def test_actual_shell_adapter_preserves_only_canonical_java_results(self):
        script=driver.protocol_adapter('ignite')
        for code,output,err,accepted in [(0,'APPLICATION_RESPONSE\n','',True),(10,'TRANSPORT_REJECTED\n','',True),
            (20,'','PROBE_INVALID',False),(1,'APPLICATION_RESPONSE\n','',False),(10,'TRANSPORT_REJECTED\nextra','',False),
            (10,'TRANSPORT_REJECTED\n\n','',False),(10,'TRANSPORT_REJECTED','',False),
            (0,'UDS_PROTOCOL_V1:10:TRANSPORT_REJECTED\n','',False),(10,'TRANSPORT_REJECTED\n','warning',False)]:
            with self.subTest(code=code,output=output,err=err),tempfile.TemporaryDirectory() as directory:
                peer=Path(directory)/'peer'
                peer.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdout.write('+repr(output)+')\nsys.stderr.write('+repr(err)+')\nsys.exit('+str(code)+')\n');peer.chmod(0o700)
                result=subprocess.run(['/bin/bash','-c',script,'adapter',str(peer)],text=True,capture_output=True)
                instance=driver.Driver(Path(directory)/'journal');instance.exec=lambda *a,**kw:result
                if accepted:self.assertEqual(instance.protocol('pod','app','/tmp/test','ignite'),code)
                else:
                    with self.assertRaises(ValueError):instance.protocol('pod','app','/tmp/test','ignite')

    def test_transport_command_errors_are_not_negative_traffic(self):
        with tempfile.TemporaryDirectory() as directory:
            instance=driver.Driver(Path(directory)/'evidence')
            for code,out,err in [(1,'','kubectl failed'),(20,'','PROBE_INVALID'),(10,'',''),(0,'TRANSPORT_REJECTED','')]:
                instance.exec=lambda *a,**k: subprocess.CompletedProcess([],code,out,err)
                with self.assertRaises(ValueError): instance.protocol('pod','app','/tmp/test','ignite','10.0.0.1',47100)
            instance.exec=lambda *a,**k: subprocess.CompletedProcess([],0,'UDS_PROTOCOL_V1:10:TRANSPORT_REJECTED\n','')
            self.assertEqual(instance.protocol('pod','app','/tmp/test','ignite','10.0.0.1',47100),10)


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
class ProtocolFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.output=Path(cls.temp.name)
        subprocess.run(['javac','--release','17','-d',str(cls.output),str(ROOT/'tests/workload-identities/ProtocolProbe.java')],check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def probe(self, mode, reply, receive=False):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1)
        port=listener.getsockname()[1];request=[]
        def serve():
            with listener:
                connection,_=listener.accept()
                with connection:
                    if receive: request.append(connection.recv(8))
                    if reply: connection.sendall(reply)
        thread=threading.Thread(target=serve);thread.start()
        result=subprocess.run(['java','-cp',str(self.output),'ProtocolProbe',mode,'127.0.0.1',str(port)],capture_output=True,text=True,timeout=10)
        thread.join(5);self.assertFalse(thread.is_alive())
        return result,request

    def test_real_protocol_frames_are_required(self):
        result,_=self.probe('ignite',b'\xff\xff'+bytes(range(1,17)))
        self.assertEqual((result.returncode,result.stdout.strip()),(0,'APPLICATION_RESPONSE'))
        result,request=self.probe('postgres',b'S',True)
        self.assertEqual(result.returncode,0);self.assertEqual(request,[b'\x00\x00\x00\x08\x04\xd2\x16\x2f'])
        result,_=self.probe('nats',b'INFO {"server_id":"NTEST","version":"2.17.0"}\r\n');self.assertEqual(result.returncode,0)

    def test_partial_wrong_and_nil_responses_never_count_as_denial(self):
        for mode,reply in [('ignite',b'\xff'),('ignite',b'\xff\xff'+bytes(16)),('nats',b'NOPE!'),('nats',b'INFO '),('postgres',b'X')]:
            with self.subTest(mode=mode,reply=reply):
                result,_=self.probe(mode,reply);self.assertEqual(result.returncode,20)
        result,_=self.probe('ignite',b'');self.assertEqual((result.returncode,result.stdout.strip()),(10,'TRANSPORT_REJECTED'))


if __name__ == '__main__': unittest.main()
