# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
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
    def test_two_real_failed_children_preserve_first_private_capture_and_only_publish_ids(self):
        spec = importlib.util.spec_from_file_location('first_failure_driver',
                                                      ROOT / 'tests/velero-ownership/drive.py')
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, ENV, clear=True):
            root = Path(temporary)
            (root / 'owner').mkdir()
            private = root / 'owner/PRIVATE-command-failure.txt'
            first = 'unknown flag: --fixture-secret https://private.example/?sig=fixture-secret\n'
            second = 'connection refused secondary-secret\n'
            for payload in (first, second):
                child = 'import sys;sys.stderr.write(' + repr(payload) + ');sys.exit(23)'
                with self.assertRaisesRegex(ValueError, 'staged command failed'):
                    driver.runner(['python3', '-c', child], timeout=5, diagnostics=private)
                self.assertEqual(private.read_bytes(), first.encode())
                self.assertEqual(private.stat().st_mode & 0o777, 0o600)
                self.assertLessEqual(private.stat().st_size, driver.TAIL_LIMIT)
            (root / 'owner/journal.json').write_text(json.dumps({'steps': [
                {'name': 'bootstrap-exemption', 'status': 'failed'}]}))
            output = root / 'public'
            S.publish(root, output, 'amd64')
            diagnostic = json.loads((output / 'proofs/amd64/failure-categories.json').read_text())
            self.assertEqual(diagnostic['categories'], [{'patternID': 'cli-arguments', 'count': 1}])
            published = ''.join(path.read_text() for path in output.rglob('*.json'))
            for forbidden in ('fixture-secret', 'secondary-secret', 'private.example', 'unknown flag', 'connection refused'):
                self.assertNotIn(forbidden, published)

    def test_first_failure_capture_never_follows_existing_or_parent_symlink(self):
        spec = importlib.util.spec_from_file_location('symlink_failure_driver',
                                                      ROOT / 'tests/velero-ownership/drive.py')
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'keep'; target.write_bytes(b'preserved')
            link = root / 'link'; link.symlink_to(target)
            outside = root / 'outside'; outside.mkdir()
            parent = root / 'parent'; parent.symlink_to(outside, target_is_directory=True)
            for destination in (link, parent / 'capture'):
                with self.assertRaisesRegex(ValueError, 'staged command failed'):
                    driver.runner(['python3', '-c', 'import sys;sys.stderr.write("private");sys.exit(1)'],
                                  timeout=5, diagnostics=destination)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b'preserved')
            self.assertFalse((outside / 'capture').exists())

    def test_failure_categories_publish_only_fixed_ids_and_capped_counts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, ENV, clear=True):
            root = Path(temporary)
            (root / 'owner').mkdir()
            private = root / 'owner/PRIVATE-command-failure.txt'
            private.write_text('orphan-private-key-fragment fixture-secret\nAuthorization: Bearer fixture-secret\n'
                               'https://private.example/?sig=fixture-secret\n'
                               'manifest unknown; failed to verify signature; unauthorized; '
                               'helm upgrade failed; unknown field; connection refused; '
                               'checksum mismatch; unknown flag; certificate has expired; '
                               'failed calling webhook; ' + 'context deadline exceeded; ' * 40)
            progress = {'ownerSteps': [{'name': 'bootstrap-exemption', 'status': 'failed'}]}
            diagnostic = S.failure_categories(root, progress)
            self.assertEqual(diagnostic['sourceSHA'], ENV['GITHUB_SHA'])
            self.assertEqual(diagnostic['failedStep'], 'bootstrap-exemption')
            self.assertEqual({entry['patternID'] for entry in diagnostic['categories']}, set(S.FAILURE_PATTERNS))
            self.assertEqual(next(e['count'] for e in diagnostic['categories'] if e['patternID'] == 'timeout'), 32)
            self.assertEqual(diagnostic['status'], 'classified')
            (root / 'owner/journal.json').write_text(json.dumps({'steps': progress['ownerSteps'],
                                                               'private': 'fixture-secret'}))
            public = root / 'public'
            S.publish(root, public, 'amd64')
            published = json.loads((public / 'proofs/amd64/failure-categories.json').read_text())
            self.assertEqual(published['failedStep'], 'bootstrap-exemption')
            self.assertEqual(published['categories'], diagnostic['categories'])
            output = ''.join(path.read_text() for path in public.rglob('*.json'))
            for forbidden in ('fixture-secret', 'private.example', 'Authorization', 'orphan-private-key-fragment',
                              'manifest unknown', 'context deadline exceeded'):
                self.assertNotIn(forbidden, output)
            self.assertNotIn('PRIVATE-command-failure.txt', [path.name for path in public.rglob('*')])
            self.assertEqual(private.read_text().count('fixture-secret'), 3)

    def test_specific_failure_signatures_never_publish_their_captured_text(self):
        fixtures = {'authentication': ['Forbidden fixture-secret', 'HTTP/1.1 403 fixture-secret',
                                       'status code: 403 fixture-secret'],
                    'cli-arguments': ['unknown flag: --fixture-secret', 'unknown command fixture-secret'],
                    'tls-certificate': ['x509: fixture-secret', 'unknown CA fixture-secret',
                                        'certificate has expired fixture-secret'],
                    'package-integrity': ['invalid tar fixture-secret', 'unexpected EOF fixture-secret',
                                          'checksum mismatch fixture-secret']}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, ENV, clear=True):
            root = Path(temporary)
            (root / 'owner').mkdir()
            for expected, samples in fixtures.items():
                for text in samples:
                    with self.subTest(expected=expected, text=text):
                        (root / 'owner/PRIVATE-command-failure.txt').write_text(text)
                        result = S.failure_categories(root, {'ownerSteps': []})
                        self.assertEqual(result['categories'], [{'patternID': expected, 'count': 1}])
                        self.assertNotIn('fixture-secret', json.dumps(result))

    def test_missing_unclassified_invalid_oversized_and_symlink_tails_never_publish_text(self):
        for case in ('missing', 'unclassified', 'invalid-utf8', 'nul', 'oversized', 'symlink', 'directory'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary, \
                    patch.dict(os.environ, ENV, clear=True):
                root = Path(temporary)
                (root / 'owner').mkdir()
                path = root / 'owner/PRIVATE-command-failure.txt'
                if case == 'symlink':
                    target = root / 'foreign'; target.write_bytes(b'fixture-secret unauthorized')
                    path.symlink_to(target)
                elif case == 'directory':
                    path.mkdir()
                elif case != 'missing':
                    path.write_bytes({'unclassified': b'fixture-secret unknown-error',
                                      'invalid-utf8': b'fixture-secret\xff', 'nul': b'fixture-secret\x00',
                                      'oversized': b'fixture-secret' + b'x' * 65536}[case])
                result = S.failure_categories(root, {'ownerSteps': []})
                self.assertEqual(result['categories'], [])
                self.assertEqual(result['failedStep'], 'unavailable')
                self.assertEqual(result['status'], 'unclassified' if case == 'unclassified' else
                                 'unavailable-oversized-or-nonregular' if case == 'oversized' else
                                 'unavailable-oversized-or-invalid-text' if case == 'nul' else 'unavailable')
                self.assertNotIn('fixture-secret', json.dumps(result))

    def pinned_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'repo'
        subprocess.run(['git', 'clone', '--shared', '--quiet', str(S.ROOT), str(root)], check=True,
                       capture_output=True, timeout=20)
        subprocess.run(['bash', '.github/scripts/pin-image-tags.sh'], cwd=root, check=True,
                       capture_output=True, timeout=20, env={k: v for k, v in os.environ.items()
                                                           if k != 'GITHUB_STEP_SUMMARY'})
        candidate = Path(temporary.name) / 'candidate'
        candidate.mkdir()
        files = {}
        for name in ('core', 'detach', 'clean', 'config'):
            path = candidate / (name + ('.yaml' if name == 'config' else '.tar.zst'))
            path.write_bytes((root / 'bundle/full/uds-config.yaml').read_bytes() if name == 'config'
                             else ('bound archive ' + name).encode())
            files[name] = {'path': path.name, 'sha256': S.sha(path)}
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
        (candidate / 'plan.json').write_text(json.dumps({'schema': 1, 'sourceSHA': head, 'files': files}))
        return root, candidate, {**ENV, 'GITHUB_SHA': head}

    def test_real_pinning_restores_only_reviewed_tasks_after_binding(self):
        root, candidate, env = self.pinned_fixture()
        changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=root).decode().splitlines()
        self.assertEqual(len(changed), 7)
        before = {name: (root / name).read_bytes() for name in changed if name != 'tasks.yaml'}
        bound = {path.name: path.read_bytes() for path in candidate.iterdir()}
        spec = importlib.util.spec_from_file_location('actual_staged_driver', root / 'tests/velero-ownership/drive.py')
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        command = lambda args: subprocess.check_output(args, cwd=root).decode()
        with self.assertRaisesRegex(ValueError, 'differs from reviewed'):
            driver.verify_helpers(command)
        original_read = Path.read_bytes
        def no_archive_read(path):
            if path.suffix == '.zst':
                raise AssertionError('bundle archives must be hashed incrementally')
            return original_read(path)
        with patch.object(S, 'ROOT', root), patch.dict(os.environ, env, clear=True), \
                patch.object(Path, 'read_bytes', no_archive_read):
            driver.load_plan(candidate / 'plan.json')
            S.restore_task_default(candidate)
            driver.verify_helpers(command)
            S.restore_task_default(candidate)  # Explicit canonical no-op.
        self.assertEqual(before, {name: (root / name).read_bytes() for name in before})
        self.assertEqual(bound, {path.name: path.read_bytes() for path in candidate.iterdir()})
        self.assertEqual(subprocess.check_output(['git', 'diff', '--name-only'], cwd=root).decode().splitlines(),
                         [name for name in changed if name != 'tasks.yaml'])

    def test_restoration_refuses_unrelated_missing_duplicate_and_symlink_without_writing(self):
        for failure in ('unrelated', 'missing', 'duplicate', 'symlink', 'helper', 'version', 'pin-helper',
                        'plan', 'archive', 'config', 'oversized-config', 'oversized-plan'):
            with self.subTest(failure=failure):
                root, candidate, env = self.pinned_fixture()
                task = root / 'tasks.yaml'
                if failure == 'unrelated':
                    task.write_bytes(task.read_bytes() + b'\n# unrelated edit\n')
                elif failure == 'missing':
                    task.unlink()
                elif failure == 'duplicate':
                    task.write_bytes(task.read_bytes() + b'  - name: TAK_IMAGE_TAG\n    default: unexpected\n')
                elif failure == 'symlink':
                    real = root / 'tasks-copy'; task.rename(real); task.symlink_to(real)
                elif failure in ('helper', 'version', 'pin-helper'):
                    name = {'helper': '.github/container-and-chart/docker/build.sh',
                            'version': '.github/container-and-chart/docker/version.txt',
                            'pin-helper': '.github/scripts/pin-image-tags.sh'}[failure]
                    path = root / name; path.write_bytes(path.read_bytes() + b'\n# unreviewed\n')
                elif failure == 'plan':
                    plan = json.loads((candidate / 'plan.json').read_text()); plan['sourceSHA'] = '0' * 40
                    (candidate / 'plan.json').write_text(json.dumps(plan))
                elif failure == 'archive':
                    (candidate / 'core.tar.zst').write_bytes(b'changed archive')
                else:
                    plan = json.loads((candidate / 'plan.json').read_text())
                    if failure == 'oversized-plan':
                        (candidate / 'plan.json').write_bytes(b' ' * 65537)
                    else:
                        path = candidate / 'config.yaml'
                        if failure == 'oversized-config':
                            path.write_bytes(b' ' * 65537)
                        else:
                            config = yaml.safe_load(path.read_text())
                            config['variables']['takserver']['UNREVIEWED_OPTION'] = 'same trusted tag remains'
                            path.write_text(yaml.safe_dump(config))
                        plan['files']['config']['sha256'] = S.sha(path)
                        (candidate / 'plan.json').write_text(json.dumps(plan))
                before = task.read_bytes() if task.exists() else None
                with patch.object(S, 'ROOT', root), patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                    S.restore_task_default(candidate)
                self.assertEqual(task.read_bytes() if task.exists() else None, before)
                if failure == 'symlink':
                    self.assertTrue(task.is_symlink())

    def test_restore_call_is_only_after_successful_candidate_binding(self):
        script = (S.ROOT / '.github/scripts/staged-migrations.sh').read_text()
        bind = script.index('candidate.py bind --directory')
        restore = script.index('staged-migrations.py restore-task-default --directory')
        driver = script.index('drive.py local-baseline')
        self.assertLess(bind, restore)
        self.assertLess(restore, driver)
        self.assertIn('set -euo pipefail', script)

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
            (directory / 'owner/PRIVATE-command-failure.txt').write_bytes(b'orphan-fixture-secret\xff')
            with patch.object(S, 'failure_categories', side_effect=AssertionError('inactive diagnostic dependency')):
                self.assertTrue(S.publish(directory, public, 'amd64')['accepted'])
            self.assertFalse((public / 'proofs/amd64/failure-categories.json').exists())
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
