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

MEDIA_SPEC = importlib.util.spec_from_file_location('media_preflight', ROOT/'demo/tools/check-media.py')
MEDIA_CHECK = importlib.util.module_from_spec(MEDIA_SPEC)
MEDIA_SPEC.loader.exec_module(MEDIA_CHECK)


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

    def test_pr_preflight_shares_manual_tools_without_deploy_or_publish_permissions(self):
        workflow = yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(), Loader=yaml.BaseLoader)
        record, preflight = workflow['jobs']['record'], workflow['jobs']['preflight']
        self.assertEqual(record['if'], "${{ github.event_name == 'workflow_dispatch' && !inputs.sign_only }}")
        self.assertEqual(preflight['if'], "github.event_name == 'pull_request'")
        self.assertEqual(preflight['timeout-minutes'], '10')
        self.assertEqual(preflight['permissions'], {'contents':'read'})
        self.assertEqual(preflight['runs-on'], record['runs-on'])
        self.assertEqual(len(preflight['steps']), 4)
        self.assertEqual(preflight['steps'][0]['with']['persist-credentials'], 'false')
        for shared in preflight['steps'][1:]:
            original = next(step for step in record['steps'] if step['name'] == shared['name'])
            self.assertEqual(shared, original)  # Shared lint cannot parse aliases across extracted steps.
        for event, sign_only, expected in [('pull_request',False,False), ('pull_request',True,False),
                                           ('workflow_dispatch',False,True), ('workflow_dispatch',True,False)]:
            expression = record['if'][3:-3].replace('github.event_name',repr(event))
            expression = expression.replace('!inputs.sign_only',repr(not sign_only)).replace('&&','and')
            self.assertEqual(eval(expression, {'__builtins__':{}}), expected)
        publish, sign = workflow['jobs']['publish'], workflow['jobs']['sign']
        self.assertEqual(publish['needs'], 'record')
        self.assertEqual(publish['if'], "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'")
        self.assertEqual(sign['needs'], ['record','publish'])
        self.assertIn("github.ref == 'refs/heads/main'", sign['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'", sign['if'])

    def test_vhs_recording_protocol_uses_real_tape_command_and_disables_publication(self):
        # This fixture exercises argv, shell/tape quoting and exit handling only.
        # It does not run VHS or establish recording/media qualification.
        with tempfile.TemporaryDirectory(prefix="explicit VHS protocol's fixture ") as directory:
            output = Path(directory)
            calls = []
            def fixture_run(command, seconds):
                calls.append(command)
                if command[1] == 'validate':
                    self.assertEqual(seconds, 10)
                    self.assertEqual(len(command), 3)
                    self.assertTrue(Path(command[2]).is_file())
                    return
                self.assertEqual(command[:3], ['vhs','--publish=false','--output'])
                self.assertEqual(seconds, 45)
                self.assertEqual(os.environ['VHS_PUBLISH'], 'false')
                tape = Path(command[-1]).read_text().splitlines()
                self.assertEqual(json.loads(tape[0].split(' ',1)[1]), str(ROOT/'demo/settings.tape'))
                self.assertEqual(tape[-2:], ['Enter','Sleep 2s'])
                typed = next(line for line in tape if line.startswith('Type@1ms ')).split(' ',1)[1]
                self.assertTrue(typed.startswith('`') and typed.endswith('`'))
                shell_command = typed[1:-1]
                self.assertIn("\"$?\"", shell_command)
                subprocess.run(['bash','-c',shell_command], check=True, stdout=subprocess.DEVNULL)
            with patch.dict(os.environ, {'VHS_PUBLISH':'true'}):
                tape, video = MEDIA_CHECK.record_vhs(output, fixture_run)
                self.assertEqual(os.environ['VHS_PUBLISH'], 'true')
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], ['vhs','validate',str(tape)])
            self.assertEqual((output/'vhs.exit').read_text().strip(), '0')
            self.assertEqual(video, output/'vhs.mp4')
            self.assertTrue(tape.is_file())

    def test_vhs_command_failure_has_no_fallback_and_restores_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            def failed(*args, **kwargs):
                raise subprocess.CalledProcessError(1, '<explicit VHS fixture>')
            with patch.dict(os.environ, {'VHS_PUBLISH':'true'}), self.assertRaises(subprocess.CalledProcessError):
                try:
                    MEDIA_CHECK.record_vhs(Path(directory), failed)
                finally:
                    self.assertEqual(os.environ['VHS_PUBLISH'], 'true')
            self.assertFalse((Path(directory)/'receipt.json').exists())
        for status in (None, '1'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                def fixture_run(command, **kwargs):
                    if command[1] != 'validate' and status is not None:
                        (output/'vhs.exit').write_text(status)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    MEDIA_CHECK.record_vhs(output, fixture_run)

    def test_conflicting_vhs_delimiter_is_rejected_before_any_tool_runs(self):
        with tempfile.TemporaryDirectory(prefix='explicit ` delimiter fixture ') as directory:
            def must_not_run(*args, **kwargs):
                self.fail('unsupported tape delimiter must not reach VHS')
            with self.assertRaisesRegex(ValueError, 'backtick'):
                MEDIA_CHECK.record_vhs(Path(directory), must_not_run)
            self.assertFalse((Path(directory)/'vhs.tape').exists())

    def test_actual_video_probe_rejects_wrong_codec_geometry_and_duration(self):
        valid = {'streams':[{'codec_name':'h264','width':1632,'height':840,
                             'pix_fmt':'yuv420p','r_frame_rate':'30/1'}], 'format':{'duration':'2.5'}}
        with patch.object(MEDIA_CHECK.subprocess, 'check_output', return_value=json.dumps(valid)):
            self.assertEqual(MEDIA_CHECK.probe_video(Path('fixture.mp4'),1632,840,1.5,6), valid)
        for field, bad in [('codec_name','vp9'), ('width',640), ('height',360),
                           ('pix_fmt','yuv444p'), ('r_frame_rate','10/1'), ('duration','30')]:
            value = json.loads(json.dumps(valid))
            if field == 'duration':
                value['format'][field] = bad
            else:
                value['streams'][0][field] = bad
            with self.subTest(field=field), patch.object(MEDIA_CHECK.subprocess, 'check_output', return_value=json.dumps(value)):
                with self.assertRaisesRegex(ValueError, 'media output differs'):
                    MEDIA_CHECK.probe_video(Path('fixture.mp4'),1632,840,1.5,6)

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

    def test_actual_dependency_protocol_rejects_old_ttyd_and_unknown_vhs_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('ttyd','vhs'):
                path=root/name
                path.write_text('#!'+sys.executable+'\n'+
                    'import os,sys\nfrom pathlib import Path\n'+
                    'name=Path(__file__).name\n'+
                    'if name=="ttyd":print("ttyd version "+os.environ.get("FIXTURE_TTYD","1.7.7-40e79c7"))\n'+
                    'elif sys.argv[1]=="--version":print("vhs version v0.12.1 (24fa225)")\n'+
                    'else:\n'+
                    ' assert sys.argv[1:]==["-"] and sys.stdin.read()==""\n'+
                    ' Path(os.environ["PROBE_CALLED"]).touch()\n'+
                    ' print(os.environ.get("FIXTURE_RESULT","no input provided"))\n'+
                    ' raise SystemExit(int(os.environ.get("FIXTURE_CODE","1")))\n')
                path.chmod(0o755)
            environment={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],
                         'PROBE_CALLED':str(root/'called')}
            with patch.dict(os.environ,environment,clear=True):
                result=MEDIA_CHECK.check_terminal_dependencies()
                self.assertIn('1.7.7',result['ttyd'])
                self.assertTrue((root/'called').exists())
                (root/'called').unlink()
                with patch.dict(os.environ,{'FIXTURE_TTYD':'1.6.3'}):
                    with self.assertRaisesRegex(ValueError,'ttyd'):MEDIA_CHECK.check_terminal_dependencies()
                self.assertFalse((root/'called').exists())
                for changes in ({'FIXTURE_RESULT':'dependency failed'}, {'FIXTURE_CODE':'0'}):
                    with patch.dict(os.environ,changes),self.assertRaisesRegex(ValueError,'dependency preflight'):
                        MEDIA_CHECK.check_terminal_dependencies()

    def test_workflow_pins_official_ttyd_instead_of_unsupported_apt_release(self):
        workflow=yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(workflow['env']['TTYD_VERSION'],'1.7.7')
        self.assertEqual(workflow['env']['TTYD_SHA256'],'8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55')
        setup=next(s for s in workflow['jobs']['record']['steps'] if s['name']=='Install recording tools')['run']
        self.assertNotIn('install ffmpeg ttyd',setup)
        self.assertIn('https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64',setup)
        self.assertIn('${TTYD_SHA256}  ${RUNNER_TEMP}/ttyd',setup)
        self.assertIn('sha256sum -c -',setup)
        self.assertIn('--max-time 30 --max-filesize 1400000',setup)

    def test_old_cli_is_rejected_before_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'proof'
            with patch.object(CHECK.subprocess, 'check_output', return_value='asciinema 2.1.0\n'), patch.object(CHECK.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'version differs'):
                    CHECK.check(Path('/fake/recorder'), output)
                run.assert_not_called()
            self.assertFalse((output/'receipt.json').exists())


if __name__=='__main__': unittest.main()
