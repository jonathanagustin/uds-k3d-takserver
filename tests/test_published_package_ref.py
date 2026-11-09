# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Published demo and upgrade consumers share numeric registry selection."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.github/scripts/published_package_ref.py'
SPEC = importlib.util.spec_from_file_location('published_ref', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
OLD = 'uds-' + 'k3d-takserver'


class PublishedPackageTests(unittest.TestCase):
    def test_numeric_boundary_and_cli_use_real_published_namespaces(self):
        for version, namespace in [('0.9.1', OLD), ('0.10.0', OLD), ('v0.10.0', OLD),
                                   ('0.11.0', 'uds-takserver'), ('1.10.0', 'uds-takserver')]:
            with self.subTest(version=version):
                expected = f'oci://ghcr.io/jonathanagustin/{namespace}/takserver:{version.removeprefix("v")}-upstream'
                self.assertEqual(MODULE.published_package_ref(version), expected)
                self.assertEqual(subprocess.check_output(['python3', str(SCRIPT), version], text=True).strip(), expected)

    def test_invalid_versions_fail_without_a_reference(self):
        for value in ['', '0.11', '00.11.0', '0.11.0-rc.1', '1.2.3/path', '1.2.3\n']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    MODULE.published_package_ref(value)
                result = subprocess.run(['python3', str(SCRIPT), value], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_demo_scripts_and_actual_tape_render_use_the_shared_reference(self):
        record = (ROOT / 'demo/record-terminal.sh').read_text()
        upgrade = (ROOT / 'demo/upgrade.sh').read_text()
        self.assertIn('published_package_ref.py "${DEMO_VERSION}"', record)
        self.assertIn('uds zarf package pull "${DEMO_PACKAGE_REF}"', record)
        self.assertIn('published_package_ref.py "${previous}"', upgrade)
        self.assertIn('uds zarf package pull "${previous_package}"', upgrade)
        for version in ('0.10.0', '0.11.0'):
            expected = MODULE.published_package_ref(version)
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'secure.tape'
                subprocess.run(['python3', str(ROOT / 'demo/ragged.py'),
                                str(ROOT / 'demo/tapes/03-secure.tape'), str(output)], check=True,
                               env={**os.environ, 'DEMO_VERSION': version, 'DEMO_PACKAGE_REF': expected,
                                    'DEMO_RELEASE_PACKAGE': '/tmp/package-fixture.tar.zst'})
                self.assertIn('gh attestation verify ' + expected, output.read_text())
                self.assertNotIn('{{PACKAGE_REF}}', output.read_text())


if __name__ == '__main__':
    unittest.main()
