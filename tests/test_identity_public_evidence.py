# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline synthetic phase publication; not a live migration result."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_staged_migrations import S, ENV, ROOT
from tests.test_identity_phase_evidence import fixture, evidence, driver


class IdentityPublicationTests(unittest.TestCase):
    def journal(self, directory):
        folder = directory/'identity'; folder.mkdir()
        phases = folder/'phases'; phases.mkdir(mode=0o700)
        entries = []
        for phase in ['baseline', 'transition', 'strict', 'rollback', 'shared']:
            bind, data = fixture(); bind['phase'] = phase
            account = 'shared' if phase in ('baseline', 'rollback', 'shared') else 'dedicated'
            data['account'] = account
            for key in ['deployments', 'replicasets', 'pods']:
                for obj in data[key]:
                    spec = obj['spec'] if key == 'pods' else obj['spec']['template']['spec']
                    if account == 'shared': spec['serviceAccountName'] = driver.LEGACY
            pepr_phase = 'shared' if phase == 'baseline' else phase
            for key in ['deployments', 'replicasets', 'pods']:
                for obj in data['pepr'][key]:
                    spec = obj['spec'] if key == 'pods' else obj['spec']['template']['spec']
                    for c in spec['containers']:
                        for e in c['env']:
                            if e['name'] == 'TAK_WORKLOAD_IDENTITY_PHASE': e['value'] = pepr_phase
            snapshot = evidence.capture(bind, **data)
            self.assertTrue(evidence.validate_phase(snapshot, driver)['accepted'], phase)
            entries.append({'phase': phase, 'reference': evidence.write_phase(phases, snapshot)})
        journal = {'schema': 1, 'completed': True, 'accepted': True, 'recoveryOnly': False,
                   'scenario': 'identities', 'architecture': 'amd64',
                   'driverSHA256': S.sha(ROOT/'tests/workload-identities/drive.py'),
                   'probeSourceSHA256': S.sha(ROOT/'tests/workload-identities/ProtocolProbe.java'),
                   'guard': {k: bind[k] for k in ('sourceSHA', 'runID', 'runAttempt', 'clusterUID')},
                   'meshConfigUID': bind['meshConfigUID'], 'meshConfigHash': bind['meshConfigHash'],
                   'stages': [{'stage': stage} for stage in ['traffic-baseline', 'traffic-dual-before-rollout',
                       'traffic-transition', 'traffic-strict', 'traffic-rollback', 'traffic-shared', 'reversed-and-verified']],
                   'phaseEvidence': entries}
        (folder/'journal.json').write_text(json.dumps(journal))
        return journal

    def env(self):
        return patch.dict(os.environ, {**ENV, 'SCENARIO': 'identities'}, clear=True)

    def test_manual_publication_replays_every_phase_and_exports_only_fixed_verdicts(self):
        with tempfile.TemporaryDirectory() as temporary, self.env(), patch.object(S.platform, 'machine', return_value='x86_64'):
            root = Path(temporary); self.journal(root)
            value = S.publish(root, root/'public', 'amd64')
            self.assertTrue(value['accepted'], value)
            summary = json.loads((root/'public/proofs/amd64/identity-phases.json').read_text())
            self.assertEqual(summary['methods'], ['manual'])
            self.assertEqual(len(summary['phaseProofs']['manual']), 5)
            self.assertTrue(S.verify(root/'public/receipts')['accepted'])
            published = ''.join(p.read_text() for p in (root/'public').rglob('*.json'))
            for forbidden in ['containers', 'annotations', 'ownerReferences', 'SECRET_SENTINEL']:
                self.assertNotIn(forbidden, published)

    def test_old_journal_missing_input_and_tampered_snapshot_never_become_accepted(self):
        for defect in ['old', 'missing', 'tampered']:
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temporary, self.env(), patch.object(S.platform, 'machine', return_value='x86_64'):
                root = Path(temporary); journal = self.journal(root)
                if defect == 'old':
                    del journal['phaseEvidence']; (root/'identity/journal.json').write_text(json.dumps(journal))
                else:
                    path = root/'identity/phases'/journal['phaseEvidence'][0]['reference']['file']
                    if defect == 'missing': path.unlink()
                    else: path.write_text('{}')
                value = S.publish(root, root/'public', 'amd64')
                self.assertFalse(value['accepted'])
                self.assertFalse((root/'public/proofs/amd64/identity-phases.json').exists())

    def test_public_hash_missing_phase_extra_payload_or_changed_mesh_fail(self):
        with tempfile.TemporaryDirectory() as temporary, self.env(), patch.object(S.platform, 'machine', return_value='x86_64'):
            root = Path(temporary); self.journal(root); value = S.publish(root, root/'public', 'amd64')
            summary = json.loads((root/'public/proofs/amd64/identity-phases.json').read_text())
            for defect in ['missing', 'payload', 'mesh']:
                altered = copy.deepcopy(summary)
                if defect == 'missing': altered['phaseProofs']['manual'].pop()
                if defect == 'payload': altered['phaseProofs']['manual'][0]['secret'] = 'SECRET_SENTINEL'
                if defect == 'mesh': altered['phaseProofs']['manual'][0]['binding']['meshConfigHash'] = '0'*64
                with self.assertRaises(ValueError): S.verify_identity_summary(altered, value)
            (root/'public/proofs/amd64/identity-phases.json').write_text('{}')
            with self.assertRaises(ValueError): S.verify(root/'public/receipts')

    def package_journal(self, root, fresh=False):
        staging = root/'package-staging'; staging.mkdir()
        journal = self.journal(staging)
        folder = root/'package-identity'; (staging/'identity').rename(folder)
        bindings = {'archiveSHA256': 'd'*64, 'planSHA256': 'e'*64, 'configSHA256': 'f'*64}
        for entry in journal['phaseEvidence']:
            snapshot = evidence.read_phase(folder/'phases', entry['reference'])
            snapshot['binding'].update(packageArchiveSHA256=bindings['archiveSHA256'], baselineValuesSHA256=bindings['configSHA256'])
            (folder/'phases'/entry['reference']['file']).unlink()
            entry['reference'] = evidence.write_phase(folder/'phases', snapshot)
        if fresh:
            snapshot = evidence.read_phase(folder/'phases', journal['phaseEvidence'][2]['reference'])
            snapshot['binding']['phase'] = 'fresh-strict'
            journal['phaseEvidence'].append({'phase': 'fresh-strict', 'reference': evidence.write_phase(folder/'phases', snapshot)})
        journal.update(method='package', packageDriverSHA256='c'*64, inputBindings=bindings,
                       packagePhases=['shared', 'transition', 'strict', 'rollback', 'shared'] + (['strict'] if fresh else []),
                       freshStrictRequested=fresh, freshStrictAccepted=fresh)
        journal['stages'] = []
        for entry in journal['phaseEvidence']:
            alias = entry['phase']
            journal['stages'] += [{'stage': 'traffic-package-'+alias, 'checks': [{'synthetic': True}]},
                                  {'stage': 'package-application-checks', 'phase': alias},
                                  {'stage': 'package-phase-evidence-'+alias, 'accepted': True},
                                  {'stage': 'package-observed-'+alias}]
        if fresh: journal['stages'].append({'stage': 'fresh-strict-verified'})
        journal['stages'].append({'stage': 'package-roundtrip-verified'})
        (folder/'journal.json').write_text(json.dumps(journal))
        return journal

    def test_package_and_fresh_strict_replay_require_actual_ordered_groups_and_bindings(self):
        actual_sha = S.sha
        def sha(path):
            return 'c'*64 if path.name == 'package_roundtrip.py' else actual_sha(path)
        for fresh in [False, True]:
            with self.subTest(fresh=fresh), tempfile.TemporaryDirectory() as temporary, self.env(), patch.object(S.platform, 'machine', return_value='x86_64'), patch.object(S, 'sha', side_effect=sha), patch.dict(os.environ, {'IDENTITY_METHOD': 'package', 'FRESH_STRICT': str(fresh).lower()}):
                root = Path(temporary); journal = self.package_journal(root, fresh)
                value = S.publish(root, root/'public', 'amd64')
                self.assertTrue(value['accepted'], value)
                self.assertTrue(S.verify(root/'public/receipts')['accepted'])
                for defect in ['traffic', 'order', 'archive']:
                    broken = copy.deepcopy(journal)
                    if defect == 'traffic': broken['stages'][0]['checks'] = []
                    if defect == 'order': broken['stages'][0], broken['stages'][1] = broken['stages'][1], broken['stages'][0]
                    if defect == 'archive': broken['inputBindings']['archiveSHA256'] = '0'*64
                    (root/'package-identity/journal.json').write_text(json.dumps(broken))
                    with self.assertRaises(ValueError): S.receipt(root, 'amd64')
                (root/'package-identity/journal.json').write_text(json.dumps(journal))

    def test_combined_request_cannot_reuse_manual_only_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary, self.env(), patch.object(S.platform, 'machine', return_value='x86_64'):
            root = Path(temporary); self.journal(root)
            with patch.dict(os.environ, {'IDENTITY_METHOD': 'combined'}):
                with self.assertRaises((ValueError, OSError)): S.receipt(root, 'amd64')
