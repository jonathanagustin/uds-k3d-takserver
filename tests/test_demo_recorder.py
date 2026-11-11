# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Keep the exact checked recorder ahead of cluster deployment."""
import importlib.util
import json
import os
import subprocess
import sys
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

    def test_exported_recorder_preserves_media_python_and_venv_shebang(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media, recorder = root/'media', root/'asciinema'
            for environment in (media, recorder):
                subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(environment)], check=True)
            # A media-only dependency represents apt's Pillow without modifying
            # the real interpreter or installing anything into the recorder.
            media_python = media/'bin/python3'
            site = subprocess.check_output([str(media_python), '-c',
                'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
            (Path(site)/'media_dependency.py').write_text('VALUE = "media-only"\n')
            executable = recorder/'bin/asciinema'
            executable.write_text('#!'+str(recorder/'bin/python3')+'\nimport sys; print(sys.prefix)\n')
            executable.chmod(0o755)
            workflow = yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(), Loader=yaml.BaseLoader)
            setup = next(s for s in workflow['jobs']['record']['steps']
                         if s['name']=='Install and check the pinned terminal recorder')['run']
            # Execute the actual publication commands, not a parallel imitation.
            publication = setup[setup.index('mkdir -p "${RUNNER_TEMP}/recorder-bin"'):]
            path_file = root/'github-path'
            env = dict(os.environ, RUNNER_TEMP=str(root), GITHUB_PATH=str(path_file))
            subprocess.run(['bash', '-euc', publication], env=env, check=True)
            env['PATH'] = path_file.read_text().strip()+os.pathsep+str(media/'bin')+os.pathsep+os.environ['PATH']
            env.pop('PYTHONPATH', None)
            actual = json.loads(subprocess.check_output(['python3', '-c',
                'import json,sys,media_dependency; print(json.dumps([sys.prefix,media_dependency.VALUE]))'], env=env, text=True))
            self.assertEqual(actual, [str(media), 'media-only'])
            self.assertEqual(subprocess.check_output(['asciinema'], env=env, text=True).strip(), str(recorder))
            self.assertEqual([p.name for p in (root/'recorder-bin').iterdir()], ['asciinema'])
            # The former whole-venv PATH demonstrably hides that dependency.
            env['PATH'] = str(recorder/'bin')+os.pathsep+env['PATH']
            hidden = subprocess.run(['python3', '-c', 'import media_dependency'], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(hidden.returncode, 0)
            self.assertIn(b'ModuleNotFoundError', hidden.stderr)

    def test_old_cli_is_rejected_before_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'proof'
            with patch.object(CHECK.subprocess, 'check_output', return_value='asciinema 2.1.0\n'), patch.object(CHECK.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'version differs'):
                    CHECK.check(Path('/fake/recorder'), output)
                run.assert_not_called()
            self.assertFalse((output/'receipt.json').exists())


if __name__=='__main__': unittest.main()
