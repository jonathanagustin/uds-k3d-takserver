# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Keep the exact checked recorder ahead of cluster deployment."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('recorder_check', ROOT/'demo/tools/check-asciinema.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class RecorderTests(unittest.TestCase):
    def test_workflow_installs_only_hashed_wheel_and_checks_before_deploy(self):
        workflow = yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(), Loader=yaml.BaseLoader)
        steps = workflow['jobs']['record']['steps']
        setup = next(s for s in steps if s['name']=='Install and check the pinned terminal recorder')
        deploy = next(s for s in steps if s['name']=='Deploy UDS Core and TAK')
        self.assertLess(steps.index(setup), steps.index(deploy))
        for token in ('python3 -m venv', '--isolated', '--no-deps', '--only-binary=:all:', '--require-hashes', 'check-asciinema.py', 'GITHUB_PATH'):
            self.assertIn(token, setup['run'])
        self.assertNotIn('apt-get', deploy['run'])
        self.assertIn('--cols 132 --rows 34', deploy['run'])
        requirement = (ROOT/'demo/tools/asciinema-requirements.txt').read_text()
        self.assertIn('asciinema-2.4.0-py3-none-any.whl', requirement)
        self.assertIn('--hash=sha256:249ccf108509d643ddaf38979dac48c99e9e251f597173d8553a30d7a6423104', requirement)

    def test_old_cli_is_rejected_before_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'proof'
            with patch.object(CHECK.subprocess, 'check_output', return_value='asciinema 2.1.0\n'), patch.object(CHECK.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'version differs'):
                    CHECK.check(Path('/fake/recorder'), output)
                run.assert_not_called()
            self.assertFalse((output/'receipt.json').exists())


if __name__=='__main__': unittest.main()
