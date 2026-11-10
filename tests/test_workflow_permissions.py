# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Permission boundaries for read-only planning and explicit publishing jobs."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def write_scopes(permissions):
    return {name for name, level in permissions.items() if level == 'write'}


def require_dependency_review(document):
    """The official checker, rather than a feature probe, owns API failures."""
    job = document['jobs']['dependency-review']
    actions = [step for step in job['steps']
               if step.get('uses', '').startswith('actions/dependency-review-action@')]
    if len(actions) != 1:
        raise ValueError('one official dependency review action is required')
    action = actions[0]
    if job.get('if') is not None or action.get('if') is not None:
        raise ValueError('dependency review must not be conditionally skipped')
    if any(item.get('continue-on-error', False) is not False for item in (job, action)):
        raise ValueError('dependency review failures must fail the check')
    if any(step.get('id') == 'feature' for step in job['steps']):
        raise ValueError('a feature probe must not replace dependency review')


class WorkflowPermissionTests(unittest.TestCase):
    def test_new_validation_jobs_do_not_inherit_write_or_oidc_access(self):
        for name in ('test.yaml', 'benchmark.yaml', 'full-core.yaml', 'dependency-review.yaml'):
            with self.subTest(workflow=name):
                document = workflow(name)
                self.assertFalse(write_scopes(document['permissions']))
                # GitHub replaces the default permission map at job level.
                # The planner has no override and must remain read-only.
                if name == 'test.yaml':
                    planner = document['jobs']['image-keys']
                    effective = planner.get('permissions', document['permissions'])
                    self.assertFalse(write_scopes(effective))

    def test_container_planner_cannot_publish_even_when_images_are_missing(self):
        document = workflow('container.yaml')
        planner = document['jobs']['plan']
        self.assertEqual(planner['permissions']['packages'], 'read')
        self.assertFalse(write_scopes(planner['permissions']))
        decision = next(step for step in planner['steps'] if step.get('id') == 'image')
        self.assertEqual(decision['env']['CHECK_ONCE'], 'true')
        # Exercise the real helper with a registry that lacks every image.
        # Even its build-capable default must never publish from this planner.
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calls = directory / 'docker-calls.jsonl'
            docker = directory / 'docker'
            docker.write_text('#!' + sys.executable + '\n'
                              'import json,os,sys\n'
                              'with open(os.environ["PERMISSION_TEST_CALLS"],"a") as f: '
                              'f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                              'sys.exit(0 if sys.argv[1:2]==["login"] else 1)\n')
            curl = directory / 'curl'
            curl.write_text('#!' + sys.executable + '\n'
                            'import sys\n'
                            'print("404" if "-w" in sys.argv else \'{"token":"fixture-pull-token"}\')\n')
            docker.chmod(0o755)
            curl.chmod(0o755)
            environment = {**os.environ, 'PATH': str(directory) + os.pathsep + os.defpath,
                           'GH_TOKEN': 'fixture-token', 'IMAGE_TAG': 'immutable-fixture',
                           'GITHUB_WORKFLOW': 'Container', 'BUILD_IF_MISSING': 'true',
                           'CHECK_ONCE': 'true', 'PERMISSION_TEST_CALLS': str(calls)}
            result = subprocess.run(['bash', str(ROOT / '.github/scripts/wait-for-tak-images.sh')],
                                    env=environment, cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            observed = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(len([call for call in observed if call[:2] == ['manifest', 'inspect']]), 6)
            self.assertTrue(all(call[:1] == ['login'] or call[:2] == ['manifest', 'inspect']
                                for call in observed))

    def test_dependency_check_has_no_comment_mutation_capability(self):
        document = workflow('dependency-review.yaml')
        job = document['jobs']['dependency-review']
        self.assertFalse(write_scopes(job.get('permissions', document['permissions'])))
        action = next(step for step in job['steps']
                      if step.get('uses', '').startswith('actions/dependency-review-action@'))
        self.assertEqual(action['with']['comment-summary-in-pr'], 'never')

    def test_dependency_review_cannot_succeed_by_skipping_its_checker(self):
        document = workflow('dependency-review.yaml')
        require_dependency_review(document)
        job = document['jobs']['dependency-review']
        self.assertEqual(job['timeout-minutes'], 15)
        checkout = next(step for step in job['steps']
                        if step.get('uses', '').startswith('actions/checkout@'))
        self.assertIs(checkout['with']['persist-credentials'], False)
        action = next(step for step in job['steps']
                      if step.get('uses', '').startswith('actions/dependency-review-action@'))
        self.assertEqual(action['uses'], 'actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294')
        for target, key, value in (('job', 'if', 'false'), ('action', 'if', "steps.feature.outputs.enabled == 'true'"),
                                   ('job', 'continue-on-error', True), ('action', 'continue-on-error', True),
                                   ('action', 'uses', './unchecked-local-wrapper')):
            changed = copy.deepcopy(document)
            changed_job = changed['jobs']['dependency-review']
            item = changed_job if target == 'job' else next(step for step in changed_job['steps']
                       if step.get('uses', '').startswith('actions/dependency-review-action@'))
            item[key] = value
            with self.subTest(target=target, bypass=key), self.assertRaises(ValueError):
                require_dependency_review(changed)
        changed = copy.deepcopy(document)
        changed['jobs']['dependency-review']['steps'].insert(1, {'id': 'feature', 'run': 'exit 0'})
        with self.assertRaises(ValueError):
            require_dependency_review(changed)

    def test_real_identity_and_publishing_consumers_keep_explicit_grants(self):
        # Configured Chainguard identities use the GitHub OIDC login in the
        # shared setup task. Removing these job grants would break that path.
        consumers = {'test.yaml': ('validate-install', 'validate-upgrade', 'validate-upgrade-pg15'),
                     'benchmark.yaml': ('benchmark',),
                     'full-core.yaml': ('validate-full-core',)}
        for name, jobs in consumers.items():
            for job in jobs:
                with self.subTest(workflow=name, job=job):
                    self.assertEqual(workflow(name)['jobs'][job]['permissions']['id-token'], 'write')
        # A package producer and attestation signer are deliberately distinct
        # from read-only admission. Do not fix the score by disabling them.
        for job in ('build', 'manifest'):
            permissions = workflow('container.yaml')['jobs'][job]['permissions']
            self.assertTrue({'packages', 'id-token', 'attestations'}.issubset(write_scopes(permissions)))


if __name__ == '__main__':
    unittest.main()
