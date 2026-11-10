# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Local chart packaging contracts; no registry publication or network access."""
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publish_charts', ROOT / '.github/scripts/publish-charts.py')
charts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(charts)


class ChartTests(unittest.TestCase):
    def test_invalid_or_nonstable_tag_rejected_before_git(self):
        for tag in ('main', 'v1.2.3-rc1', '1.2.3', 'v01.2.3', '--help'):
            with self.subTest(tag=tag), patch.object(charts, 'run', side_effect=AssertionError('must not execute')):
                with self.assertRaises(ValueError):
                    charts.release(ROOT, tag, 'origin/main')

    def test_registry_failures_are_not_treated_as_missing(self):
        for error in ('UNAUTHORIZED 401', 'DENIED 403', '401 request failed with body 404', 'TLS certificate failure', 'timeout'):
            with patch.object(charts, 'run', return_value=subprocess.CompletedProcess([], 1, '', error)):
                with self.assertRaises(RuntimeError):
                    charts.existing('registry/chart:1.2.3')
        with patch.object(charts, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'MANIFEST_UNKNOWN: 404')):
            self.assertIsNone(charts.existing('registry/chart:1.2.3'))

    def test_collision_compares_content_and_source_not_only_version(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'uds-cloudtak-1.2.3.tgz'
            archive.write_bytes(b'expected packaged bytes')
            manifest = {'layers': [{'mediaType': charts.MEDIA, 'digest': charts.sha(archive.read_bytes())}],
                        'annotations': {'org.opencontainers.image.source': charts.SOURCE,
                                        'org.opencontainers.image.revision': 'revision',
                                        'org.opencontainers.image.url': charts.SOURCE + '/tree/v1.2.3/charts/cloudtak',
                                        'org.opencontainers.image.licenses': 'GPL-3.0-only'}}
            self.assertEqual(charts.match_existing((manifest, 'sha256:digest'), archive, 'revision'), 'sha256:digest')
            with self.assertRaisesRegex(ValueError, 'source annotations'):
                charts.match_existing((manifest, 'sha256:digest'), archive, 'other-source')
            archive.write_bytes(b'different bytes')
            with self.assertRaisesRegex(ValueError, 'packaged bytes'):
                charts.match_existing((manifest, 'sha256:digest'), archive, 'revision')

    def test_normalization_removes_clock_metadata_without_changing_content(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for index in range(2):
                path = Path(temp) / f'{index}.tgz'
                with tarfile.open(path, 'w:gz') as archive:
                    info = tarfile.TarInfo('chart/template.yaml')
                    info.mtime = index + 10
                    info.uid = index + 1
                    info.size = 7
                    archive.addfile(info, io.BytesIO(b'content'))
                charts.normalize(path, 1234)
                paths.append(path.read_bytes())
            self.assertEqual(paths[0], paths[1])
            with tarfile.open(fileobj=io.BytesIO(paths[0]), mode='r:gz') as archive:
                self.assertEqual(archive.extractfile('chart/template.yaml').read(), b'content')
                self.assertEqual(archive.getmember('chart/template.yaml').mtime, 1234)
            executable = Path(temp) / 'executable.tgz'
            with tarfile.open(executable, 'w:gz') as archive:
                info = tarfile.TarInfo('chart/template.yaml')
                info.mode = 0o755
                info.size = 7
                archive.addfile(info, io.BytesIO(b'content'))
            charts.normalize(executable, 1234)
            self.assertNotEqual(paths[0], executable.read_bytes())

    def run_attestation_step(self, caller, overrides=None, reject_subject=None):
        workflow = yaml.safe_load((ROOT / '.github/workflows/charts.yaml').read_text())
        steps = [step for job in workflow['jobs'].values() for step in job['steps']
                 if step.get('name') == 'Verify chart attestations']
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['shell'], 'bash')
        expected = [
            ['attestation', 'verify', 'oci://ghcr.io/fixture-org/charts/uds-takserver@sha256:' + 'a' * 64,
             '--owner', 'fixture-org', '--signer-workflow',
             'fixture-org/uds-takserver/.github/workflows/charts.yaml'],
            ['attestation', 'verify', 'oci://ghcr.io/fixture-org/charts/uds-cloudtak@sha256:' + 'b' * 64,
             '--owner', 'fixture-org', '--signer-workflow',
             'fixture-org/uds-takserver/.github/workflows/charts.yaml'],
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'helm-charts').mkdir()
            (root / 'helm-charts/subjects.txt').write_text(
                'a' * 64 + ' ghcr.io/fixture-org/charts/uds-takserver\n'
                + 'b' * 64 + ' ghcr.io/fixture-org/charts/uds-cloudtak\n')
            (root / 'expected.json').write_text(json.dumps(expected))
            executable = root / 'gh'
            executable.write_text(f'#!{sys.executable}\n' + r"""
import json, os, sys
from pathlib import Path
root = Path(os.environ['RUNNER_TEMP'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as out:
    out.write(json.dumps(args) + '\n')
expected = json.loads((root / 'expected.json').read_text())
if args not in expected:
    sys.exit(41)
if args[2] == os.environ.get('REJECT_SUBJECT'):
    sys.exit(42)
""")
            executable.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       RUNNER_TEMP=temp, GITHUB_REPOSITORY='fixture-org/uds-takserver',
                       GITHUB_REPOSITORY_OWNER='fixture-org', GITHUB_WORKFLOW_REF=caller,
                       GH_TOKEN='fixture-no-network')
            env.update(overrides or {})
            env['REJECT_SUBJECT'] = reject_subject or ''
            result = subprocess.run(['bash', '-c', steps[0]['run']], env=env,
                                    capture_output=True, text=True, timeout=10)
            log = root / 'calls.jsonl'
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls, expected

    def test_attestation_signer_is_chart_workflow_for_direct_and_reusable_callers(self):
        for caller in ('fixture-org/uds-takserver/.github/workflows/charts.yaml@refs/tags/v0.1.2',
                       'fixture-org/uds-takserver/.github/workflows/release-please.yaml@refs/heads/main'):
            with self.subTest(caller=caller):
                result, calls, expected = self.run_attestation_step(caller)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, expected)

    def test_attestation_owner_and_signer_repository_are_fail_closed(self):
        for overrides in ({'GITHUB_REPOSITORY_OWNER': 'wrong-owner'},
                          {'GITHUB_REPOSITORY': 'fixture-org/wrong-repository'}):
            with self.subTest(overrides=overrides):
                result, calls, _ = self.run_attestation_step(
                    'fixture-org/uds-takserver/.github/workflows/charts.yaml@refs/heads/main', overrides)
                self.assertEqual(result.returncode, 41)
                self.assertEqual(len(calls), 1)

    def test_attestation_failure_stops_before_next_immutable_subject(self):
        result, calls, expected = self.run_attestation_step(
            'fixture-org/uds-takserver/.github/workflows/release-please.yaml@refs/heads/main',
            reject_subject='oci://ghcr.io/fixture-org/charts/uds-takserver@sha256:' + 'a' * 64)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(calls, expected[:1])

    @unittest.skipUnless(shutil.which('helm'), 'requires the repository-pinned Helm')
    def test_real_tag_packaging_preserves_render_and_app_version(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / 'repo'
            repo.mkdir()
            def git(*args):
                return charts.run(['git', *args], repo).stdout.strip()
            git('init', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (repo / 'LICENSE').write_text('release license fixture\n')
            (repo / '.release-please-manifest.json').write_text('{".":"1.2.3"}')
            for directory, name in charts.CHARTS.items():
                chart = repo / 'charts' / directory
                (chart / 'templates').mkdir(parents=True)
                (chart / 'Chart.yaml').write_text(yaml.safe_dump({'apiVersion': 'v2', 'name': name,
                    'version': '0.1.0', 'appVersion': 'upstream-version'}))
                (chart / 'templates/config.yaml').write_text('apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\ndata:\n  setting: unchanged\n')
            git('add', '.')
            git('commit', '-m', 'fixture')
            git('tag', 'v1.2.3')
            revision, stamp = charts.release(repo, 'v1.2.3', 'main')
            output = Path(temp) / 'out'
            output.mkdir()
            for name, package in charts.prepare(repo, revision, stamp, '1.2.3', output):
                metadata = yaml.safe_load(charts.run(['helm', 'show', 'chart', str(package)]).stdout)
                self.assertEqual(metadata['version'], '1.2.3')
                self.assertEqual(metadata['appVersion'], 'upstream-version')
                self.assertEqual(metadata['annotations']['org.opencontainers.image.licenses'], 'GPL-3.0-only')
                with tarfile.open(package, 'r:gz') as bundled:
                    self.assertEqual(bundled.extractfile(f'{name}/LICENSE').read(), b'release license fixture\n')
                self.assertEqual(metadata['annotations']['org.opencontainers.image.revision'], revision)
                directory = next(key for key, value in charts.CHARTS.items() if value == name)
                before = charts.run(['helm', 'template', 'existing-release', str(repo / 'charts' / directory)]).stdout
                after = charts.run(['helm', 'template', 'existing-release', str(package)]).stdout
                self.assertEqual(before, after)
            with self.assertRaises(RuntimeError):
                charts.release(repo, 'v9.9.9', 'main')
            (repo / '.release-please-manifest.json').write_text('{".":"2.0.0"}')
            git('add', '.')
            git('commit', '-m', 'mismatched fixture')
            git('tag', 'v1.2.4')
            with self.assertRaisesRegex(ValueError, 'manifest'):
                charts.release(repo, 'v1.2.4', 'main')
            git('checkout', '-b', 'side')
            git('commit', '--allow-empty', '-m', 'unmerged')
            git('tag', 'v2.0.0')
            with self.assertRaises(RuntimeError):
                charts.release(repo, 'v2.0.0', 'main')


if __name__ == '__main__':
    unittest.main()
