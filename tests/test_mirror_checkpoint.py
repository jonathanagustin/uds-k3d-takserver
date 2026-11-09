# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Execute the mirror workflow against dynamic and literal version inputs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class MirrorCheckpointTests(unittest.TestCase):
    def run_plan(self, extra=''):
        workflow = yaml.safe_load((ROOT / '.github/workflows/mirror-checkpoint.yaml').read_text())
        script = next(step['run'] for step in workflow['jobs']['mirror']['steps']
                      if step.get('name') == 'Copy the missing versions')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / '.github/scripts/deploy-slim-core.sh'
            source.parent.mkdir(parents=True)
            source.write_text((ROOT / '.github/scripts/deploy-slim-core.sh').read_text())
            (root / 'tests').mkdir()
            # The real dynamic selector used to contribute an empty version.
            (root / 'tests/upgrade.sh').write_text((ROOT / 'tests/upgrade.sh').read_text())
            (root / 'tasks.yaml').write_text('SLIM_CORE_VERSION=1.15.0\n' + extra)
            mock = root / 'uds'
            mock.write_text('''#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == "zarf tools registry digest "* ]] || exit 91
ref="${@: -1}"
[[ "$ref" =~ :[0-9]+\\.[0-9]+\\.[0-9]+$ ]] || exit 92
printf '%s\\n' "$ref" >> "$REF_LOG"
v="${ref##*:}"
sed -n "s/^ *\\[${v//./\\.}\\]=\\(sha256:[0-9a-f]*\\).*/\\1/p" .github/scripts/deploy-slim-core.sh
''')
            mock.chmod(0o755)
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       UPSTREAM='upstream/checkpoint', MIRROR='mirror/checkpoint',
                       REF_LOG=str(root / 'refs'))
            result = subprocess.run(['bash', '-c', script], cwd=root, env=env,
                                    text=True, capture_output=True)
            refs = (root / 'refs').read_text().splitlines() if (root / 'refs').exists() else []
            return result, refs

    def test_dynamic_upgrade_selector_never_requests_empty_tag(self):
        result, refs = self.run_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Versions: 1.15.0 1.15.2 1.16.0', result.stdout)
        self.assertEqual(refs, [f'{repo}/checkpoint:{version}'
                              for version in ('1.15.0', '1.15.2', '1.16.0')
                              for repo in ('upstream', 'mirror')])

    def test_malformed_literal_fails_before_any_registry_request(self):
        result, refs = self.run_plan('SLIM_CORE_VERSION=1.2\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid checkpoint version: 1.2', result.stderr)
        self.assertEqual(refs, [])


if __name__ == '__main__':
    unittest.main()
