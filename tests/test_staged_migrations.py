# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('staged_migrations', ROOT / '.github/scripts/staged-migrations.py')
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
ENV = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
       'GITHUB_REPOSITORY': 'jonathanagustin/uds-takserver', 'SCENARIO': 'velero', 'ARCHITECTURE': 'amd64',
       'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


class StagedMigrationTests(unittest.TestCase):
    def test_only_explicit_manual_main_selection_is_accepted(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(S.selection(), (['velero'], ['amd64']))
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/feature'),
                           ('GITHUB_REPOSITORY', 'fork/repo'), ('SCENARIO', 'unknown'), ('ARCHITECTURE', '')]:
            with patch.dict(os.environ, {**ENV, key: value}, clear=True), self.assertRaises(ValueError):
                S.selection()
        with patch.dict(os.environ, {**ENV, 'SCENARIO': 'all', 'ARCHITECTURE': 'arm64'}, clear=True):
            self.assertEqual(S.selection(), (['velero', 'identities'], ['arm64']))

    def test_summary_rejects_missing_wrong_source_or_skipped_selected_receipt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ENV, clear=True), patch.object(S, 'verify_public_proofs'):
            directory = Path(tmp)
            with self.assertRaises(ValueError):
                S.verify(directory)
            receipt = {'schema': 1, 'sourceSHA': ENV['GITHUB_SHA'], 'runID': '123', 'runAttempt': '1',
                       'architecture': 'amd64', 'scenarios': ['velero'], 'results': {'velero': 'passed'}, 'accepted': True}
            path = directory / 'amd64.json'
            path.write_text(json.dumps(receipt))
            self.assertTrue(S.verify(directory)['accepted'])
            for changed in ({'sourceSHA': 'b' * 40}, {'runAttempt': '2'}, {'results': {'velero': 'skipped'}},
                            {'scenarios': ['velero', 'identities']}):
                path.write_text(json.dumps({**receipt, **changed}))
                with self.assertRaises(ValueError):
                    S.verify(directory)

    def test_owner_receipt_requires_complete_exact_phase_sequence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ENV, clear=True), patch.object(S.platform, 'machine', return_value='x86_64'):
            directory = Path(tmp)
            owner = directory / 'owner'
            owner.mkdir()
            base = {'schema': 1, 'accepted': True, 'driverSHA256': S.sha(ROOT / 'tests/velero-ownership/drive.py'),
                    'steps': [], 'cluster': {'sourceSHA': ENV['GITHUB_SHA'], 'runID': '123', 'runAttempt': '1', 'clusterUID': 'cluster'},
                    'daemonsetUID': 'agent'}
            for group, stage in [('fresh', 'fresh-core'), ('handoff', 'core-after'), ('handoff', 'local-after')]:
                path = owner / group / (stage + '.json')
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({'stage': stage, 'backupRestore': True, 'observerSHA256': S.sha(ROOT / 'tests/velero-ownership/observe.py'),
                                            'clusterUID': 'cluster', 'daemonsetUID': 'agent', 'retiredCoreConfigAbsent': stage == 'local-after'}))
            for names in ([], S.OWNER_STEPS[:-1], list(reversed(S.OWNER_STEPS))):
                (owner / 'journal.json').write_text(json.dumps({**base, 'steps': [{'name': name, 'status': 'passed'} for name in names]}))
                with self.assertRaisesRegex(ValueError, 'round-trip not accepted'):
                    S.receipt(directory, 'amd64')
            (owner / 'journal.json').write_text(json.dumps({**base, 'steps': [{'name': name, 'status': 'passed'} for name in S.OWNER_STEPS]}))
            self.assertTrue(S.receipt(directory, 'amd64')['accepted'])

    def test_failure_publication_never_copies_private_data_and_stays_unaccepted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ENV, clear=True):
            directory = Path(tmp) / 'private'
            (directory / 'owner').mkdir(parents=True)
            (directory / 'owner/journal.json').write_text(json.dumps({'steps': [{'name': 'fresh-core-agent', 'status': 'failed', 'message': 'secretneedle'}],
                                                                     'private': 'secretneedle'}))
            (directory / 'PRIVATE-command-failure.txt').write_text('secretneedle')
            output = Path(tmp) / 'public'
            result = S.publish(directory, output, 'amd64')
            self.assertFalse(result['accepted'])
            published = ''.join(path.read_text() for path in output.rglob('*.json'))
            self.assertNotIn('secretneedle', published)
            self.assertIn('fresh-core-agent', published)
            with self.assertRaises(ValueError):
                S.verify(output / 'receipts')

    def test_real_publisher_and_summary_bind_actual_sanitized_proof_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ENV, clear=True), patch.object(S.platform, 'machine', return_value='x86_64'):
            directory = Path(tmp) / 'private'
            (directory / 'owner').mkdir(parents=True)
            guard = {'sourceSHA': ENV['GITHUB_SHA'], 'runID': '123', 'runAttempt': '1', 'clusterUID': '1' * 36}
            journal = {'schema': 1, 'accepted': True, 'driverSHA256': S.sha(ROOT / 'tests/velero-ownership/drive.py'),
                       'steps': [{'name': name, 'status': 'passed'} for name in S.OWNER_STEPS],
                       'cluster': guard, 'daemonsetUID': '2' * 36}
            (directory / 'owner/journal.json').write_text(json.dumps(journal))
            for group, stage, suffix in [('fresh', 'fresh-core', 'fresh'), ('handoff', 'core-after', 'core'), ('handoff', 'local-after', 'local')]:
                path = directory / 'owner' / group / (stage + '.json')
                path.parent.mkdir(exist_ok=True)
                name = 'tak-ci-123-1-' + suffix
                proof = {'schema': 1, 'stage': stage, 'observerSHA256': S.sha(ROOT / 'tests/velero-ownership/observe.py'),
                         'clusterUID': guard['clusterUID'], 'daemonsetUID': journal['daemonsetUID'],
                         'observedAt': '2026-11-10T00:00:00+00:00', 'backupRestore': True, 'retiredCoreConfigAbsent': stage == 'local-after',
                         'releaseManifestHashes': {'localManifest': 'a' * 64, 'coreManifest': 'b' * 64},
                         'agentSpec': {'selector': {'matchLabels': {'name': 'node-agent'}},
                                       'owner': ['uds-takserver-config', 'takserver'] if suffix == 'local' else ['velero', 'velero'],
                                       'resourceVersion': '123', 'status': {'numberReady': 1}},
                         'backup': name, 'restore': name + '-r',
                         'volumeCopies': {key: [{'namespace': 'takserver', 'volume': 'data', 'phase': 'Completed', 'name': key + '-data'}] for key in ('pvb', 'pvr')}}
                path.write_text(json.dumps(proof))
            public = Path(tmp) / 'public'
            self.assertTrue(S.publish(directory, public, 'amd64')['accepted'])
            self.assertTrue(S.verify(public / 'receipts')['accepted'])
            (public / 'proofs/amd64/local-after.json').unlink()
            with self.assertRaises((ValueError, OSError, KeyError)):
                S.verify(public / 'receipts')

    def test_accepted_receipt_cannot_pass_without_underlying_public_proofs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ENV, clear=True):
            directory = Path(tmp)
            (directory / 'progress.json').write_text(json.dumps({'accepted': True, 'ownerSteps': [{'name': name, 'status': 'passed'} for name in S.OWNER_STEPS]}))
            value = {'scenarios': ['velero'], 'publishedProofHashes': {'progress': S.sha(directory / 'progress.json')}}
            with self.assertRaises((ValueError, OSError, KeyError)):
                S.verify_public_proofs(directory, value)

    def test_public_observer_drops_raw_controller_messages_and_extra_nested_fields(self):
        with patch.dict(os.environ, ENV, clear=True):
            proof = {'schema': 1, 'stage': 'local-after', 'observerSHA256': 'a' * 64,
                     'clusterUID': '1' * 36, 'daemonsetUID': '2' * 36, 'observedAt': '2026-11-10T00:00:00+00:00',
                     'backupRestore': True, 'retiredCoreConfigAbsent': True,
                     'releaseManifestHashes': {'localManifest': 'b' * 64, 'coreManifest': 'c' * 64},
                     'agentSpec': {'selector': {'matchLabels': {'name': 'node-agent'}}, 'owner': ['uds-takserver-config', 'takserver'],
                                   'resourceVersion': '123', 'status': {'numberReady': 1, 'conditions': [{'message': 'secretneedle'}]},
                                   'secret': 'secretneedle'},
                     'backup': 'tak-ci-123-1-local', 'restore': 'tak-ci-123-1-local-r',
                     'volumeCopies': {key: [{'namespace': 'takserver', 'volume': 'data', 'phase': 'Completed',
                                            'name': key + '-data', 'private': 'secretneedle'}] for key in ('pvb', 'pvr')}}
            public = S.sanitize_observer(proof, 'local-after')
            self.assertNotIn('secretneedle', json.dumps(public))
            self.assertTrue(public['retiredCoreConfigAbsent'])
            self.assertEqual(public['agentSpec']['status'], {'numberReady': 1})

    def test_manual_workflow_has_no_automatic_triggers_or_blanket_matrix(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/staged-migrations.yaml').read_text())
        # PyYAML 1.1 treats the unquoted GitHub `on` key as true.
        trigger = workflow.get('on', workflow.get(True))
        self.assertEqual(set(trigger), {'workflow_dispatch'})
        self.assertEqual(trigger['workflow_dispatch']['inputs']['architecture']['default'], 'amd64')
        self.assertEqual(trigger['workflow_dispatch']['inputs']['scenario']['default'], 'velero')
        self.assertEqual(workflow['jobs']['trial']['strategy']['matrix'], '${{ fromJSON(needs.plan.outputs.matrix) }}')
        self.assertEqual(workflow['jobs']['summary']['if'], 'always()')
        steps = workflow['jobs']['trial']['steps']
        names = [step.get('name', '') for step in steps]
        self.assertLess(names.index('Refuse a remote daemon before runner or cluster work'), names.index('Prepare the disposable runner'))
        upload = next(step for step in steps if step.get('name') == 'Upload exact-run sanitized acceptance evidence')
        self.assertEqual(upload['with']['path'], 'out/staged-public-${{ matrix.arch }}/')
        script = (ROOT / '.github/scripts/staged-migrations.sh').read_text()
        self.assertLess(script.index('ephemeral-cluster.py bootstrap'), script.index('SLIM_CORE_VERSION=1.16.0'))
        self.assertNotIn('create-dev-package', script)
        self.assertIn('dev-package.sh prebuilt', script)
        self.assertNotIn('--force-conflicts', script)


if __name__ == '__main__':
    unittest.main()
