# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline typed guard evidence; never Kubernetes or live migration acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.test_identity_rollout_driver import driver, policy_fixture, workload_fixture, pepr_fixture

SPEC = importlib.util.spec_from_file_location('phase_evidence', Path(__file__).parent / 'workload-identities/phase_evidence.py')
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


def fixture():
    deployments, replicasets, pods, uids = workload_fixture()
    package, policies, network, baseline = policy_fixture()
    bind = {'sourceSHA': 'a'*40, 'runID': '123', 'runAttempt': '1', 'clusterUID': 'cluster-uid',
            'meshConfigUID': 'mesh-uid', 'meshConfigHash': 'b'*64, 'phase': 'strict'}
    pepr_deployments, pepr_replicasets, pepr_pods = pepr_fixture()
    return bind, dict(guards=driver, package=package, policies=policies, network_policies=network,
                     baseline_network=baseline, deployments=deployments, replicasets=replicasets,
                     pods=pods, account='dedicated', baseline_uids=uids,
                     template_fingerprints={d['metadata']['name']: driver.template_fingerprint(d) for d in deployments},
                     pepr={'deployments': list(pepr_deployments.values()), 'replicasets': pepr_replicasets, 'pods': pepr_pods},
                     pepr_uids={name: d['metadata']['uid'] for name, d in pepr_deployments.items()},
                     pepr_template_fingerprints={name: driver.template_fingerprint(d, True) for name, d in pepr_deployments.items()},
                     render_inputs={'apiVersions': ['apps/v1', 'uds.dev/v1alpha1', 'v1'],
                                    'apiVersionsSHA256': evidence.digest(['apps/v1', 'uds.dev/v1alpha1', 'v1']),
                                    'packageCRD': {'name': 'packages.uds.dev', 'uid': 'crd-uid', 'generation': 1,
                                                   'resourceVersion': '99', 'version': 'v1alpha1', 'schemaSHA256': 'c'*64}},
                     policy_lists={'takserver': {'resourceVersion': '100', 'itemCount': 4},
                                   'istio-system': {'resourceVersion': '101', 'itemCount': 0}})


class PhaseEvidenceTests(unittest.TestCase):
    def snapshot(self):
        bind, data = fixture()
        return evidence.capture(bind, **data)

    def test_complete_projection_reuses_live_guards_and_binds_run(self):
        snapshot = self.snapshot()
        self.assertTrue(snapshot['complete'], snapshot)
        result = evidence.validate_phase(snapshot, driver, snapshot['binding'])
        self.assertTrue(result['accepted'], result)
        self.assertEqual(result['workloadCount'], 8)
        self.assertEqual(result['inventoryCounts']['policies'], 4)
        changed = dict(snapshot['binding'], runID='999')
        self.assertFalse(evidence.validate_phase(snapshot, driver, changed)['accepted'])

    def test_capture_diagnostic_has_fixed_projection_step_without_partial_payload(self):
        cases = [
            ('render_inputs', 'inventory_bound', lambda data: data['render_inputs'].update(apiVersions=['SECRET_SENTINEL'] * (evidence.MAX_ITEMS + 1))),
            ('package_projection', 'malformed_input', lambda data: data['package'].pop('status')),
            ('policy_inventory', 'policy_inventory_incomplete', lambda data: data['policy_lists'].pop('istio-system')),
            ('policy_projection', 'unsupported_policy_condition', lambda data: data['policies'][0]['spec']['rules'][0].update(
                when=[{'key': 'SECRET_SENTINEL', 'values': ['SECRET_SENTINEL']}]))]
        for step, reason, change in cases:
            with self.subTest(step=step):
                bind, data = fixture()
                data['package']['metadata']['annotations'] = {'SECRET_SENTINEL': 'SECRET_SENTINEL'}
                change(data)
                value = evidence.capture(bind, **data)
                self.assertFalse(value['complete'])
                self.assertEqual(value['diagnostic'], {'scope': 'capture', 'step': step, 'reason': reason})
                self.assertNotIn('package', value)
                self.assertNotIn('policies', value)
                self.assertNotIn('SECRET_SENTINEL', json.dumps(value))
                verdict = evidence.validate_phase(value, driver)
                self.assertFalse(verdict['accepted'])
                self.assertEqual(verdict['reason'], 'insufficient_evidence')
                self.assertEqual(verdict['diagnostic'], value['diagnostic'])

    def test_replay_diagnostic_distinguishes_schema_binding_and_guard_rejection(self):
        value = self.snapshot()
        self.assertNotIn('diagnostic', evidence.validate_phase(value, driver))
        for step, change in [
            ('render_inputs', lambda item: item.pop('renderInputs')),
            ('source_binding', lambda item: item.update(guardSHA256='0' * 64)),
            ('inventory_counts', lambda item: item['counts'].update(pods=999)),
            ('application_templates', lambda item: item['deployments'][0].update(templateSHA256='0' * 64))]:
            with self.subTest(step=step):
                changed = copy.deepcopy(value)
                change(changed)
                result = evidence.validate_phase(changed, driver)
                self.assertFalse(result['accepted'])
                self.assertEqual(result['diagnostic']['scope'], 'replay')
                self.assertEqual(result['diagnostic']['step'], step)
                evidence.public_diagnostic(result['diagnostic'])
        for name, step in [('validate_policies', 'policy_guard'), ('validate_workloads', 'application_guard'),
                           ('validate_pepr', 'pepr_guard')]:
            with self.subTest(name=name), mock.patch.object(driver, name, side_effect=ValueError('SECRET_SENTINEL')):
                result = evidence.validate_phase(value, driver)
                self.assertFalse(result['accepted'])
                self.assertEqual(result['diagnostic'], {'scope': 'replay', 'step': step, 'reason': 'guard_rejected'})
                self.assertNotIn('SECRET_SENTINEL', json.dumps(result))

    def test_public_diagnostic_rejects_arbitrary_strings_and_extra_fields(self):
        safe = {'scope': 'capture', 'step': 'policy_projection', 'reason': 'unsupported_schema'}
        self.assertEqual(evidence.public_diagnostic(safe), safe)
        for value in [None, {**safe, 'scope': 'SECRET_SENTINEL'}, {**safe, 'step': 'SECRET_SENTINEL'},
                      {**safe, 'reason': 'SECRET_SENTINEL'}, {**safe, 'name': 'SECRET_SENTINEL'},
                      {**safe, 'step': 'policy_guard'}, {**safe, 'reason': True}]:
            with self.subTest(value=value), self.assertRaises(evidence.EvidenceError):
                evidence.public_diagnostic(value)
        bind, data = fixture()
        with mock.patch.object(evidence, 'package_rules', side_effect=evidence.EvidenceError('SECRET_SENTINEL')):
            value = evidence.capture(bind, **data)
        self.assertEqual(value['diagnostic'], {'scope': 'capture', 'step': 'package_projection', 'reason': 'unsupported_schema'})
        self.assertNotIn('SECRET_SENTINEL', json.dumps(value))

    def test_driver_capture_reuses_observation_inputs_and_recovery_does_not_overwrite(self):
        bind, data = fixture()
        mesh = {'metadata': {'uid': bind['meshConfigUID']}, 'data': {'mesh': 'rootNamespace: istio-system'}}
        with tempfile.TemporaryDirectory() as directory:
            instance = driver.Driver(Path(directory) / 'journal.json')
            instance.state.update(guard={k: bind[k] for k in ('sourceSHA', 'runID', 'runAttempt', 'clusterUID')},
                meshConfigUID=bind['meshConfigUID'], meshConfigHash=driver.sha(mesh['data']['mesh']),
                packageUID=data['package']['metadata']['uid'],
                packageInvariant=driver.package_invariant(data['package']),
                currentAllow=data['package']['spec']['network']['allow'], baselineNetwork=data['baseline_network'],
                deploymentUIDs=data['baseline_uids'], templateFingerprints=data['template_fingerprints'],
                peprUIDs=data['pepr_uids'], peprTemplateFingerprints=data['pepr_template_fingerprints'])
            calls = []
            def get(kind, name=None, namespace='takserver', labels=None):
                calls.append((kind, namespace))
                if namespace == 'pepr-system':
                    if kind == 'deployment':
                        return next(d for d in data['pepr']['deployments'] if d['metadata']['name'] == name)
                    return {'items': data['pepr'][kind]}
                if kind == 'package': return data['package']
                if kind == 'configmap': return mesh
                if kind.startswith('authorization'):
                    policies = [] if namespace == 'istio-system' else data['policies']
                    return {'metadata': {'resourceVersion': '100'}, 'items': policies}
                return {'items': data[{'networkpolicies': 'network_policies'}.get(kind, kind)]}
            instance.get = get
            instance.authorization_policy_list=lambda namespace:get('authorizationpolicies.security.istio.io',namespace=namespace)
            instance.wait = lambda callback: callback()
            instance.observe_render_inputs = lambda: data['render_inputs']
            verdict = instance.capture_phase('strict', 'dedicated')
            self.assertTrue(verdict['accepted'])
            self.assertEqual(len(calls), 12, 'capture helper must not fetch another observation')
            reference = instance.state['phaseEvidence'][0]['reference']
            stored = evidence.read_phase(Path(directory) / 'phases', reference)
            self.assertEqual(stored['binding']['phase'], 'strict')
            self.assertTrue(evidence.validate_phase(stored, driver)['accepted'])
            instance.state['recoveryOnly'] = True
            self.assertTrue(instance.capture_phase('strict', 'dedicated')['accepted'])
            self.assertEqual(len(instance.state['phaseEvidence']), 1)
            self.assertFalse(instance.state['accepted'])
            self.assertEqual(evidence.read_phase(Path(directory) / 'phases', reference), stored)
            with self.assertRaisesRegex(ValueError, 'unsupported extra phase binding'):
                instance.capture_phase('strict', 'dedicated', {'sourceSHA': 'c' * 40})

    def test_old_journal_and_missing_complete_root_inventory_are_insufficient(self):
        for value in ({'schema': 1, 'accepted': True, 'stages': []}, {}):
            self.assertEqual(evidence.validate_phase(value, driver)['reason'], 'insufficient_evidence')
        bind, data = fixture()
        del data['policy_lists']['istio-system']
        value = evidence.capture(bind, **data)
        self.assertFalse(value['complete'])
        self.assertFalse(evidence.validate_phase(value, driver)['accepted'])

    def test_inactive_owner_is_rejected_by_same_new_guard(self):
        bind, data = fixture()
        old = copy.deepcopy(data['replicasets'][0])
        old['metadata']['uid'] = 'inactive-rs'
        old['metadata']['name'] = 'inactive-rs'
        old['spec']['replicas'] = 0
        data['replicasets'].append(old)
        data['pods'][0]['metadata']['ownerReferences'][0]['uid'] = 'inactive-rs'
        value = evidence.capture(bind, **data)
        self.assertTrue(value['complete'])
        with self.assertRaises(ValueError):
            driver.validate_workloads(data['deployments'], data['replicasets'], data['pods'], 'dedicated', data['baseline_uids'])
        self.assertFalse(evidence.validate_phase(value, driver)['accepted'])

    def test_extra_selector_root_allow_is_captured_and_rejected(self):
        bind, data = fixture()
        root = copy.deepcopy(data['policies'][0])
        root['metadata'].update(name='root-extra', namespace='istio-system')
        root['spec']['selector']['matchLabels']['unlisted-label'] = 'possible'
        data['policies'].append(root)
        data['policy_lists']['istio-system']['itemCount'] = 1
        value = evidence.capture(bind, **data)
        self.assertTrue(value['complete'])
        self.assertEqual(value['policies'][-1]['spec']['selector']['matchLabels']['unlisted-label'], 'possible')
        self.assertFalse(evidence.validate_phase(value, driver)['accepted'])

    def test_pepr_old_phase_inactive_owner_and_missing_inventory_fail(self):
        for defect in ('phase', 'owner', 'missing'):
            bind, data = fixture()
            if defect == 'phase':
                data['pepr']['pods'][0]['spec']['containers'][0]['env'][0]['value'] = 'shared'
            elif defect == 'owner':
                old = copy.deepcopy(data['pepr']['replicasets'][0])
                old['metadata']['uid'] = 'old-pepr-rs'
                old['spec']['replicas'] = 0
                data['pepr']['replicasets'].append(old)
                data['pepr']['pods'][0]['metadata']['ownerReferences'][0]['uid'] = 'old-pepr-rs'
            else:
                data['pepr']['deployments'].pop()
            value = evidence.capture(bind, **data)
            self.assertFalse(evidence.validate_phase(value, driver)['accepted'], defect)

    def test_payload_and_full_annotations_never_enter_projection(self):
        bind, data = fixture()
        for obj in data['deployments'] + data['replicasets']:
            obj['spec']['template']['spec']['containers'] = [{'env': [{'value': 'SECRET_SENTINEL'}], 'command': ['SECRET_SENTINEL']}]
            obj['metadata'].setdefault('annotations', {})['unrelated'] = 'SECRET_SENTINEL'
        data['template_fingerprints'] = {d['metadata']['name']: driver.template_fingerprint(d) for d in data['deployments']}
        data['pods'][0]['spec']['containers'] = [{'env': [{'value': 'SECRET_SENTINEL'}]}]
        value = evidence.capture(bind, **data)
        self.assertTrue(value['complete'])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(value))
        self.assertTrue(evidence.validate_phase(value, driver)['accepted'])
        data['policies'][0]['spec']['rules'][0]['when'] = [{'key': 'request.headers[authorization]', 'values': ['SECRET_SENTINEL']}]
        value = evidence.capture(bind, **data)
        self.assertFalse(value['complete'])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(value))

    def test_bounds_inventory_counts_and_source_hash_cannot_be_waived(self):
        for change in ('counts', 'guard', 'capture', 'template', 'network'):
            value = self.snapshot()
            if change == 'counts': value['counts']['pods'] += 1
            if change == 'guard': value['guardSHA256'] = '0'*64
            if change == 'capture': value['captureSHA256'] = '0'*64
            if change == 'template': value['deployments'][0]['templateSHA256'] = '0'*64
            if change == 'network': value['network'][0]['specSHA256'] = '0'*64
            self.assertFalse(evidence.validate_phase(value, driver)['accepted'], change)
        bind, data = fixture()
        data['policies'] *= evidence.MAX_ITEMS
        self.assertFalse(evidence.capture(bind, **data)['complete'])

    def test_render_capability_crd_schema_binding_is_required_and_tamper_evident(self):
        value = self.snapshot()
        original = value['binding']['renderInputsSHA256']
        changed = copy.deepcopy(value)
        changed['renderInputs']['packageCRD']['resourceVersion'] = '100'
        self.assertEqual(evidence.validate_render_inputs(changed['renderInputs'])[1], original)
        self.assertTrue(evidence.validate_phase(changed, driver)['accepted'])
        for defect in ('missing', 'api', 'hash', 'schema', 'uid', 'generation'):
            changed = copy.deepcopy(value)
            if defect == 'missing': del changed['renderInputs']
            if defect == 'api': changed['renderInputs']['apiVersions'].append('unsafe/v1')
            if defect == 'hash': changed['renderInputs']['apiVersionsSHA256'] = '0'*64
            if defect == 'schema': changed['renderInputs']['packageCRD']['schemaSHA256'] = '0'*64
            if defect == 'uid': changed['renderInputs']['packageCRD']['uid'] = 'other-crd'
            if defect == 'generation': changed['renderInputs']['packageCRD']['generation'] += 1
            self.assertFalse(evidence.validate_phase(changed, driver)['accepted'], defect)

    def test_private_write_read_no_overwrite_symlink_hash_or_size_bypass(self):
        value = self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); path.chmod(0o700)
            reference = evidence.write_phase(path, value)
            self.assertEqual(evidence.read_phase(path, reference), value)
            self.assertEqual((path/reference['file']).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): evidence.write_phase(path, value)
            bad = dict(reference, sha256='0'*64)
            with self.assertRaises(evidence.EvidenceError): evidence.read_phase(path, bad)
            (path/'phase-strict.json').unlink()
            (path/'phase-strict.json').symlink_to('/dev/null')
            with self.assertRaises(evidence.EvidenceError): evidence.read_phase(path, reference)
