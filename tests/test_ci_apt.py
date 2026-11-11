# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise APT policy with source fixtures and a local fake apt-get only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ci_apt', ROOT/'.github/scripts/ci-apt.py')
APT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APT)


class AptTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root/'apt.conf.d').mkdir();(root/'sources.list.d').mkdir()
        return root

    def test_only_exact_public_ubuntu_http_endpoints_change(self):
        for host,target in APT.MIRRORS.items():
            self.assertEqual(APT.canonical_uri('http://'+host+'/ubuntu/'), 'https://'+target+'/ubuntu/')
        for uri in ['https://archive.ubuntu.com/ubuntu','http://custom.example/ubuntu',
                    'http://user:password@azure.archive.ubuntu.com/ubuntu',
                    'http://archive.ubuntu.com:8080/ubuntu','http://archive.ubuntu.com/custom',
                    'http://archive.ubuntu.com/ubuntu?token=private','http://archive.ubuntu.com/ubuntu#private',
                    'http://archive.ubuntu.com.evil.test/ubuntu']:
            self.assertEqual(APT.canonical_uri(uri),uri)

    def test_legacy_options_suites_components_comments_and_custom_repos_preserved(self):
        before = b'# http://azure.archive.ubuntu.com/ubuntu\ndeb [arch=amd64 signed-by=/keys/ubuntu.gpg] http://azure.archive.ubuntu.com/ubuntu jammy main universe # keep\ndeb-src https://custom.example/repo custom main\n'
        after = APT.rewrite(before,'list')
        self.assertEqual(after,before.replace(b'] http://azure.archive.ubuntu.com',b'] https://archive.ubuntu.com'))

    def test_deb822_multiple_uris_continuations_and_inline_signed_key_preserved(self):
        before = b'Types: deb deb-src\nURIs: http://azure.archive.ubuntu.com/ubuntu https://custom.example/repo\n http://security.ubuntu.com/ubuntu\nSuites: jammy jammy-updates\nComponents: main universe\nArchitectures: amd64\nSigned-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n keep-key-bytes\n -----END PGP PUBLIC KEY BLOCK-----\n'
        after = APT.rewrite(before,'sources')
        self.assertEqual(after,before.replace(b'http://azure.archive.ubuntu.com',b'https://archive.ubuntu.com').replace(b'http://security.ubuntu.com',b'https://security.ubuntu.com'))

    def test_mirrorlist_priority_and_comments_preserved(self):
        before = b'# mirrors\nhttp://azure.archive.ubuntu.com/ubuntu\tpriority:1\nhttps://custom.example/repo priority:2\n'
        self.assertEqual(APT.rewrite(before,'mirror'),before.replace(b'http://azure.archive.ubuntu.com',b'https://archive.ubuntu.com'))

    def test_real_atomic_fallback_handles_mirrorfile_and_preserves_mode(self):
        root = self.fixture();source=root/'sources.list'
        source.write_text('deb mirror+file:/etc/apt/apt-mirrors.txt jammy main\n')
        mirror=root/'apt-mirrors.txt';mirror.write_text('http://azure.archive.ubuntu.com/ubuntu priority:1\n');mirror.chmod(0o640)
        self.assertTrue(APT.fallback(root))
        self.assertEqual(source.read_text(),'deb mirror+file:/etc/apt/apt-mirrors.txt jammy main\n')
        self.assertIn('https://archive.ubuntu.com',mirror.read_text())
        self.assertEqual(mirror.stat().st_mode&0o777,0o640)
        self.assertFalse(APT.fallback(root))

    def test_symlinks_and_partial_replacement_fail_closed(self):
        root = self.fixture();outside=root/'outside';outside.write_text('private')
        (root/'sources.list').symlink_to(outside)
        with self.assertRaises(ValueError):APT.fallback(root)
        self.assertEqual(outside.read_text(),'private')
        (root/'sources.list').unlink()
        paths=[root/'sources.list',root/'sources.list.d/second.list']
        for p in paths:p.write_text('deb http://archive.ubuntu.com/ubuntu jammy main\n')
        original = APT.atomic_replace;calls=[]
        def fail_second(*args):
            calls.append(args)
            if len(calls)==2:raise OSError('fixture write failure')
            return original(*args)
        with patch.object(APT,'atomic_replace',side_effect=fail_second),self.assertRaises(OSError):APT.fallback(root)
        for p in paths:self.assertIn('http://archive.ubuntu.com',p.read_text())
        self.assertEqual(list(root.rglob('.uds-ci-*')),[])

    def test_no_stale_success_no_identical_retry_and_at_most_two_updates(self):
        for statuses,source,expected,calls in [([0],'http://archive.ubuntu.com',0,1),
                ([1],'https://custom.example',1,1),([1,0],'http://archive.ubuntu.com',0,2),
                ([1,1],'http://archive.ubuntu.com',1,2)]:
            with self.subTest(statuses=statuses,source=source):
                root=self.fixture();(root/'sources.list').write_text('deb '+source+'/ubuntu jammy main\n')
                runner=unittest.mock.Mock(side_effect=statuses)
                self.assertEqual(APT.update(root,runner),expected);self.assertEqual(runner.call_count,calls)
                config=(root/'apt.conf.d/99zz-uds-ci-acquisition').read_bytes()
                self.assertEqual(config,APT.CONFIG)
                self.assertNotIn(b'Trusted',config);self.assertNotIn(b'Verify-Peer',config)

    def test_complete_apt_url_diagnostics_hide_auth_and_query_values(self):
        text = 'failed http://user:PRIVATE_PASSWORD@custom.example/ubuntu and https://custom.example/repo?access=PRIVATE_TOKEN'
        scrubbed = APT.scrub_uri_credentials(text)
        self.assertNotIn('PRIVATE_PASSWORD',scrubbed)
        self.assertNotIn('PRIVATE_TOKEN',scrubbed)
        self.assertIn('[REDACTED URL]',scrubbed)
        self.assertEqual(APT.scrub_uri_credentials('http://archive.ubuntu.com/ubuntu'), 'http://archive.ubuntu.com/ubuntu')

    def test_owned_configuration_is_not_overwritten(self):
        root=self.fixture();path=root/'apt.conf.d/99zz-uds-ci-acquisition';path.write_text('custom')
        with self.assertRaises(ValueError):APT.configure(root)
        self.assertEqual(path.read_text(),'custom')

    def test_actual_command_simulation_preserves_security_options_and_one_install(self):
        root=self.fixture();tools=root/'bin';tools.mkdir();calls=root/'calls.jsonl'
        fake=tools/'apt-get';fake.write_text('#!'+sys.executable+'''\nimport json,os,sys
with open(os.environ['FAKE_APT_CALLS'],'a') as f:f.write(json.dumps({'args':sys.argv[1:],'noninteractive':os.environ.get('DEBIAN_FRONTEND')})+'\\n')
print('signed acquisition fixture')
''');fake.chmod(0o755)
        with patch.dict(os.environ,{'PATH':str(tools)+os.pathsep+os.environ['PATH'],'FAKE_APT_CALLS':str(calls)}):
            self.assertEqual(APT.run_apt('update'),0)
            self.assertEqual(APT.run_apt('install',['ffmpeg','python3-venv']),0)
        records=[json.loads(line) for line in calls.read_text().splitlines()]
        self.assertEqual(len(records),2)
        for record in records:
            self.assertIn('APT::Update::Error-Mode=any',record['args'])
            self.assertIn('Acquire::Retries=0',record['args'])
            self.assertIn('Acquire::https::Timeout=10',record['args'])
            self.assertEqual(record['noninteractive'],'noninteractive')
            self.assertNotIn('--allow-unauthenticated',record['args'])
        self.assertEqual(records[1]['args'][-2:],['ffmpeg','python3-venv'])

    def test_deadline_discards_partial_output_without_real_apt(self):
        root=self.fixture();tools=root/'bin';tools.mkdir();fake=tools/'apt-get'
        fake.write_text('#!'+sys.executable+'\nimport time\nprint("private partial",flush=True)\ntime.sleep(5)\n');fake.chmod(0o755)
        with patch.dict(os.environ,{'PATH':str(tools)+os.pathsep+os.environ['PATH']}):
            self.assertEqual(APT.run_apt('update',seconds=.15),124)

    def test_demo_uses_shared_bounded_helper_and_guards_missing_uds(self):
        workflow=yaml.load((ROOT/'.github/workflows/demo.yaml').read_text(),Loader=yaml.BaseLoader)
        steps=workflow['jobs']['record']['steps'];install=next(s for s in steps if s['name']=='Install recording tools')
        self.assertIn('ci-apt.py update',install['run']);self.assertIn('ci-apt.py install',install['run'])
        self.assertNotIn('for attempt',install['run']);self.assertNotIn('apt_try',install['run'])
        debug=next(s for s in steps if s['name']=='Debug Output');self.assertIn('command -v uds',debug['run'])


if __name__=='__main__':unittest.main()
