# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Real subprocess fixtures prove acquisition policy, not a browser launch."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocsBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        self.scripts = self.root/'.github/scripts'
        self.scripts.mkdir(parents=True)
        for name in ('check-docs-browser.py', 'docs-browser-smoke.cjs', 'redact-logs.py'):
            shutil.copyfile(ROOT/'.github/scripts'/name, self.scripts/name)
        self.paths = []
        for name in ('chromium', 'headless'):
            directory = self.root/name
            directory.mkdir()
            executable = directory/'chrome'
            executable.write_bytes(b'\x7fELFfixture')
            (directory/'child.so').write_bytes(b'\x7fELFchild')
            self.paths.append(str(executable))
        self.fake('node', '''import json,os,sys
from pathlib import Path
root=Path(os.environ['FIXTURE'])
with (root/'calls').open('a') as f:f.write('node '+sys.argv[-1]+'\\n')
if sys.argv[-1]=='paths':print(os.environ['BROWSER_PATHS'])
elif os.environ.get('SCENARIO')=='launch-failure':
 print('password=PRIVATE_BROWSER_PASSWORD',file=sys.stderr);sys.exit(1)
else:print('fixture launch, not a real browser')
''')
        self.fake('ldd', '''import os
from pathlib import Path
root=Path(os.environ['FIXTURE'])
with (root/'calls').open('a') as f:f.write('ldd\\n')
scenario=os.environ.get('SCENARIO','')
if scenario=='unknown':print('libuntrusted.so.1 => not found')
elif scenario in ('missing','install-failure','still-missing') and (not (root/'installed').exists() or scenario=='still-missing'):
 print('libnss3.so => not found')
else:print('libnss3.so => /usr/lib/libnss3.so (0x123)')
''')
        self.fake('sudo', '''import os,sys
from pathlib import Path
root=Path(os.environ['FIXTURE'])
assert sys.argv[2].endswith('/ci-apt.py')
with (root/'calls').open('a') as f:f.write('apt '+' '.join(sys.argv[3:])+'\\n')
if sys.argv[3]=='install':
 if os.environ.get('SCENARIO')=='install-failure':sys.exit(1)
 (root/'installed').touch()
''')

    def fake(self, name, body):
        path = self.bin/name
        path.write_text('#!/usr/bin/env python3\n'+body)
        path.chmod(0o755)

    def invoke(self, scenario=''):
        result = subprocess.run(['python3',str(self.scripts/'check-docs-browser.py')],
            cwd=self.root, capture_output=True, text=True, timeout=15,
            env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                 'FIXTURE':str(self.root),'BROWSER_PATHS':json.dumps(self.paths),'SCENARIO':scenario})
        calls = (self.root/'calls').read_text().splitlines()
        return result,calls

    def test_present_libraries_skip_apt_and_audit_both_distributions_children(self):
        result,calls = self.invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls.count('ldd'),4)
        self.assertEqual(calls.count('node launch'),1)
        self.assertFalse(any(c.startswith('apt ') for c in calls))

    def test_missing_known_library_gets_one_exact_acquisition_then_fresh_audit(self):
        result,calls = self.invoke('missing')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([c for c in calls if c.startswith('apt ')],['apt update','apt install libnss3'])
        self.assertEqual(calls.count('ldd'),8)
        self.assertEqual(calls[-1],'node launch')

    def test_unknown_library_never_enters_apt_or_launch(self):
        result,calls = self.invoke('unknown')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c.startswith('apt ') for c in calls))
        self.assertNotIn('node launch',calls)

    def test_unknown_launch_failure_is_redacted_without_apt_retry(self):
        result,calls = self.invoke('launch-failure')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('PRIVATE_BROWSER_PASSWORD',result.stdout+result.stderr)
        self.assertIn('[REDACTED]',result.stdout)
        self.assertFalse(any(c.startswith('apt ') for c in calls))

    def test_failed_acquisition_does_not_launch(self):
        result,calls = self.invoke('install-failure')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('node launch',calls)
        self.assertEqual(calls.count('apt update'),1)

    def test_still_missing_after_install_never_retries(self):
        result,calls = self.invoke('still-missing')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('node launch',calls)
        self.assertEqual(calls.count('apt update'),1)
        self.assertEqual(calls.count('apt install libnss3'),1)

    def test_child_escape_is_rejected_before_audit(self):
        (self.root/'chromium/escape').symlink_to(self.root/'bin/node')
        result,calls = self.invoke()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(calls,['node paths'])


if __name__=='__main__': unittest.main()
