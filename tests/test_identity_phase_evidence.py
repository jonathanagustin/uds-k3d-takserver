# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline typed guard evidence; never Kubernetes or live migration acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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
