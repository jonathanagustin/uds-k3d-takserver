# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Keep active publishers on the renamed repository with explicit legacy reads."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
OLD = 'uds-' + 'k3d-takserver'
NEW = 'uds-takserver'
SIGNERS = {
    '.github/workflows/release.yaml': 1,
    'README.md': 2,
    'demo/record-terminal.sh': 1,
    'demo/shell.sh': 1,
    'demo/upgrade.sh': 1,
    'tests/upgrade.sh': 1,
}


_SPEC = importlib.util.spec_from_file_location(
    'published_package_ref', ROOT / '.github/scripts/published_package_ref.py')
_PUBLISHED = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PUBLISHED)


def legacy_readme_fixture():
    package = f'ghcr.io/jonathanagustin/{OLD}/takserver'
    signer = f'https://github.com/jonathanagustin/({OLD}|{NEW})/.github/workflows/release.yaml'
    return '\n'.join([
        'VERSION=0.10.0 # x-release-please-version',
        f'Published package: oci://{package}:0.10.0-upstream',
        f'uds zarf package deploy "oci://{package}:${{VERSION}}-upstream"',
        f'uds zarf package verify "oci://{package}:${{VERSION}}-upstream"',
        f'repository: {package}',
        f'gh attestation verify "oci://{package}:${{VERSION}}-upstream"',
        signer, signer,
        f'https://github.com/jonathanagustin/{OLD}/.github/workflows/demo.yaml@refs/heads/main',
    ])


def readme_uses_legacy_packages(readme, version):
    """Couple release markers/examples to the same immutable registry selector."""
    expected = _PUBLISHED.published_package_ref(version)
    markers = re.findall(r'^VERSION=([^ #]+) # x-release-please-version$', readme, re.MULTILINE)
    if not markers:
        raise ValueError('README release version markers are missing')
    if any(marker != version for marker in markers):
        raise ValueError(f'README VERSION markers must match manifest release {version}')
    legacy = f'/{OLD}/' in expected
    if not legacy and f'ghcr.io/jonathanagustin/{OLD}/takserver' in readme:
        raise ValueError(f'Release {version} resolves to {expected}, but README still uses legacy package examples; '
                         'update package references together with VERSION markers')
    return legacy


class RepositoryNameTests(unittest.TestCase):
    def test_only_documented_immutable_compatibility_uses_the_previous_name(self):
        version = json.loads((ROOT / '.release-please-manifest.json').read_text())['.']
        legacy_readme = readme_uses_legacy_packages((ROOT / 'README.md').read_text(), version)
        names = subprocess.check_output(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
        counts = Counter()
        signer_counts = Counter()
        for name in names.decode().split('\0'):
            path = ROOT / name
            if not name or name.startswith('upstream/') or not path.is_file():
                continue
            data = path.read_bytes()
            if OLD.encode() not in data:
                continue
            for line in data.decode().splitlines():
                if OLD not in line:
                    continue
                counts[name] += 1
                if name in SIGNERS and f'/({OLD}|{NEW})/' in line:
                    signer_counts[name] += 1
                    self.assertIn(f'/({OLD}|{NEW})/', line, name)
                    self.assertIn('workflows/release', line, name)
                elif name == 'README.md':
                    legacy_package = f'ghcr.io/jonathanagustin/{OLD}/takserver'
                    self.assertTrue(any(value in line for value in (
                        f'The current 0.10 release is published as `oci://{legacy_package}:0.10.0-upstream`',
                        f'uds zarf package deploy "oci://{legacy_package}:${{VERSION}}-upstream" --confirm',
                        f'uds zarf package verify "oci://{legacy_package}:${{VERSION}}-upstream"',
                        f'repository: {legacy_package}',
                        f'gh attestation verify "oci://{legacy_package}:${{VERSION}}-upstream"',
                        f'--certificate-identity https://github.com/jonathanagustin/{OLD}/.github/workflows/demo.yaml@refs/heads/main',
                    )), line)
                elif name == 'docs/how-to/upgrade-from-0-6.md':
                    self.assertEqual(line.strip(),
                        f'uds zarf package deploy "oci://ghcr.io/jonathanagustin/{OLD}/takserver:${{VERSION}}-upstream" --confirm')
                elif name == '.github/container-and-chart/postgis/smoke.sh':
                    self.assertEqual(line, f'old_image="${{OLD_IMAGE:-ghcr.io/jonathanagustin/{OLD}/postgis:15-3.4}}"')
                elif name == '.github/scripts/published_package_ref.py':
                    self.assertIn(f'namespace = "{OLD}" if parsed < (0, 11, 0)', line)
                elif name == 'tests/test_upgrade_baseline.py':
                    self.assertTrue('takserver:0.6.0-upstream' in line or
                                    f'("0.10.0", "{OLD}")' in line, line)
                else:
                    self.fail(f'Active legacy repository reference in {name}')
        self.assertEqual(signer_counts, Counter(SIGNERS))
        self.assertEqual(counts, Counter({**SIGNERS, 'README.md': 8 if legacy_readme else 3,
                         'docs/how-to/upgrade-from-0-6.md': 1,
                         '.github/container-and-chart/postgis/smoke.sh': 1,
                         '.github/scripts/published_package_ref.py': 1, 'tests/test_upgrade_baseline.py': 2}))

    def test_release_version_update_cannot_leave_legacy_package_examples(self):
        readme = legacy_readme_fixture()
        self.assertTrue(readme_uses_legacy_packages(readme, '0.10.0'))
        updated_markers = readme.replace('VERSION=0.10.0', 'VERSION=0.11.0')
        with self.assertRaisesRegex(ValueError, 'README still uses legacy package examples'):
            readme_uses_legacy_packages(updated_markers, '0.11.0')
        with self.assertRaisesRegex(ValueError, 'VERSION markers must match manifest'):
            readme_uses_legacy_packages(updated_markers, '0.10.0')

    def test_renamed_release_keeps_only_immutable_trust_references(self):
        for version in ('0.11.0', '1.10.0'):
            with self.subTest(version=version):
                readme = legacy_readme_fixture().replace('VERSION=0.10.0', f'VERSION={version}')
                readme = readme.replace(f'ghcr.io/jonathanagustin/{OLD}/takserver',
                                       f'ghcr.io/jonathanagustin/{NEW}/takserver')
                self.assertFalse(readme_uses_legacy_packages(readme, version))
                self.assertEqual(sum(OLD in line for line in readme.splitlines()), 3)

    def test_label_publishers_and_readers_agree_on_the_new_namespace(self):
        files = [ROOT / '.github/container-and-chart' / image / 'build.sh'
                 for image in ('docker', 'cloudtak', 'postgis')]
        for path in files:
            with self.subTest(path=path):
                source = path.read_text()
                self.assertIn('ghcr.io/jonathanagustin/' + NEW, source)
                self.assertIn('dev.' + NEW + '.inputs', source)
                self.assertNotIn('dev.' + OLD + '.inputs', source)


if __name__ == '__main__':
    unittest.main()
