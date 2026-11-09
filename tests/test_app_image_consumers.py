# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Consumers wait for keyed producer outputs and Demo keys identify app HEAD."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SELECT = ROOT / '.github/scripts/select-demo-app-ref.sh'
HELPERS = ('.github/scripts/wait-for-tak-images.sh', '.github/scripts/pin-image-tags.sh',
           '.github/container-and-chart/docker/build.sh', '.github/container-and-chart/cloudtak/build.sh', '.github/container-and-chart/postgis/build.sh')
PRESERVED = ('demo/record.sh', 'tests/demo/test.ts', 'tests/playwright.demo.config.ts',
             'tasks.yaml', '.gitignore', '.github/workflows/demo.yaml',
             '.github/scripts/published_package_ref.py')


class ConsumerWorkflowTests(unittest.TestCase):
    def test_both_consumers_wait_and_pin_before_create_or_stamp(self):
        for workflow, job, boundary in (('atak-e2e', 'e2e', 'Deploy UDS Core slim and TAK Server'),
                                         ('demo', 'record', 'Stamp the release version')):
            jobs = yaml.safe_load((ROOT / f'.github/workflows/{workflow}.yaml').read_text())['jobs']
            selected = jobs[job]
            steps = selected['steps']
            names = [step.get('name') for step in steps]
            order = [names.index(name) for name in ('Wait for the six TAK images',
                     'Wait for the CloudTAK image', 'Wait for the PostGIS image',
                     "Use the selected source's keyed application images", boundary)]
            self.assertEqual(order, sorted(order))
            if workflow == 'demo':
                source = next(step for step in steps if step.get('id') == 'app-source')
                self.assertNotIn('if', source)
                self.assertEqual(source['env']['EXPECTED_SHA'],
                                 '${{ github.event.pull_request.head.sha || github.sha }}')
                self.assertLess(steps.index(source), order[0])
            tak = steps[order[0]]
            self.assertEqual(tak['env']['BUILD_IF_MISSING'], 'false')
            expected = ('${{ github.event.pull_request.head.sha || github.sha }}' if workflow == 'atak-e2e'
                        else '${{ steps.app-source.outputs.expected-sha }}')
            self.assertEqual(tak['env']['EXPECTED_SHA'], expected)
            self.assertEqual([steps[i]['run'] for i in order[:4]], [
                './.github/scripts/wait-for-tak-images.sh',
                './.github/container-and-chart/cloudtak/build.sh --wait',
                './.github/container-and-chart/postgis/build.sh --wait',
                './.github/scripts/pin-image-tags.sh'])


class DemoSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        for name in (*PRESERVED, *HELPERS, '.github/container-and-chart/docker/Dockerfile'):
            if name == '.github/scripts/published_package_ref.py':
                continue  # Added with the recorder commit, absent from the app ref.
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('app\n')
            if name in HELPERS:
                path.chmod(0o755)
                if name.endswith(('cloudtak/build.sh', 'postgis/build.sh')):
                    path.write_text('if [[ "${1:-}" = "--wait" ]]; then exit 0; fi\n')
                elif name.endswith('wait-for-tak-images.sh'):
                    path.write_text('build_if_missing="${BUILD_IF_MISSING:-true}"\n'
                                    '# EXPECTED_SHA\n'
                                    'if [[ "${build_if_missing}" != "true" ]]; then exit 0; fi\n')
        (self.root / 'upstream/takserver').mkdir(parents=True)
        self.commit(pin='1' * 40)
        self.app = self.git('rev-parse', 'HEAD')
        self.git('branch', 'app')
        for name in PRESERVED:
            (self.root / name).write_text('recorder\n')
        (self.root / '.github/container-and-chart/docker/Dockerfile').write_text('workflow recipe\n')
        (self.root / 'added-after-app.txt').write_text('must disappear\n')
        self.commit(pin='2' * 40)
        self.workflow = self.git('rev-parse', 'HEAD')
        self.git('remote', 'add', 'origin', str(self.root))

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, pin=None):
        self.git('add', '.')
        if pin:
            self.git('update-index', '--add', '--cacheinfo', f'160000,{pin},upstream/takserver')
        self.git('commit', '-qm', 'fixture')

    def select(self, ref=''):
        self.output = self.root / 'outputs'
        return subprocess.run(['bash', str(SELECT)], cwd=self.root, capture_output=True, text=True,
                              env={**os.environ, 'APP_REF': ref, 'EXPECTED_SHA': 'b' * 40,
                                   'GITHUB_OUTPUT': str(self.output)})

    def test_default_preserves_pr_head_lookup_without_changing_checkout(self):
        result = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.workflow)
        self.assertEqual(self.output.read_text().strip(), 'expected-sha=' + 'b' * 40)

    def test_custom_ref_changes_head_and_keeps_only_recorder_overlay(self):
        result = self.select('app')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.app)
        self.assertEqual(self.git('rev-parse', 'HEAD:.github/container-and-chart/docker'),
                         self.git('rev-parse', 'app:.github/container-and-chart/docker'))
        self.assertEqual((self.root / '.github/container-and-chart/docker/Dockerfile').read_text(), 'app\n')
        self.assertEqual(self.git('rev-parse', 'HEAD:upstream/takserver'), '1' * 40)
        self.assertFalse((self.root / 'added-after-app.txt').exists())
        for name in PRESERVED:
            self.assertEqual((self.root / name).read_text(), 'recorder\n')
        self.assertEqual(self.output.read_text().strip(), 'expected-sha=' + self.app)

    def test_executable_legacy_helper_is_not_executed_as_a_capability_probe(self):
        helper = self.root / '.github/container-and-chart/cloudtak/build.sh'
        helper.write_text('#!/bin/bash\ntouch unexpected-build\n')
        self.commit()
        self.git('branch', 'legacy')
        self.git('checkout', '-q', self.workflow)
        result = self.select('legacy')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('lacks the supported --wait branch', result.stderr)
        self.assertFalse((self.root / 'unexpected-build').exists())

    def test_unsupported_source_fails_clearly_before_any_wait(self):
        (self.root / HELPERS[0]).unlink()
        self.commit()
        self.git('branch', 'unsupported')
        self.git('checkout', '-q', self.workflow)
        result = self.select('unsupported')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported demo app source', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
