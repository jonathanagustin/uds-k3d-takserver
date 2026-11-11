# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('package_render_gate', HERE / 'decide.py')
GATE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GATE)


class GitEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GITHUB_REPOSITORY': 'fixture/project', 'GITHUB_EVENT_NAME': 'push',
                    'GITHUB_REF': 'refs/heads/main'}
        self.git('init', '-q', '--initial-branch=main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write(GATE.CLASSIFIER, (ROOT / GATE.CLASSIFIER).read_text())
        for name in ('docs/a.md', 'takx/README.md', 'charts/value.yaml', 'tests/test_package_values.py', GATE.WORKFLOW):
            self.write(name, 'initial\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        self.event_path = Path(self.tmp.name) / 'event.json'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], env=self.env,
                                       stderr=subprocess.DEVNULL, text=True, timeout=10)

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self, changes=None):
        for name, value in (changes or {}).items():
            if value is None:
                (self.repo / name).unlink()
            else:
                self.write(name, value)
        self.git('add', '-A')
        self.git('commit', '--allow-empty', '-qm', 'change')
        return self.git('rev-parse', 'HEAD').strip()

    def push_event(self, head):
        self.env['GITHUB_SHA'] = head
        return {'repository': {'full_name': 'fixture/project'}, 'ref': self.env['GITHUB_REF'],
                'before': self.base, 'after': head}

    def evaluate(self, event):
        self.event_path.write_text(json.dumps(event))
        return GATE.evaluate(self.repo, self.event_path, self.env)[0]

    def test_proven_documentation_and_takx_changes_skip(self):
        head = self.commit({'docs/a.md': 'docs\n', 'takx/README.md': 'optional client\n'})
        self.assertFalse(self.evaluate(self.push_event(head)))

    def test_runtime_unknown_and_mixed_changes_render(self):
        for name in ('charts/value.yaml', 'unclassified/new.file'):
            with self.subTest(path=name):
                head = self.commit({'docs/a.md': name, name: 'runtime\n'})
                self.assertTrue(self.evaluate(self.push_event(head)))

    def test_deleted_runtime_path_is_not_lost(self):
        head = self.commit({'charts/value.yaml': None})
        self.assertTrue(self.evaluate(self.push_event(head)))

    def test_deleted_documentation_can_skip(self):
        head = self.commit({'docs/a.md': None})
        self.assertFalse(self.evaluate(self.push_event(head)))

    def test_rename_checks_both_source_and_destination(self):
        self.git('mv', 'charts/value.yaml', 'docs/renamed.md')
        head = self.commit()
        self.assertTrue(self.evaluate(self.push_event(head)))
        self.git('mv', 'docs/a.md', 'charts/from-docs.yaml')
        head = self.commit()
        self.assertTrue(self.evaluate(self.push_event(head)))

    def test_doc_to_doc_rename_can_skip(self):
        self.git('mv', 'docs/a.md', 'docs/renamed.md')
        self.assertFalse(self.evaluate(self.push_event(self.commit())))

    def test_force_paths_bypass_native_matrix_exclusions(self):
        for name in (GATE.WORKFLOW, GATE.CLASSIFIER, 'tests/test_package_values.py',
                     '.github/test-infra/package-render/future-guard.py'):
            with self.subTest(path=name):
                head = self.commit({name: 'changed\n'})
                self.assertTrue(self.evaluate(self.push_event(head)))

    def test_empty_missing_commit_and_bad_events_render(self):
        head = self.commit()
        event = self.push_event(head)
        self.assertTrue(self.evaluate(event))
        for before in ('0' * 40, 'f' * 40, '', '--help'):
            with self.subTest(before=before):
                self.assertTrue(self.evaluate({**event, 'before': before}))
        self.assertTrue(GATE.evaluate(self.repo, Path(self.tmp.name) / 'missing', self.env)[0])
        self.event_path.write_text('{bad json')
        self.assertTrue(GATE.evaluate(self.repo, self.event_path, self.env)[0])
        self.env['GITHUB_EVENT_NAME'] = 'workflow_dispatch'
        self.assertTrue(self.evaluate(event))

    def test_checkout_and_event_identities_must_agree(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        for mutation in ({'after': self.base}, {'repository': {'full_name': 'other/project'}},
                         {'ref': 'refs/heads/other'}):
            self.assertTrue(self.evaluate({**event, **mutation}))
        self.env['GITHUB_SHA'] = self.base
        self.assertTrue(self.evaluate(event))

    def test_exact_pr_merge_parents_are_verified(self):
        self.git('checkout', '-qb', 'topic')
        head = self.commit({'docs/a.md': 'topic docs\n'})
        self.git('checkout', '-q', 'main')
        self.git('merge', '--no-ff', '-qm', 'PR merge', 'topic')
        merge = self.git('rev-parse', 'HEAD').strip()
        self.env.update(GITHUB_EVENT_NAME='pull_request', GITHUB_SHA=merge, GITHUB_REF='refs/pull/17/merge')
        event = {'repository': {'full_name': 'fixture/project'}, 'number': 17,
                 'pull_request': {'base': {'sha': self.base}, 'head': {'sha': head}, 'merge_commit_sha': merge}}
        self.assertFalse(self.evaluate(event))
        for hint in (None, 'private-invalid-merge', self.base):
            cached = {**event, 'pull_request': {**event['pull_request'], 'merge_commit_sha': hint}}
            self.assertFalse(self.evaluate(cached))
        absent = {**event, 'pull_request': dict(event['pull_request'])}
        del absent['pull_request']['merge_commit_sha']
        self.assertFalse(self.evaluate(absent))
        self.assertTrue(self.evaluate({**event, 'pull_request': {**event['pull_request'], 'head': {'sha': self.base}}}))
        self.git('checkout', '-q', 'topic')
        self.assertTrue(self.evaluate(event))  # source HEAD is not the expected merge checkout
        self.env['GITHUB_SHA'] = head
        self.assertTrue(self.evaluate(event))

    def pr_fixture(self, changes):
        self.git('checkout', '-qb', 'topic')
        head = self.commit(changes)
        self.git('checkout', '-q', 'main')
        self.git('merge', '--no-ff', '-qm', 'PR merge', 'topic')
        merge = self.git('rev-parse', 'HEAD').strip()
        self.env.update(GITHUB_EVENT_NAME='pull_request', GITHUB_SHA=merge, GITHUB_REF='refs/pull/17/merge')
        return {'repository': {'full_name': 'fixture/project'}, 'number': 17,
                'pull_request': {'base': {'sha': self.base}, 'head': {'sha': head}}}

    def replace_merge_tree(self, event, changes):
        for name, contents in changes.items():
            self.write(name, contents)
        self.git('add', '-A')
        tree = self.git('write-tree').strip()
        head = event['pull_request']['head']['sha']
        merge = self.git('commit-tree', tree, '-p', self.base, '-p', head, '-m', 'same parents, different tree').strip()
        self.git('checkout', '-q', '--detach', merge)
        self.env['GITHUB_SHA'] = merge

    def test_merge_only_runtime_and_force_inputs_render(self):
        event = self.pr_fixture({'docs/a.md': 'docs-only source\n'})
        self.assertFalse(self.evaluate(event))
        self.replace_merge_tree(event, {'charts/value.yaml': 'merge-only runtime\n'})
        self.assertTrue(self.evaluate(event))
        # A forced validation input must render even though runtime paths ignore it.
        self.replace_merge_tree(event, {'charts/value.yaml': 'initial\n',
                                        'tests/test_package_values.py': 'merge-only contract\n'})
        self.assertTrue(self.evaluate(event))

    def test_runtime_source_reverted_by_merge_still_renders(self):
        event = self.pr_fixture({'charts/value.yaml': 'runtime source\n', 'docs/a.md': 'docs\n'})
        self.replace_merge_tree(event, {'charts/value.yaml': 'initial\n'})
        self.assertTrue(self.evaluate(event))

    def test_merge_only_rename_retains_runtime_endpoint(self):
        event = self.pr_fixture({'docs/a.md': 'docs\n'})
        (self.repo / 'docs').mkdir(exist_ok=True)
        self.git('mv', 'charts/value.yaml', 'docs/renamed.yaml')
        self.replace_merge_tree(event, {})
        self.assertTrue(self.evaluate(event))

    def test_pr_checkout_diff_must_be_complete(self):
        event = self.pr_fixture({'docs/a.md': 'docs\n'})
        real = GATE.git
        for missing in (b'', b'M\0docs/a.md'):
            def incomplete(repo, *args):
                if args[:1] == ('diff',) and args[-2] == self.env['GITHUB_SHA']:
                    return missing
                return real(repo, *args)
            with self.subTest(missing=missing), patch.object(GATE, 'git', side_effect=incomplete):
                self.assertTrue(self.evaluate(event))
        self.env['GITHUB_REF'] = 'refs/pull/18/merge'
        self.assertTrue(self.evaluate(event))

    def test_shallow_exact_merge_with_absent_hint_can_skip(self):
        event = self.pr_fixture({'docs/a.md': 'docs\n'})
        merge = self.env['GITHUB_SHA']
        clone = Path(self.tmp.name) / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--no-checkout', '--depth=2',
                        self.repo.as_uri(), str(clone)], env=self.env, check=True, timeout=10)
        subprocess.run(['git', '-C', str(clone), 'checkout', '-q', '--detach', merge],
                       env=self.env, check=True, timeout=10)
        self.event_path.write_text(json.dumps(event))
        self.assertEqual(GATE.evaluate(clone, self.event_path, self.env),
                         (False, 'verified non-runtime paths'))

    def test_combined_paths_limit_renders(self):
        event = self.pr_fixture({'docs/a.md': 'docs\n'})
        real = GATE.git
        def large_diff(repo, *args):
            if args[:1] == ('diff',):
                return b''.join(b'M\0docs/file-' + str(i).encode() + b'\0' for i in range(5001))
            return real(repo, *args)
        with patch.object(GATE, 'git', side_effect=large_diff):
            self.assertTrue(self.evaluate(event))

    def test_bad_paths_and_incomplete_git_records_render(self):
        head = self.commit({'docs/line\nfile.md': 'ordinary file\n'})
        self.assertTrue(self.evaluate(self.push_event(head)))
        for raw in (b'', b'M\0docs/a.md', b'R100\0docs/a.md\0', b'M\0../escape\0', b'X\0docs/a.md\0'):
            with self.subTest(raw=raw), self.assertRaises(GATE.EvidenceUnavailable):
                GATE.changed_paths(raw)

    def test_git_diff_failure_or_truncation_retains_rendering(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        real = GATE.git
        def failed(repo, *args):
            if args[:1] == ('diff',):
                raise subprocess.CalledProcessError(1, ['git', 'diff'])
            return real(repo, *args)
        with patch.object(GATE, 'git', side_effect=failed):
            self.assertTrue(self.evaluate(event))
        def truncated(repo, *args):
            return b'R100\0docs/a.md\0' if args[:1] == ('diff',) else real(repo, *args)
        with patch.object(GATE, 'git', side_effect=truncated):
            self.assertTrue(self.evaluate(event))

    def test_classifier_failure_or_worktree_drift_retains_rendering(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        self.write(GATE.CLASSIFIER, '#!/bin/bash\nexit 1\n')
        self.assertTrue(self.evaluate(event))
        # Even committed classifier changes must render, never trust their new decision.
        head = self.commit()
        self.assertTrue(self.evaluate(self.push_event(head)))

    def test_classifier_process_error_or_unknown_output_retains_rendering(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        real_run = subprocess.run
        def failed(command, **kwargs):
            if command[:1] == ['bash']:
                raise subprocess.CalledProcessError(1, command)
            return real_run(command, **kwargs)
        with patch.object(GATE.subprocess, 'run', side_effect=failed):
            self.assertTrue(self.evaluate(event))
        def unknown(command, **kwargs):
            if command[:1] == ['bash']:
                return subprocess.CompletedProcess(command, 0, b'runtime=false\nextra\n')
            return real_run(command, **kwargs)
        with patch.object(GATE.subprocess, 'run', side_effect=unknown):
            self.assertTrue(self.evaluate(event))

    def test_uncertainty_reasons_are_fixed_and_private(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        self.event_path.write_text(json.dumps(event))
        private = 'PRIVATE-secret-url-or-path'
        cases = [
            ({**event, 'repository': {'full_name': private}}, 'repository-mismatch'),
            ({**event, 'before': private}, 'commit-unavailable'),
        ]
        for value, code in cases:
            with self.subTest(code=code):
                self.event_path.write_text(json.dumps(value))
                render, reason = GATE.evaluate(self.repo, self.event_path, self.env)
                self.assertTrue(render)
                self.assertEqual(reason, f'evidence unavailable; rendering retained [{code}]')
                self.assertNotIn(private, reason)
        self.event_path.write_text(json.dumps(event))
        for error in (ValueError(private), subprocess.CalledProcessError(1, [private], output=private)):
            with self.subTest(error=type(error).__name__), patch.object(GATE, 'decision', side_effect=error):
                render, reason = GATE.evaluate(self.repo, self.event_path, self.env)
                self.assertTrue(render)
                self.assertEqual(reason, 'evidence unavailable; rendering retained [unclassified-unavailable]')
                self.assertNotIn(private, reason)
        # Arbitrary exception text must never become a public reason code.
        with patch.object(GATE, 'decision', side_effect=GATE.EvidenceUnavailable(private)):
            self.assertEqual(GATE.evaluate(self.repo, self.event_path, self.env),
                             (True, 'evidence unavailable; rendering retained [identity-unavailable]'))

    def test_real_git_failure_has_fixed_reason(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        event = self.push_event(head)
        event['before'] = 'f' * 40
        self.event_path.write_text(json.dumps(event))
        self.assertEqual(GATE.evaluate(self.repo, self.event_path, self.env),
                         (True, 'evidence unavailable; rendering retained [git-evidence-unavailable]'))

    def test_cli_writes_only_its_own_fixed_output(self):
        head = self.commit({'docs/a.md': 'docs\n'})
        self.event_path.write_text(json.dumps(self.push_event(head)))
        output = Path(self.tmp.name) / 'output'
        env = {**self.env, 'GITHUB_EVENT_PATH': str(self.event_path), 'GITHUB_OUTPUT': str(output)}
        result = subprocess.run([sys.executable, '-B', str(HERE / 'decide.py'), '--repo', str(self.repo)],
                                env=env, capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(output.read_text(), 'render=false\n')
        self.assertEqual(result.stdout, '')
        self.assertIn('verified non-runtime', result.stderr)


if __name__ == '__main__':
    unittest.main()
