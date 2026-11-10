# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Receipt identity/omission contracts; no cluster or external API required."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/install-receipt.py'
SPEC = importlib.util.spec_from_file_location('install_receipt', SCRIPT)
RECEIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECEIPT)


class InstallReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        workflow = self.root / RECEIPT.WORKFLOW
        workflow.parent.mkdir(parents=True)
        workflow.write_text('name: fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.inputs = {'package_key': 'amd64-' + 'a' * 16,
                       'package_archive_sha256': 'sha256:' + '1' * 64,
                       'checkpoint_oci_digest': 'sha256:' + '2' * 64,
                       'core_oci_digest': 'sha256:' + '3' * 64,
                       'image_digests': {name: 'sha256:' + '4' * 64 for name in RECEIPT.IMAGES},
                       'uds_version': '0.41.0'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def build(self, **overrides):
        values = {'root': self.root, 'repository': 'fixture/repository', 'event': 'pull_request',
                  'run_id': 123, 'attempt': 2, 'arch': 'amd64', 'scenario': 'install',
                  'result': 'success', 'inputs': self.inputs}
        values.update(overrides)
        return RECEIPT.receipt(**values)

    def test_records_actual_synthetic_checkout_instead_of_reported_head(self):
        base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-qb', 'feature')
        (self.root / 'feature').write_text('feature\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'feature')
        head = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-q', 'main')
        (self.root / 'base').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base advanced')
        self.git('merge', '-q', '--no-ff', 'feature', '-m', 'synthetic merge')
        previous = os.environ.get('GITHUB_SHA')
        os.environ['GITHUB_SHA'] = head
        try:
            value = self.build()
        finally:
            if previous is None:
                os.environ.pop('GITHUB_SHA', None)
            else:
                os.environ['GITHUB_SHA'] = previous
        self.assertEqual(value['source']['checkout_commit'], self.git('rev-parse', 'HEAD'))
        self.assertNotIn(value['source']['checkout_commit'], (base, head))
        self.assertEqual(value['source']['checkout_tree'], self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual(value['run'], {'id': 123, 'attempt': 2, 'event': 'pull_request',
                                       'job': 'validate-install'})
        self.assertFalse(value['reuse_authorized'])

    def test_squash_tree_equality_does_not_authorize_reuse(self):
        value = self.build()
        self.git('commit', '--allow-empty', '-qm', 'different commit same tree')
        later = self.build(event='push')
        self.assertEqual(value['source']['checkout_tree'], later['source']['checkout_tree'])
        self.assertNotEqual(value['source']['checkout_commit'], later['source']['checkout_commit'])
        self.assertFalse(later['reuse_authorized'])

    def test_rejects_missing_execution_other_modes_and_unknown_scenarios(self):
        for result in ('failure', 'skipped', 'cancelled', ''):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.build(result=result)
        for values in ({'scenario': 'upgrade'}, {'scenario': 'install-airgap', 'arch': 'arm64'},
                       {'mode': 'trust'}, {'mode': 'diagnostic'}, {'attempt': 0}, {'run_id': True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.build(**values)
        self.assertEqual(self.build(scenario='install-airgap')['execution']['step'],
                         'Install and test without node internet egress')

    def test_rejects_unknown_or_incomplete_input_and_image_fields(self):
        for mutation in ('extra', 'missing', 'image-missing', 'image-extra', 'wrong-arch'):
            inputs = json.loads(json.dumps(self.inputs))
            if mutation == 'extra':
                inputs['Authorization'] = 'opaque-secret'
            elif mutation == 'missing':
                del inputs['checkpoint_oci_digest']
            elif mutation == 'image-missing':
                del inputs['image_digests']['postgis']
            elif mutation == 'image-extra':
                inputs['image_digests']['opaque-secret'] = 'sha256:' + '5' * 64
            else:
                inputs['package_key'] = 'arm64-' + 'a' * 16
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.build(inputs=inputs)

    def test_cli_omits_rejected_payload_and_refuses_output_replacement(self):
        manifest = self.root / 'inputs.json'
        output = self.root / 'receipt.json'
        args = ['python3', str(SCRIPT), '--checkout', str(self.root),
                '--repository', 'fixture/repository', '--event', 'pull_request',
                '--run-id', '123', '--attempt', '1', '--architecture', 'amd64',
                '--scenario', 'install', '--execution-result', 'success',
                '--inputs', str(manifest), '--output', str(output)]
        inputs = dict(self.inputs, password='opaque-sensitive-value')
        manifest.write_text(json.dumps(inputs))
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('opaque-sensitive-value', result.stdout + result.stderr)
        self.assertFalse(output.exists())
        manifest.write_text('{"secret": "opaque-sensitive-value"')
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('opaque-sensitive-value', result.stdout + result.stderr)
        invalid_args = list(args)
        invalid_args[invalid_args.index('--run-id') + 1] = 'opaque-sensitive-value'
        result = subprocess.run(invalid_args, capture_output=True, text=True)
        self.assertNotIn('opaque-sensitive-value', result.stdout + result.stderr)
        manifest.write_text(json.dumps(self.inputs))
        subprocess.run(args, check=True, capture_output=True)
        content = output.read_bytes()
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), content)
        self.assertNotIn('opaque-sensitive-value', content.decode())


if __name__ == '__main__':
    unittest.main()
