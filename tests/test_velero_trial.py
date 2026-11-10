# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('velero_drive', ROOT / 'tests/velero-ownership/drive.py')
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)


class TrialTests(unittest.TestCase):
    def test_distinct_real_backup_names_without_forging_run_identity(self):
        for suffix in ('', 'fresh', 'core', 'local', 'unreviewed'):
            result = subprocess.run(['bash', '-euc', 'run_id=123; attempt=2; source tests/backup-names.sh; printf "%s %s" "$backup_name" "$restore_name"'],
                                    cwd=ROOT, text=True, capture_output=True,
                                    env={**os.environ, 'BACKUP_TRIAL_SUFFIX': suffix})
            if suffix == 'unreviewed':
                self.assertNotEqual(result.returncode, 0)
            else:
                name = 'tak-ci-123-2' + ('-' + suffix if suffix else '')
                self.assertEqual(result.stdout, name + ' ' + name + '-r')
                self.assertEqual(result.returncode, 0)

    def test_plan_requires_exact_source_and_actual_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = {}
            for name in ('core', 'detach', 'clean', 'config'):
                target = root / name
                if name == 'config':
                    target.write_bytes((ROOT / 'bundle/full/uds-config.yaml').read_bytes())
                else:
                    target.write_text(name)
                inputs[name] = {'path': name, 'sha256': D.digest(target)}
            plan = root / 'plan.json'
            plan.write_text(json.dumps({'schema': 1, 'sourceSHA': 'a' * 40, 'files': inputs}))
            with patch.dict(os.environ, {'GITHUB_SHA': 'a' * 40}):
                self.assertEqual(set(D.load_plan(plan)), set(inputs))
                config = __import__('yaml').safe_load((root / 'config').read_text())
                config['options'] = {'insecure': True}
                (root / 'config').write_text(__import__('yaml').safe_dump(config))
                inputs['config']['sha256'] = D.digest(root / 'config')
                plan.write_text(json.dumps({'schema': 1, 'sourceSHA': 'a' * 40, 'files': inputs}))
                with self.assertRaisesRegex(ValueError, 'only reviewed'):
                    D.load_plan(plan)
                (root / 'core').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    D.load_plan(plan)
            with patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40}):
                with self.assertRaisesRegex(ValueError, 'source'):
                    D.load_plan(plan)

    def test_changed_api_smoke_dependency_is_rejected_by_real_source_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in D.REVIEWED_HELPERS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('reviewed bytes\n')
            calls = []
            def command(argv):
                self.assertEqual(argv[:2], ['git', 'show'])
                self.assertTrue(argv[2].startswith('HEAD:'))
                calls.append(argv[2][5:])
                return 'reviewed bytes\n'
            with patch.object(D, 'ROOT', root):
                D.verify_helpers(command)
                self.assertIn('tests/api-smoke.sh', calls)
                self.assertIn('.github/scripts/checked-pipe.sh', calls)
                self.assertIn('.github/scripts/redact-logs.py', calls)
                (root / 'tests/api-smoke.sh').write_text('changed acceptance behavior')
                with self.assertRaisesRegex(ValueError, 'differs from reviewed'):
                    D.verify_helpers(command)

    def test_deploy_set_key_matches_real_package_variable_declaration(self):
        import yaml
        package = yaml.safe_load((ROOT / 'zarf.yaml').read_text())
        variables = {item['name'] for item in package['variables']}
        with tempfile.TemporaryDirectory() as tmp:
            driver = self.driver(tmp)
            target = Path(tmp) / 'input'
            target.write_text('fixture')
            driver.files = {'core': target, 'config': target}
            driver.state['inputs'] = {'core': D.digest(target), 'config': D.digest(target)}
            driver.idle = lambda: None
            calls = []
            driver.execute = lambda args, **kwargs: calls.append((args, kwargs))
            for owner in ('local', 'core'):
                driver.deploy('core', 'takserver', owner)
                args, options = calls[-1]
                key, value = args[args.index('--set') + 1].split('=')
                prefix, variable = key.split('.')
                self.assertEqual(prefix, package['metadata']['name'])
                self.assertIn(variable, variables)
                self.assertEqual(variable, 'FILESYSTEM_BACKUP_OWNER')
                self.assertEqual(value, owner)
                self.assertEqual(args[args.index('--packages') + 1], prefix)
                self.assertEqual(options['env']['UDS_CONFIG'], str(target))
                self.assertNotIn('--force-conflicts', args)

    def test_excessive_child_stdout_is_killed_without_unbounded_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = Path(tmp) / 'private.txt'
            with self.assertRaisesRegex(ValueError, 'bounded capture limit'):
                D.runner(['python3', '-c', 'import sys; sys.stdout.buffer.write(b"x" * (12 * 1024 * 1024))'],
                         timeout=5, diagnostics=diagnostic)
            self.assertLessEqual(diagnostic.stat().st_size, D.TAIL_LIMIT)
            self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)

    def test_timeout_retains_private_diagnostic_and_kills_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            diagnostic = Path(tmp) / 'private.txt'
            with self.assertRaisesRegex(ValueError, 'timed out'):
                D.runner(['python3', '-c', 'import time; print("specific timed-out stage", flush=True); time.sleep(30)'],
                         timeout=0.1, diagnostics=diagnostic)
            self.assertIn('specific timed-out stage', diagnostic.read_text())
            self.assertEqual(diagnostic.stat().st_mode & 0o777, 0o600)

    def test_candidate_variants_preserve_keep_and_detach_before_config_retirement(self):
        spec = importlib.util.spec_from_file_location('owner_candidate', ROOT / 'tests/velero-ownership/candidate.py')
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
        import yaml
        rendered = subprocess.run(['helm', 'template', 'takserver', str(ROOT / 'charts/takserver'),
                                   '--set', 'backup.filesystem.enabled=true', '--show-only', 'templates/filesystem-backup.yaml'],
                                  text=True, capture_output=True, check=True)
        exemption = next(doc for doc in yaml.safe_load_all(rendered.stdout) if doc['kind'] == 'Exemption')
        original = yaml.safe_load((ROOT / 'bundle/full/uds-bundle.yaml').read_text())
        result = candidate.variants(original, exemption)
        self.assertEqual({p['name'] for p in result['core']['packages']}, {'core-base', 'core-backup-restore', 'takserver'})
        for name, enabled, config in [('core', True, True), ('detach', False, True), ('clean', False, False)]:
            package = next(p for p in result[name]['packages'] if p['name'] == 'core-backup-restore')
            values = {v['path']: v['value'] for v in package['overrides']['velero']['velero']['values']}
            self.assertIs(values['deployNodeAgent'], enabled)
            self.assertEqual(values['nodeAgent']['annotations'], {'helm.sh/resource-policy': 'keep'})
            self.assertEqual('configMaps.node-agent-config' in values, config)
            self.assertEqual(values['configuration.extraEnvVars'], [{'name': 'HOME', 'value': '/scratch'}])
        self.assertEqual(original, yaml.safe_load((ROOT / 'bundle/full/uds-bundle.yaml').read_text()))

    def driver(self, directory):
        driver = object.__new__(D.Driver)
        driver.directory = Path(directory)
        driver.context = 'k3d-uds'
        driver.state = {'steps': [], 'accepted': False}
        driver.guarded = lambda: None
        return driver

    def test_failed_step_keeps_failure_journal_without_claiming_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self.driver(tmp)
            def fail():
                raise ValueError('private secret error')
            with self.assertRaises(ValueError):
                driver.step('transfer', fail)
            text = (Path(tmp) / 'journal.json').read_text()
            state = json.loads(text)
            self.assertFalse(state['accepted'])
            self.assertEqual(state['steps'][0]['status'], 'failed')
            self.assertNotIn('private secret', text)
            self.assertEqual((Path(tmp) / 'journal.json').stat().st_mode & 0o777, 0o600)

    def test_round_trip_requires_three_acceptances_and_preserves_phase_order(self):
        for fail_stage in (None, 'core-after'):
            with tempfile.TemporaryDirectory() as tmp:
                driver = self.driver(tmp)
                calls = []
                class Transfer:
                    uid = ''
                    def read(self, *_):
                        return {'metadata': {'uid': 'same-agent'}}
                    def transfer(self, source, target):
                        calls.append(('transfer', source, target))
                driver.transfer = Transfer()
                driver.read_command = lambda _: ''
                driver.deploy = lambda *args, **kwargs: calls.append(('deploy', args, kwargs))
                driver.execute = lambda *args, **kwargs: calls.append(('setup', args))
                driver.wait = lambda: calls.append(('wait',))
                driver.observe = lambda *args: calls.append(('observe', *args))
                def accept(stage, group, suffix):
                    calls.append(('accept', stage, group, suffix))
                    if stage == fail_stage:
                        raise ValueError('failed real acceptance')
                driver.accept = accept
                def reverse():
                    calls.append(('reverse',))
                    for name in ('prepare-local-config', 'detach-core-agent-retain-config', 'transfer-to-local',
                                 'deploy-local-agent', 'wait-local-agent', 'retire-core-config'):
                        driver.step(name, lambda: None)
                driver.reverse = reverse
                if fail_stage:
                    with self.assertRaises(ValueError):
                        driver.round_trip()
                    self.assertFalse(driver.state['accepted'])
                    self.assertFalse(any(c[:2] == ('accept', 'local-after') for c in calls))
                else:
                    driver.round_trip()
                    self.assertTrue(driver.state['accepted'])
                    self.assertEqual([c[1] for c in calls if c[0] == 'accept'], ['fresh-core', 'core-after', 'local-after'])
                    self.assertEqual(calls[0], ('deploy', ('core', 'core-base'), {'bootstrap': True}))
                    self.assertEqual(calls[1], ('deploy', ('core', 'core-backup-restore'), {'bootstrap': True}))
                    self.assertLess(calls.index(('observe', 'local-before', 'handoff')),
                                    calls.index(('transfer', D.T.LOCAL, D.T.CORE)))
                    self.assertEqual(driver.state['daemonsetUID'], 'same-agent')
                    spec = importlib.util.spec_from_file_location('staged_receipt', ROOT / '.github/scripts/staged-migrations.py')
                    receipt = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(receipt)
                    self.assertEqual([step['name'] for step in driver.state['steps']], receipt.OWNER_STEPS)

    def test_reversal_order_and_no_cleanup_after_failure(self):
        for fail_at in (None, 'detach-core-agent-retain-config'):
            with tempfile.TemporaryDirectory() as tmp:
                driver = self.driver(tmp)
                class Transfer:
                    uid = 'uid'
                    def read(self, *_):
                        return {'metadata': {'name': 'node-agent', 'namespace': 'velero', 'uid': 'uid', 'resourceVersion': '1', 'generation': 1,
                                             'annotations': {'meta.helm.sh/release-name': 'velero', 'meta.helm.sh/release-namespace': 'velero'},
                                             'labels': {'app.kubernetes.io/managed-by': 'Helm'}},
                                'spec': {'selector': {'matchLabels': {'name': 'node-agent'}}},
                                'status': {'desiredNumberScheduled': 1, 'numberReady': 1, 'numberAvailable': 1, 'updatedNumberScheduled': 1, 'observedGeneration': 1}}
                    def local_config(self):
                        pass
                    def transfer(self, *_):
                        pass
                driver.transfer = Transfer()
                driver.wait = lambda: None
                driver.deploy = lambda *_: None
                actual_step = driver.step
                def step(name, action):
                    if name == fail_at:
                        raise ValueError('stop here')
                    actual_step(name, action)
                driver.step = step
                if fail_at:
                    with self.assertRaises(ValueError):
                        driver.reverse()
                    self.assertEqual([s['name'] for s in driver.state['steps']], ['prepare-local-config'])
                else:
                    driver.reverse()
                    self.assertEqual([s['name'] for s in driver.state['steps']], [
                        'prepare-local-config', 'detach-core-agent-retain-config', 'transfer-to-local',
                        'deploy-local-agent', 'wait-local-agent', 'retire-core-config'])
                    self.assertFalse(driver.state['accepted'])


if __name__ == '__main__':
    unittest.main()
