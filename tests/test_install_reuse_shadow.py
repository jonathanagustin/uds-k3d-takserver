# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline policy fixtures are NOT cryptographic qualification or CI acceptance."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/install-reuse-shadow.py'
SPEC = importlib.util.spec_from_file_location('shadow', SCRIPT)
SHADOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHADOW)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.base, self.head, self.merge, self.target, self.policy, self.tree = [c * 40 for c in '123456']
        self.workflow = b'name: reviewed fixture\n'
        self.receipt = {
            'schema_version': 1, 'kind': 'install-execution', 'reuse_authorized': False,
            'source': {'repository': SHADOW.REPO, 'checkout_commit': self.merge, 'checkout_tree': self.tree},
            'workflow': {'path': SHADOW.WORKFLOW, 'sha256': hashlib.sha256(self.workflow).hexdigest()},
            'run': {'id': 100, 'attempt': 2, 'event': 'pull_request', 'job': 'validate-install'},
            'scenario': {'name': 'install', 'architecture': 'amd64', 'mode': 'ordinary'},
            'execution': {'step': 'Test', 'result': 'success'},
            'inputs': {'package_key': 'amd64-' + 'a' * 16, 'package_archive_sha256': 'sha256:' + 'a' * 64,
                       'checkpoint_oci_digest': 'sha256:' + 'b' * 64, 'core_oci_digest': 'sha256:' + 'c' * 64,
                       'uds_version': '0.41.0',
                       'image_digests': {name: 'sha256:' + 'd' * 64 for name in SHADOW.ENCODER.IMAGES}}}
        self.pr = {'number': 5, 'state': 'closed', 'merged': True, 'merge_commit_sha': self.target,
                   'base': {'ref': 'main', 'sha': self.base, 'repo': {'full_name': SHADOW.REPO}},
                   'head': {'sha': self.head, 'repo': {'full_name': SHADOW.REPO}}}
        self.run = {'id': 100, 'workflow_id': 20, 'path': SHADOW.WORKFLOW, 'event': 'pull_request',
                    'head_sha': self.head, 'head_repository': {'full_name': SHADOW.REPO, 'id': 1427088300},
                    'status': 'completed', 'conclusion': 'success', 'run_attempt': 2,
                    'pull_requests': [{'number': 5}]}
        self.job = {'id': 30, 'name': 'validate-install (amd64)', 'status': 'completed',
                    'conclusion': 'success', 'run_id': 100, 'run_attempt': 2,
                    'steps': [self.step(name) for name in ('Test', 'Authenticate optional install receipt',
                                                         'Upload authenticated install receipt')]}
        self.artifact = {'id': 40, 'name': 'install-receipt-X64-online-100-2', 'expired': False}
        self.api = mock.Mock()
        self.gets = {'pulls/5': self.pr,
                     f'git/commits/{self.merge}': {'sha': self.merge, 'tree': {'sha': self.tree},
                                                 'parents': [{'sha': self.base}, {'sha': self.head}]},
                     f'git/commits/{self.target}': {'sha': self.target, 'tree': {'sha': self.tree},
                                                  'parents': [{'sha': self.base}]},
                     'actions/workflows/test.yaml': {'id': 20}, 'actions/runs/100': self.run}
        self.api.get.side_effect = lambda path: self.gets[path]
        self.api.file.return_value = self.workflow
        self.runs = [self.run]
        self.jobs = [self.job]
        self.artifacts = [self.artifact]
        self.api.pages.side_effect = lambda path, key: {'workflow_runs': self.runs, 'jobs': self.jobs,
                                                       'artifacts': self.artifacts}[key]

    @staticmethod
    def step(name):
        return {'name': name, 'status': 'completed', 'conclusion': 'success'}

    def verification(self, raw):
        # Structural policy fixture only. CLI obtains this exclusively from gh crypto verification.
        ref = 'refs/pull/5/merge'
        signer = f'https://github.com/{SHADOW.REPO}/{SHADOW.WORKFLOW}@{ref}'
        invocation = f'https://github.com/{SHADOW.REPO}/actions/runs/100/attempts/2'
        cert = {'issuer': 'https://token.actions.githubusercontent.com', 'subjectAlternativeName': signer,
                'buildSignerURI': signer, 'buildSignerDigest': self.merge,
                'sourceRepositoryDigest': self.merge, 'sourceRepositoryURI': f'https://github.com/{SHADOW.REPO}',
                'sourceRepositoryRef': ref, 'sourceRepositoryIdentifier': '1427088300',
                'sourceRepositoryOwnerIdentifier': '5193877', 'runnerEnvironment': 'github-hosted',
                'runInvocationURI': invocation, 'buildTrigger': 'pull_request',
                'buildConfigURI': signer, 'buildConfigDigest': self.merge}
        statement = {'_type': 'https://in-toto.io/Statement/v1',
                     'predicateType': 'https://slsa.dev/provenance/v1',
                     'subject': [{'name': f'install-receipt-{self.receipt["scenario"]["name"]}-amd64.json',
                                  'digest': {'sha256': hashlib.sha256(raw).hexdigest()}}],
                     'predicate': {'buildDefinition': {
                         'buildType': 'https://actions.github.io/buildtypes/workflow/v1',
                         'externalParameters': {'workflow': {'path': SHADOW.WORKFLOW, 'ref': ref,
                                                            'repository': f'https://github.com/{SHADOW.REPO}'}},
                         'resolvedDependencies': [{'digest': {'gitCommit': self.merge},
                                                   'uri': f'git+https://github.com/{SHADOW.REPO}@{ref}'}]},
                         'runDetails': {'metadata': {'invocationId': invocation}}}}
        return [{'verificationResult': {'signature': {'certificate': cert}, 'statement': statement}}]

    def result(self, verified_change=None):
        raw = json.dumps(self.receipt).encode()
        self.api.artifact.return_value = raw
        verified = self.verification(raw)
        if verified_change:
            verified_change(verified)
        result = SHADOW.shadow(self.api, raw, verified, 5, self.target, self.policy)
        self.assertFalse(result['reuse_authorized'])
        self.assertEqual(result['decision'], 'execute-fresh')
        return result

    def test_structural_evidence_can_pass_but_always_requires_fresh(self):
        result = self.result()
        self.assertTrue(result['evidence_qualified'])
        self.assertIn('prospective-input-equivalence-not-proven', result['blockers'])

    def test_schema_unknown_fields_and_true_authorization_refused(self):
        for key, value in [('schema_version', 2), ('reuse_authorized', True), ('extra', 'secret')]:
            with self.subTest(key=key):
                prior = copy.deepcopy(self.receipt)
                self.receipt[key] = value
                self.assertFalse(self.result()['evidence_qualified'])
                self.receipt = prior

    def test_synthetic_parents_and_target_tree_must_match_exactly(self):
        for change in ('source-parent', 'target-parent', 'tree', 'target-two-parents'):
            with self.subTest(change=change):
                saved = copy.deepcopy(self.gets)
                if change == 'source-parent':
                    self.gets[f'git/commits/{self.merge}']['parents'].reverse()
                elif change == 'target-parent':
                    self.gets[f'git/commits/{self.target}']['parents'][0]['sha'] = self.head
                elif change == 'tree':
                    self.gets[f'git/commits/{self.target}']['tree']['sha'] = 'f' * 40
                else:
                    self.gets[f'git/commits/{self.target}']['parents'].append({'sha': self.head})
                self.assertFalse(self.result()['evidence_qualified'])
                self.gets = saved

    def test_pr423_stale_snapshot_uses_actual_tested_base_not_metadata(self):
        # Actual observed PR423 base/head/synthetic/tree values. The target
        # commit and crypto object are STRUCTURAL fixtures, not a real squash
        # or signature claim. Authentic qualification is a separate live probe.
        stale_snapshot = '904905f0a88dca238e9a283280e13f1017e8ed5d'
        tested_base = '8691a11b0db743923cbe99f8c3f486a9bfa3b04d'
        tested_head = '2a5afcf2244de21271ba688bd348b9f10c3188d3'
        tested_merge = '0109e4ac6bb05801fb6460b0c4274afbff3e0078'
        tested_tree = 'f8b066fe58de38ed2547bb0b9de7534684d48a46'
        self.gets[f'git/commits/{tested_merge}'] = {
            'sha': tested_merge, 'tree': {'sha': tested_tree},
            'parents': [{'sha': tested_base}, {'sha': tested_head}]}
        self.merge = tested_merge
        self.pr['base']['sha'] = stale_snapshot
        self.pr['head']['sha'] = tested_head
        self.run['head_sha'] = tested_head
        self.receipt['source'].update(checkout_commit=tested_merge, checkout_tree=tested_tree)
        self.gets[f'git/commits/{self.target}'].update(
            tree={'sha': tested_tree}, parents=[{'sha': tested_base}])
        result = self.result()
        self.assertTrue(result['evidence_qualified'])
        self.assertFalse(result['reuse_authorized'])
        for blocker in ('prospective-input-equivalence-not-proven',
                        'execution-class-policy-not-established',
                        'complete-producer-dependency-policy-not-established',
                        'consumer-enforcement-not-enabled'):
            self.assertIn(blocker, result['blockers'])

    def test_actual_base_change_is_rejected_even_when_pr_snapshot_matches_target(self):
        # Equal trees do not excuse a different actual main base after testing.
        advanced = 'a' * 40
        self.pr['base']['sha'] = advanced
        self.gets[f'git/commits/{self.target}']['parents'] = [{'sha': advanced}]
        self.assertFalse(self.result()['evidence_qualified'])

    def test_changed_current_pr_head_is_not_the_tested_head(self):
        self.pr['head']['sha'] = 'a' * 40
        self.run['head_sha'] = self.pr['head']['sha']
        self.assertFalse(self.result()['evidence_qualified'])

    def test_missing_extra_or_malformed_parents_fail_closed(self):
        for source_parents, target_parents in (([], [{'sha': self.base}]),
                                                ([{'sha': self.base}], [{'sha': self.base}]),
                                                ([{'sha': self.base}, {'sha': self.head}], []),
                                                ([{'sha': 'invalid'}, {'sha': self.head}],
                                                 [{'sha': 'invalid'}])):
            self.gets[f'git/commits/{self.merge}']['parents'] = source_parents
            self.gets[f'git/commits/{self.target}']['parents'] = target_parents
            self.assertFalse(self.result()['evidence_qualified'])

    def test_open_or_fork_pr_is_not_same_repository_squash(self):
        for change in ('open', 'fork', 'wrong-merge'):
            saved = copy.deepcopy(self.pr)
            if change == 'open':
                self.pr['merged'] = False
            elif change == 'fork':
                self.pr['head']['repo']['full_name'] = 'other/fork'
            else:
                self.pr['merge_commit_sha'] = self.head
            self.assertFalse(self.result()['evidence_qualified'])
            self.pr.clear()
            self.pr.update(saved)

    def test_newer_failure_or_later_attempt_prevents_old_green(self):
        self.runs.append({**self.run, 'id': 101, 'conclusion': 'failure'})
        self.assertFalse(self.result()['evidence_qualified'])
        self.runs.pop()
        self.run['run_attempt'] = 3
        self.assertFalse(self.result()['evidence_qualified'])

    def test_postmerge_empty_pr_array_keeps_signed_selected_run(self):
        self.run['pull_requests'] = []
        self.assertTrue(self.result()['evidence_qualified'])

    def test_newer_failed_cancelled_or_queued_empty_pr_array_invalidates_old_green(self):
        self.run['pull_requests'] = []
        for status, conclusion in (('completed', 'failure'), ('completed', 'cancelled'), ('queued', None)):
            self.runs.append({**self.run, 'id': 101, 'status': status, 'conclusion': conclusion,
                              'pull_requests': []})
            self.assertIn('not-latest-applicable-run', self.result()['blockers'])
            self.runs.pop()

    def older_run(self, status, conclusion, attempt):
        self.runs.append({**self.run, 'id': 99, 'run_attempt': attempt, 'status': status,
                          'conclusion': conclusion, 'pull_requests': []})
        return self.result()

    def test_older_id_queued_rerun_cannot_be_masked_by_newer_green(self):
        result = self.older_run('queued', None, 2)
        self.assertIn('other-applicable-run-unsettled-or-rerun-order-unproven', result['blockers'])

    def test_older_id_running_rerun_cannot_be_masked_by_newer_green(self):
        result = self.older_run('in_progress', None, 2)
        self.assertIn('other-applicable-run-unsettled-or-rerun-order-unproven', result['blockers'])

    def test_older_id_failed_rerun_cannot_be_masked_by_newer_green(self):
        result = self.older_run('completed', 'failure', 2)
        self.assertIn('other-applicable-run-unsettled-or-rerun-order-unproven', result['blockers'])

    def test_older_id_cancelled_rerun_cannot_be_masked_by_newer_green(self):
        result = self.older_run('completed', 'cancelled', 2)
        self.assertIn('other-applicable-run-unsettled-or-rerun-order-unproven', result['blockers'])

    def test_older_id_unsettled_first_attempt_also_requires_fresh(self):
        for status in ('queued', 'in_progress'):
            result = self.older_run(status, None, 1)
            self.assertIn('other-applicable-run-unsettled-or-rerun-order-unproven', result['blockers'])
            self.runs.pop()

    def test_known_older_completed_first_attempt_can_be_superseded(self):
        for conclusion in ('failure', 'cancelled'):
            result = self.older_run('completed', conclusion, 1)
            self.assertTrue(result['evidence_qualified'])
            self.runs.pop()

    def test_run_list_identity_must_match_query_even_for_older_rows(self):
        for change in ({'event': 'push'}, {'head_sha': 'a' * 40}, {'workflow_id': 21},
                       {'head_repository': {}}, {'head_repository': {'full_name': SHADOW.REPO}},
                       {'head_repository': {'full_name': 'other/fork', 'id': 1427088300}},
                       {'head_repository': {'full_name': SHADOW.REPO, 'id': 99}},
                       {'run_attempt': None}):
            self.runs.append({**self.run, 'id': 99, **change})
            self.assertIn('run-list-identity-missing-contradictory-or-ambiguous', self.result()['blockers'])
            self.runs.pop()

    def test_positively_identified_foreign_fork_does_not_supersede_same_repo_run(self):
        self.runs.append({**self.run, 'id': 101,
                          'head_repository': {'full_name': 'other/fork', 'id': 99}})
        self.assertTrue(self.result()['evidence_qualified'])

    def test_missing_selected_run_and_duplicate_run_ids_fail_fresh(self):
        self.runs[:] = [{**self.run, 'id': 99}]
        self.assertFalse(self.result()['evidence_qualified'])
        self.runs[:] = [self.run, copy.deepcopy(self.run)]
        self.assertFalse(self.result()['evidence_qualified'])

    def test_selected_run_listing_cannot_mask_changed_attempt_or_result(self):
        for change in ({'run_attempt': 3}, {'status': 'queued', 'conclusion': None},
                       {'conclusion': 'failure'}):
            self.runs[:] = [{**self.run, **change}]
            self.assertIn('selected-run-list-attempt-or-result-changed', self.result()['blockers'])
        self.runs[:] = [self.run]

    def test_actual_execution_failure_skip_missing_or_duplicate_rejected(self):
        for state in ('failure', 'skipped', 'missing', 'duplicate'):
            saved = copy.deepcopy(self.job['steps'])
            if state == 'missing':
                self.job['steps'].pop(0)
            elif state == 'duplicate':
                self.job['steps'].append(self.step('Test'))
            else:
                self.job['steps'][0]['conclusion'] = state
            self.assertFalse(self.result()['evidence_qualified'])
            self.job['steps'] = saved

    def test_offline_requires_real_cleanup_success(self):
        self.receipt['scenario']['name'] = 'install-airgap'
        name = 'Install and test without node internet egress'
        self.receipt['execution']['step'] = name
        self.job['name'] = 'validate-install (amd64, airgap)'
        self.job['steps'][0]['name'] = name
        self.artifact['name'] = 'install-receipt-X64-airgap-100-2'
        self.assertFalse(self.result()['evidence_qualified'])
        self.job['steps'].append(self.step('Restore airgap node egress'))
        self.assertTrue(self.result()['evidence_qualified'])

    def test_duplicate_job_or_artifact_and_expired_artifact_rejected(self):
        self.jobs.append(copy.deepcopy(self.job))
        self.assertFalse(self.result()['evidence_qualified'])
        self.jobs.pop()
        self.artifacts.append(copy.deepcopy(self.artifact))
        self.assertFalse(self.result()['evidence_qualified'])
        self.artifacts.pop()
        self.artifact['expired'] = True
        self.assertFalse(self.result()['evidence_qualified'])

    def test_issuer_invocation_subject_and_repository_id_exact_binding(self):
        for key in ('issuer', 'runInvocationURI', 'sourceRepositoryIdentifier', 'buildSignerDigest'):
            def alter(v, key=key):
                v[0]['verificationResult']['signature']['certificate'][key] = 'wrong'
            self.assertFalse(self.result(alter)['evidence_qualified'])
        def altered_subject(v):
            v[0]['verificationResult']['statement']['subject'][0]['digest']['sha256'] = '0' * 64
        self.assertFalse(self.result(altered_subject)['evidence_qualified'])

    def test_reviewed_workflow_and_helpers_not_just_content_key(self):
        self.api.file.side_effect = lambda commit, path: self.workflow if commit == self.merge else b'changed'
        self.assertFalse(self.result()['evidence_qualified'])

    def test_api_failure_becomes_bounded_fresh_result(self):
        self.api.get.side_effect = SHADOW.Unavailable('command-failed')
        result = self.result()
        self.assertFalse(result['evidence_qualified'])
        self.assertEqual(result['blockers'][0], 'command-failed')

    def test_signed_receipt_must_equal_actual_artifact_bytes(self):
        self.api.artifact.side_effect = lambda artifact_id: b'other'
        self.assertIn('artifact-receipt-bytes-mismatch', self.result()['blockers'])


class TransportTests(unittest.TestCase):
    def test_all_pages_including_expected_total_and_unique_ids(self):
        api = SHADOW.GitHub('unused')
        api.get = mock.Mock(side_effect=[{'total_count': 101, 'jobs': [{'id': i} for i in range(100)]},
                                         {'total_count': 101, 'jobs': [{'id': 100}]}])
        self.assertEqual(len(api.pages('jobs', 'jobs')), 101)
        self.assertIn('page=2', api.get.call_args.args[0])

    def test_missing_or_changed_page_and_duplicate_ids_fail(self):
        for second in ({'total_count': 101, 'jobs': []}, {'total_count': 102, 'jobs': [{'id': 100}]},
                       {'total_count': 101, 'jobs': [{'id': 99}]}):
            api = SHADOW.GitHub('unused')
            api.get = mock.Mock(side_effect=[{'total_count': 101, 'jobs': [{'id': i} for i in range(100)]}, second])
            with self.assertRaises(SHADOW.Unavailable):
                api.pages('jobs', 'jobs')

    def test_archive_rejects_traversal_symlink_extra_entries_and_large_payload(self):
        for name, mode, data, extra in [('install-receipt-install-amd64.json', stat.S_IFREG, b'ok', False),
                                       ('../escape', stat.S_IFREG, b'bad', False),
                                       ('install-receipt-install-amd64.json', stat.S_IFLNK, b'target', False),
                                       ('install-receipt-install-amd64.json', stat.S_IFREG, b'x' * 65537, False),
                                       ('install-receipt-install-amd64.json', stat.S_IFREG, b'ok', True)]:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, data)
                if extra:
                    archive.writestr('extra', 'bad')
            if name.startswith('install-') and mode == stat.S_IFREG and len(data) == 2 and not extra:
                self.assertEqual(SHADOW.archive_receipt(stream.getvalue()), b'ok')
            else:
                with self.assertRaises(SHADOW.Unavailable):
                    SHADOW.archive_receipt(stream.getvalue())

    def test_real_unavailable_crypto_command_reports_fresh_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / 'receipt.json'
            bundle = Path(temp) / 'bundle.jsonl'
            fixture = PolicyTests()
            fixture.setUp()
            receipt.write_text(json.dumps(fixture.receipt))
            bundle.write_text('{}')
            result = subprocess.run([sys.executable, str(SCRIPT), '--receipt', str(receipt),
                                     '--bundle', str(bundle), '--pr', '5', '--target', fixture.target,
                                     '--policy-ref', fixture.policy, '--gh', '/missing/gh'],
                                    capture_output=True, text=True, check=True)
            value = json.loads(result.stdout)
            self.assertFalse(value['reuse_authorized'])
            self.assertFalse(value['evidence_qualified'])
            self.assertEqual(value['decision'], 'execute-fresh')

    def test_real_cli_malformed_scalar_remains_fresh_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / 'receipt.json'
            bundle = Path(temp) / 'bundle.jsonl'
            receipt.write_text('null')
            bundle.write_text('{}')
            result = subprocess.run([sys.executable, str(SCRIPT), '--receipt', str(receipt),
                                     '--bundle', str(bundle), '--pr', '5', '--target', 'a' * 40,
                                     '--policy-ref', 'b' * 40], capture_output=True, text=True, check=True)
            self.assertEqual(result.stderr, '')
            self.assertEqual(json.loads(result.stdout)['decision'], 'execute-fresh')

    def test_bounded_local_reads_reject_symlinks_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'input'
            source.write_bytes(b'12345')
            self.assertEqual(SHADOW.bounded_file(source, 5), b'12345')
            with self.assertRaises(SHADOW.Unavailable):
                SHADOW.bounded_file(source, 4)
            link = Path(temp) / 'link'
            link.symlink_to(source)
            with self.assertRaises(OSError):
                SHADOW.bounded_file(link, 5)

    def test_deep_json_is_fresh_not_traceback(self):
        value = SHADOW.shadow(None, b'[' * 2000 + b'0' + b']' * 2000, [], 5, 'a' * 40, 'b' * 40)
        self.assertFalse(value['evidence_qualified'])
        self.assertEqual(value['decision'], 'execute-fresh')

    def test_real_timeout_kills_child_and_returns_bounded_reason(self):
        with mock.patch.object(SHADOW, 'COMMAND_TIMEOUT', 0.05):
            with self.assertRaisesRegex(SHADOW.Unavailable, 'command-timeout'):
                SHADOW.command([sys.executable, '-c', 'import time; time.sleep(10)'])

    def test_duplicate_json_fields_are_not_silently_overwritten(self):
        with self.assertRaises(ValueError):
            json.loads('{"schema_version":1,"schema_version":2}', object_pairs_hook=SHADOW.unique_fields)

    def test_real_output_limit_refuses_oversized_child(self):
        with self.assertRaises(SHADOW.Unavailable):
            SHADOW.command([sys.executable, '-c', 'import os; os.write(1, b"x" * (5 * 1024 * 1024))'])


if __name__ == '__main__':
    unittest.main()
