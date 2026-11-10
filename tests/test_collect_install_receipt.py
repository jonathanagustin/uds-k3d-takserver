# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Actual checkout/OCI fixtures exercise the optional producer as a whole."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests import test_install_artifact_inputs as artifact_fixtures

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('collector',
                                            ROOT / '.github/scripts/collect-install-receipt.py')
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()
        self.directory = Path(self.temp.name) / 'runner'
        self.directory.mkdir()
        workflow = self.root / '.github/workflows/test.yaml'
        workflow.parent.mkdir(parents=True)
        workflow.write_bytes((ROOT / '.github/workflows/test.yaml').read_bytes())
        for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c',
                     'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']):
            subprocess.run(['git', '-C', str(self.root), *args], check=True,
                           capture_output=True, timeout=5)
        event = self.directory / 'event.json'
        event.write_text('{}')
        self.env = {'GITHUB_REPOSITORY': collector.REPOSITORY, 'GITHUB_EVENT_NAME': 'push',
                    'GITHUB_EVENT_PATH': str(event), 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                    'GITHUB_SHA': '0' * 40,
                    'TEST_TYPE': 'install', 'TEST_FLAVOR': 'upstream', 'AIRGAP_TEST': 'false',
                    'RECEIPT_DIAGNOSTIC': 'none', 'GITHUB_ENV': str(self.directory / 'env'),
                    'GITHUB_OUTPUT': str(self.directory / 'output'), 'INSTALL_OUTCOME': 'success',
                    'AIRGAP_OUTCOME': 'skipped', 'AIRGAP_RESTORE_OUTCOME': 'skipped',
                    'SANITIZE_OK': 'true', 'INSTALL_RECEIPT_CHECKPOINT_VALIDATED': 'true'}
        self.arch = patch.object(collector.platform, 'machine', return_value='x86_64')
        self.arch.start()
        self.addCleanup(self.arch.stop)

    def inputs(self):
        fixture = artifact_fixtures.ArtifactInputsTests()
        fixture.setUp()
        fixture.archive(self.root, list(fixture.objects.items())).rename(
            self.root / 'uds-bundle-takserver-dev-amd64-dev.tar.zst')
        checkpoint = self.root / '.cache/k3d-core-slim-dev/zarf-package-k3d-core-slim-dev-amd64-1.16.0.tar.zst'
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b'checkpoint acquisition bytes')
        acquisition = {
            'schema_version': 1, 'source': sorted(collector.checkpoint.REPOSITORIES)[0],
            'version': '1.16.0', 'architecture': 'amd64',
            'archive_sha256': collector.checkpoint.archive_hash(checkpoint),
            'index_digest': 'sha256:' + 'a' * 64, 'manifest_digest': 'sha256:' + 'b' * 64}
        Path(str(checkpoint) + '.receipt.json').write_text(json.dumps(acquisition))
        (self.directory / 'install-checkpoint-selection.json').write_text(json.dumps({
            'archive': str(checkpoint), 'acquisition': acquisition, 'run_id': 123, 'attempt': 2}))
        self.fixture = fixture
        for suffix in ('-upstream', ''):
            (self.root / f'zarf-package-takserver-amd64-dev{suffix}.tar.zst').write_bytes(b'package bytes')
        return fixture

    def collect(self):
        pinned = self.directory / 'install-pinned.json'
        if not pinned.exists():
            with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0']):
                collector.pinned(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0',
                                                           self.fixture.expected_app]) as command:
            result = collector.collect(self.root, self.env, self.directory)
        digest_call = command.call_args_list[-1]
        self.assertEqual(digest_call.args[1][:5], ['uds', 'zarf', 'package', 'inspect', 'digest'])
        self.assertEqual(digest_call.args[1][5], str(self.root / 'zarf-package-takserver-amd64-dev-upstream.tar.zst'))
        return result

    def test_ordinary_producer_uses_early_checkout_and_real_archive_metadata(self):
        fixture = self.inputs()
        saved = collector.capture(self.root, self.env, self.directory)
        # The later pin operation changes working files, not the recorded tree.
        (self.root / 'zarf.yaml').write_text('pinned image inputs')
        result = self.collect()
        self.assertEqual(result['source']['checkout_commit'], saved['checkout']['source']['checkout_commit'])
        self.assertEqual(result['inputs']['image_digests'], fixture.expected_images)
        self.assertEqual(result['inputs']['core_oci_digest'], fixture.expected_core)
        self.assertEqual(result['inputs']['package_archive_sha256'], collector.checkpoint.sha(b'package bytes'))
        self.assertFalse(result['reuse_authorized'])
        self.assertNotEqual(result['source']['checkout_commit'], self.env['GITHUB_SHA'])
        self.assertIn('INSTALL_RECEIPT_METADATA=true', Path(self.env['GITHUB_ENV']).read_text())
        self.assertIn('ready=true', Path(self.env['GITHUB_OUTPUT']).read_text())

    def test_airgap_requires_correct_execution_and_restore_success(self):
        env = {**self.env, 'AIRGAP_TEST': 'true', 'INSTALL_OUTCOME': 'skipped',
               'AIRGAP_OUTCOME': 'success', 'AIRGAP_RESTORE_OUTCOME': 'success'}
        self.inputs()
        self.env = env
        collector.capture(self.root, self.env, self.directory)
        self.assertEqual(self.collect()['scenario']['name'], 'install-airgap')
        for outcome in ('skipped', 'cancelled', 'failure'):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                collector.execution({**env, 'AIRGAP_RESTORE_OUTCOME': outcome}, 'install-airgap')

    def test_failure_skipped_cancelled_and_unsanitized_are_not_receipts(self):
        for key in ('INSTALL_OUTCOME', 'SANITIZE_OK'):
            for outcome in ('skipped', 'cancelled', 'failure', ''):
                with self.subTest(key=key, outcome=outcome), self.assertRaises(ValueError):
                    collector.execution({**self.env, key: outcome}, 'install')
        with self.assertRaises(ValueError):
            collector.execution({**self.env, 'AIRGAP_OUTCOME': 'success'}, 'install')

    def test_forks_trust_diagnostics_and_wrong_scenario_omit_at_capture(self):
        cases = [({'GITHUB_EVENT_NAME': 'pull_request'},
                  {'pull_request': {'head': {'repo': {'full_name': 'fork/project'}}}}),
                 ({'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'inputs': {'trust_bundle': 'true'}}),
                 ({'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'inputs': {'diagnostic_case': 'pg15-both'}}),
                 ({'RECEIPT_DIAGNOSTIC': 'upgrade-amd64'}, {}),
                 ({'TEST_TYPE': 'upgrade'}, {}), ({'TEST_FLAVOR': 'registry1'}, {})]
        for updates, event in cases:
            Path(self.env['GITHUB_EVENT_PATH']).write_text(json.dumps(event))
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                collector.capture(self.root, {**self.env, **updates}, self.directory)
        self.assertFalse((self.directory / 'install-source.json').exists())

    def test_checkout_change_missing_proof_and_different_plain_archive_omit(self):
        self.inputs()
        collector.capture(self.root, self.env, self.directory)
        plain = self.root / 'zarf-package-takserver-amd64-dev.tar.zst'
        plain.write_bytes(b'different bundled archive')
        with self.assertRaises(ValueError):
            self.collect()
        plain.write_bytes(b'package bytes')
        (self.directory / 'install-checkpoint-selection.json').unlink()
        with self.assertRaises(OSError):
            self.collect()
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'new checkout'],
                       check=True, capture_output=True, timeout=5)
        with self.assertRaises(ValueError):
            self.collect()
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_rejected_current_validation_cannot_use_stale_marker(self):
        self.inputs()
        collector.capture(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0']):
            collector.pinned(self.root, self.env, self.directory)
        self.env['INSTALL_RECEIPT_CHECKPOINT_VALIDATED'] = 'false'
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0']):
            with self.assertRaises(ValueError):
                collector.collect(self.root, self.env, self.directory)
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_unrelated_package_digest_never_authenticates_bundle_inputs(self):
        self.inputs()
        collector.capture(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0']):
            collector.pinned(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0',
                                                           'sha256:' + 'f' * 64]):
            with self.assertRaises(ValueError):
                collector.collect(self.root, self.env, self.directory)
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_failed_current_cache_validation_removes_stale_selection_and_omits(self):
        self.inputs()
        collector.capture(self.root, self.env, self.directory)
        scripts = self.root / '.github/scripts'
        scripts.mkdir(parents=True, exist_ok=True)
        for name in ('deploy-slim-core.sh', 'checkpoint-identity.py'):
            (scripts / name).write_bytes((ROOT / '.github/scripts' / name).read_bytes())
        zarf = self.root / 'zarf'
        zarf.write_text('#!/bin/sh\n[ "$1 $2" = "package deploy" ] || exit 91\nexit 0\n')
        zarf.chmod(0o755)
        import os
        env = {**os.environ, **self.env, 'INSTALL_RECEIPT_METADATA': 'true',
               'RUNNER_TEMP': str(self.directory), 'SLIM_K3D_EXTRA_ARGS': ''}
        result = subprocess.run(['bash', str(scripts / 'deploy-slim-core.sh')], env=env,
                                capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('identity omitted', result.stdout)
        self.assertTrue(Path(self.env['GITHUB_ENV']).read_text().rstrip().endswith(
            'INSTALL_RECEIPT_CHECKPOINT_VALIDATED=false'))
        # The bytes/sidecar remain valid locally, but current pinned digest validation failed.
        self.assertTrue(next((self.root / '.cache/k3d-core-slim-dev').glob('*.receipt.json')).exists())
        self.assertFalse((self.directory / 'install-checkpoint-selection.json').exists())
        with self.assertRaises(OSError):
            self.collect()
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_pinned_input_change_omits_before_archive_collection(self):
        collector.capture(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'c' * 16, 'v0.41.0']):
            collector.pinned(self.root, self.env, self.directory)
        with patch.object(collector, 'command', side_effect=['amd64-' + 'd' * 16, 'v0.41.0']):
            with self.assertRaises(ValueError):
                collector.collect(self.root, self.env, self.directory)
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_latest_run_identity_must_match_snapshot(self):
        collector.capture(self.root, self.env, self.directory)
        for field in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                collector.collect(self.root, {**self.env, field: '999'}, self.directory)
        self.assertFalse(Path(self.env['GITHUB_OUTPUT']).exists())

    def test_workflow_captures_before_pin_and_only_uploads_authenticated_success(self):
        source = (ROOT / '.github/workflows/test.yaml').read_text()
        self.assertLess(source.index('name: Capture install receipt source'),
                        source.index("name: Use this commit's TAK"))
        for step in ('Collect optional install receipt', 'Authenticate optional install receipt',
                     'Upload authenticated install receipt'):
            block = source.split('name: ' + step, 1)[1].split('\n      - ', 1)[0]
            self.assertIn('continue-on-error: true', block)
            self.assertIn('success()', block)
            self.assertIn("env.TEST_TYPE == 'install'", block)
            self.assertIn('github.event.pull_request.head.repo.full_name == github.repository', block)
        upload = source.split('name: Upload authenticated install receipt', 1)[1].split('\n      - ', 1)[0]
        self.assertIn("steps.attest-install-receipt.outcome == 'success'", upload)
        self.assertIn("steps.install-receipt.outputs.ready == 'true'", upload)


if __name__ == '__main__':
    unittest.main()
