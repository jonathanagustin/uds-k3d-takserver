# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Acquisition proof must survive cache reuse without querying a mutable tag."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('checkpoint_identity',
                                            ROOT / '.github/scripts/checkpoint-identity.py')
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)
SOURCE = sorted(identity.REPOSITORIES)[0]


def encoded(value):
    return json.dumps(value, separators=(',', ':')).encode()


class CheckpointIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'zarf-package-k3d-core-slim-dev-amd64-1.16.0.tar.zst'
        self.archive.write_bytes(b'actual acquired archive bytes')
        self.manifest = encoded({'schemaVersion': 2, 'mediaType': identity.MANIFEST,
                                 'config': self.descriptor('application/vnd.zarf.config.v1+json'),
                                 'layers': [self.descriptor('application/vnd.zarf.layer.v1.blob')]})
        self.index = encoded({'schemaVersion': 2, 'mediaType': identity.INDEX, 'manifests': [
            {'mediaType': identity.MANIFEST, 'digest': identity.sha(self.manifest),
             'size': len(self.manifest), 'platform': {'architecture': 'amd64', 'os': 'multi'}}]})
        self.digest = identity.sha(self.index)

    @staticmethod
    def descriptor(media):
        return {'mediaType': media, 'digest': 'sha256:' + 'a' * 64, 'size': 1}

    def acquire(self):
        with patch.object(identity, 'fetch', side_effect=[self.index, self.manifest]) as fetch:
            value = identity.acquire(self.archive, SOURCE, '1.16.0', 'amd64', self.digest, ['zarf'])
        self.assertEqual([call.args[1] for call in fetch.call_args_list],
                         [f'{SOURCE}@{self.digest}', f'{SOURCE}@{identity.sha(self.manifest)}'])
        return value

    def test_fresh_acquisition_and_same_cached_bytes(self):
        value = self.acquire()
        self.assertEqual(value['archive_sha256'], identity.sha(self.archive.read_bytes()))
        with patch.object(identity, 'fetch', side_effect=AssertionError('cache must not query registry')):
            self.assertEqual(identity.validate(value, self.archive, SOURCE, '1.16.0', 'amd64'), value)

    def test_old_cache_omits_without_registry_or_repull(self):
        result = subprocess.run(['python3', str(SPEC.origin), '--archive', str(self.archive),
                                 '--source', SOURCE, '--version', '1.16.0', '--architecture', 'amd64'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('omitted', result.stdout)
        self.assertEqual(self.archive.read_bytes(), b'actual acquired archive bytes')
        self.assertNotIn('Traceback', result.stderr)

    def test_mismatched_archive_or_sidecar_omits(self):
        value = self.acquire()
        self.archive.write_bytes(b'replacement archive')
        with self.assertRaises(ValueError):
            identity.validate(value, self.archive, SOURCE, '1.16.0', 'amd64')
        for field, replacement in [('source', 'registry.invalid/private'), ('version', '1.15.2'),
                                   ('architecture', 'arm64'), ('index_digest', 'secret')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                identity.validate({**value, field: replacement}, self.archive, SOURCE, '1.16.0', 'amd64')

    def test_validated_cache_emits_exact_run_bound_selected_archive(self):
        value = self.acquire()
        Path(str(self.archive) + '.receipt.json').write_text(json.dumps(value))
        selected = Path(self.temp.name) / 'selected.json'
        github_env = Path(self.temp.name) / 'github-env'
        result = subprocess.run(['python3', str(SPEC.origin), '--archive', str(self.archive),
                                 '--source', SOURCE, '--version', '1.16.0', '--architecture', 'amd64',
                                 '--digest', self.digest, '--selection-output', str(selected)],
                                env={**os.environ, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                                     'GITHUB_ENV': str(github_env)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(selected.read_text()), {
            'archive': str(self.archive.resolve()), 'acquisition': value, 'run_id': 123, 'attempt': 2})
        self.assertEqual(github_env.read_text(), 'INSTALL_RECEIPT_CHECKPOINT_VALIDATED=true\n')

    def test_descriptor_and_exact_bytes_are_required(self):
        for index, manifest, digest in [(self.index + b' ', self.manifest, self.digest),
                                       (self.index, self.manifest + b' ', self.digest)]:
            with self.assertRaises(ValueError):
                identity.resolve(index, manifest, digest, 'amd64')
        for mutate in ('duplicate', 'linux', 'wrong-size', 'wrong-arch', 'non-object'):
            index = json.loads(self.index)
            item = index['manifests'][0]
            if mutate == 'duplicate':
                index['manifests'].append(item)
            elif mutate == 'linux':
                item['platform']['os'] = 'linux'
            elif mutate == 'wrong-size':
                item['size'] += 1
            elif mutate == 'wrong-arch':
                item['platform']['architecture'] = 'arm64'
            else:
                index['manifests'].append('untrusted')
            data = encoded(index)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                identity.resolve(data, self.manifest, identity.sha(data), 'amd64')

    def test_wrong_package_schema_rejected(self):
        manifest = json.loads(self.manifest)
        manifest['config']['mediaType'] = 'application/vnd.oci.image.config.v1+json'
        data = encoded(manifest)
        index = json.loads(self.index)
        index['manifests'][0].update(digest=identity.sha(data), size=len(data))
        index = encoded(index)
        with self.assertRaises(ValueError):
            identity.resolve(index, data, identity.sha(index), 'amd64')

    def test_shell_cached_archive_never_pulls_or_queries_registry(self):
        root = Path(self.temp.name) / 'checkout'
        scripts = root / '.github/scripts'
        scripts.mkdir(parents=True)
        for name in ('deploy-slim-core.sh', 'checkpoint-identity.py'):
            (scripts / name).write_bytes((ROOT / '.github/scripts' / name).read_bytes())
        zarf = root / 'zarf'
        calls = root / 'calls.jsonl'
        zarf.write_text('#!' + sys.executable + '\n'
                        'import json,os,sys\n'
                        'with open(os.environ["CHECKPOINT_CALLS"],"a") as f: '
                        'f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                        'sys.exit(0 if sys.argv[1:3]==["package","deploy"] else 91)\n')
        zarf.chmod(0o755)
        before = self.archive.read_bytes()
        observed = []
        runner = root / 'runner'
        runner.mkdir()
        for metadata in ('false', 'true'):
            env = {**os.environ, 'SLIM_PACKAGE_DIR': self.temp.name,
                   'INSTALL_RECEIPT_METADATA': metadata, 'SLIM_K3D_EXTRA_ARGS': '',
                   'RUNNER_TEMP': str(runner), 'GITHUB_ENV': str(runner / 'env'),
                   'CHECKPOINT_CALLS': str(calls)}
            result = subprocess.run(['bash', str(scripts / 'deploy-slim-core.sh')], env=env,
                                    capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if metadata == 'true':
                self.assertIn('identity omitted', result.stdout)
            self.assertIn('Deploying', result.stdout)
            observed.append([json.loads(line) for line in calls.read_text().splitlines()])
            calls.unlink()
            self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(len(observed[0]), 1)
        self.assertEqual(observed[0][0][:2], ['package', 'deploy'])

    def test_shell_fresh_pull_uses_verified_digest_and_failed_pull_is_not_success(self):
        root = Path(self.temp.name) / 'fresh-checkout'
        scripts = root / '.github/scripts'
        scripts.mkdir(parents=True)
        (scripts / 'deploy-slim-core.sh').write_bytes((ROOT / '.github/scripts/deploy-slim-core.sh').read_bytes())
        zarf = root / 'zarf'
        digest = 'sha256:d47b4ef370fd0e1ca2d5976fb1bedc7132178784e9b7453b28ff228509bb1d51'
        zarf.write_text('#!/bin/sh\n'
                        'case "$1 $2 $3" in\n'
                        f'"tools registry digest") echo {digest} ;;\n'
                        f'"package pull oci://{SOURCE}@{digest}") touch "{root}/matched-immutable-pull"; exit 77 ;;\n'
                        '*) exit 91 ;;\nesac\n')
        zarf.chmod(0o755)
        env = {**os.environ, 'SLIM_PACKAGE_DIR': str(root / 'cache'), 'SLIM_CORE_MIRROR': '',
               'INSTALL_RECEIPT_METADATA': 'true', 'SLIM_K3D_EXTRA_ARGS': ''}
        result = subprocess.run(['bash', str(scripts / 'deploy-slim-core.sh')], env=env,
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((root / 'matched-immutable-pull').exists())
        self.assertNotIn('Deploying', result.stdout)
        self.assertNotIn('identity recorded', result.stdout)

    def test_failure_output_cannot_echo_registry_credentials(self):
        result = subprocess.run(['python3', str(SPEC.origin), '--secret-token=DO_NOT_PRINT'],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('DO_NOT_PRINT', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
