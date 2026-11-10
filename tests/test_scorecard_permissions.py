# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline caller/callee permission contracts; no workflow dispatch or token use."""
import copy
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ('defenseunicorns/uds-common/.github/workflows/callable-scorecard.yaml@'
            '9cb4ebfd9f9a5efd1dbc454bf3aae843d0b57b9f')
# Extracted policy fixture for that exact reusable workflow: top read-all,
# run job security-events:write for SARIF and id-token:write for badge publication.
# These are the explicit read scopes its current local caller already grants.
READS = {'actions', 'artifact-metadata', 'attestations', 'checks', 'code-quality',
         'contents', 'deployments', 'discussions', 'drives', 'issues', 'models',
         'packages', 'pages', 'pull-requests', 'repository-projects', 'statuses',
         'vulnerability-alerts'}
UPSTREAM_WRITES = {'security-events': 'write', 'id-token': 'write'}
CONTRACT = {**dict.fromkeys(READS, 'read'), **UPSTREAM_WRITES}


def valid_call_contract(caller, wrapper):
    """The immutable upstream default requires the complete explicit read map."""
    return (caller['permissions'] == wrapper['permissions'] == 'read-all' and
            caller['jobs']['run']['permissions'] == CONTRACT and
            wrapper['jobs']['analyze']['permissions'] == CONTRACT and
            wrapper['jobs']['analyze']['uses'] == UPSTREAM)


class ScorecardPermissionTests(unittest.TestCase):
    def setUp(self):
        self.caller = yaml.safe_load((ROOT / '.github/workflows/scorecard.yaml').read_text())
        self.wrapper = yaml.safe_load((ROOT / '.github/workflows/scorecard-analysis.yaml').read_text())

    def test_actual_caller_preserves_upstream_read_all_and_publisher_grants(self):
        self.assertTrue(valid_call_contract(self.caller, self.wrapper))
        for permission in READS:
            self.assertEqual(self.wrapper['jobs']['analyze']['permissions'][permission], 'read')
        self.assertEqual({key: value for key, value in self.wrapper['jobs']['analyze']['permissions'].items()
                          if value == 'write'}, UPSTREAM_WRITES)

    def test_no_workflow_default_write_or_unrelated_job_write_grants(self):
        self.assertEqual(self.wrapper['permissions'], 'read-all')
        jobs_with_writes = {name for name, job in self.wrapper['jobs'].items()
                            if job.get('permissions') == 'write-all' or
                            (isinstance(job.get('permissions'), dict) and
                             'write' in job['permissions'].values())}
        self.assertEqual(jobs_with_writes, {'analyze'})
        # A future job without an override inherits read-all, not publisher writes.
        fixture = copy.deepcopy(self.wrapper)
        fixture['jobs']['inspect'] = {'runs-on': 'ubuntu-latest', 'steps': [{'run': 'true'}]}
        self.assertEqual(fixture['jobs']['inspect'].get('permissions', fixture['permissions']), 'read-all')

    def test_every_read_scope_and_required_write_is_needed_for_call_contract(self):
        for scope in CONTRACT:
            with self.subTest(scope=scope):
                fixture = copy.deepcopy(self.wrapper)
                del fixture['jobs']['analyze']['permissions'][scope]
                self.assertFalse(valid_call_contract(self.caller, fixture))
        for scope in UPSTREAM_WRITES:
            fixture = copy.deepcopy(self.wrapper)
            fixture['jobs']['analyze']['permissions'][scope] = 'read'
            self.assertFalse(valid_call_contract(self.caller, fixture))

    def test_original_global_publisher_grants_are_not_read_only_defaults(self):
        fixture = copy.deepcopy(self.wrapper)
        fixture['permissions'] = fixture['jobs']['analyze'].pop('permissions')
        self.assertFalse(valid_call_contract(self.caller, fixture))

    def test_reusable_reference_and_restricted_secret_hop_are_preserved(self):
        self.assertEqual(self.caller['jobs']['run']['uses'], './.github/workflows/scorecard-analysis.yaml')
        self.assertEqual(self.wrapper['jobs']['analyze']['uses'], UPSTREAM)
        self.assertEqual(self.wrapper['jobs']['analyze']['secrets'], 'inherit')
        self.assertEqual(set(self.caller['jobs']['run']['secrets']), {'SCORECARD_READ_TOKEN'})


if __name__ == '__main__':
    unittest.main()
