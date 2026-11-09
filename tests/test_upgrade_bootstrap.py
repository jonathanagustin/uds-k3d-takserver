# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Published Core/Pepr pairs and fail-closed checkpoint selection contracts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('upgrade-bootstrap.py')
SPEC = importlib.util.spec_from_file_location('upgrade_bootstrap', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BootstrapTests(unittest.TestCase):
    def cli(self, refs, package, raw=False):
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / 'core.json'
            pepr = Path(directory) / 'pepr.json'
            core.write_text(refs if raw else json.dumps(refs))
            pepr.write_text(package if raw else json.dumps(package))
            return subprocess.run(['python3', str(SCRIPT), str(core), str(pepr)], capture_output=True, text=True)

    def test_actual_published_source_pairs_select_compatible_checkpoints(self):
        # Source: each tag's bundle/uds-bundle.yaml and pepr/package.json.
        # v0.6=8735336, v0.7=8c1e029, v0.10=12c193e, v0.11=eb4c66f.
        cases = [('v0.6.0', '1.15.2-upstream', '2.0.3', '1.15.0'),
                 ('v0.7.0', '1.16.0-upstream', '2.0.7', '1.16.0'),
                 ('v0.10.0', '1.16.0-upstream', '2.0.7', '1.16.0'),
                 ('v0.11.0', '1.16.0-upstream', '2.0.7', '1.16.0')]
        for tag, core, pepr, expected in cases:
            with self.subTest(release=tag):
                package = {'dependencies': {'pepr': pepr}, 'pepr': {'peprVersion': pepr}}
                self.assertEqual(MODULE.select_bootstrap([core], package), expected)
                result = self.cli([core], package)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected + '\n')

    def test_missing_duplicate_and_unknown_pairs_never_guess_a_checkpoint(self):
        cases = [(None, {}), ([], {}), (['1.16.0-upstream'] * 2, {}), ([None], {}), ([''], {}),
                 (['1.16.0-upstream'], None), (['1.16.0-upstream'], {'dependencies': []}),
                 (['1.16.0-upstream'], {'dependencies': {}}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': ''}}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': 207}}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': '2.0.7'}}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': '2.0.7'}, 'pepr': []}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': '2.0.7'}, 'pepr': {}}),
                 (['1.16.0-upstream'], {'dependencies': {'pepr': '2.0.7'}, 'pepr': {'peprVersion': '2.0.3'}}),
                 (['1.15.2-upstream'], {'dependencies': {'pepr': '2.0.5'}, 'pepr': {'peprVersion': '2.0.5'}}),
                 (['1.17.0-upstream'], {'dependencies': {'pepr': '2.0.7'}, 'pepr': {'peprVersion': '2.0.7'}})]
        for refs, package in cases:
            with self.subTest(refs=refs, package=package):
                with self.assertRaises(ValueError):
                    MODULE.select_bootstrap(refs, package)
                result = self.cli(refs, package)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_duplicate_json_members_malformed_and_missing_files_fail_closed(self):
        for refs, package in [('[]', '{}'), ('not json', '{}'),
                              ('["1.16.0-upstream"]', '{"dependencies":{"pepr":"2.0.3","pepr":"2.0.7"}}')]:
            result = self.cli(refs, package, raw=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['python3', str(SCRIPT), str(Path(directory) / 'missing-core.json'),
                                     str(Path(directory) / 'missing-pepr.json')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_upgrade_uses_only_release_data_and_the_same_version_for_cleanup(self):
        source = SCRIPT.with_name('upgrade.sh').read_text()
        self.assertIn('git show "${tag}:pepr/package.json"', source)
        self.assertIn('[.packages[] | select(.name == "core-base") | .ref]', source)
        self.assertLess(source.index('bootstrap_core="$('), source.index('uds create "${work}/bundle"'))
        self.assertIn('SLIM_CORE_VERSION="${bootstrap_core}" uds run deploy-slim-core', source)
        self.assertIn('zarf-package-k3d-core-slim-dev-*-"${bootstrap_core}".tar.zst', source)
        self.assertNotIn('SLIM_CORE_VERSION=1.15.0', source)


if __name__ == '__main__':
    unittest.main()
