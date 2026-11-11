#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real package key without building a package."""
import os
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
import time
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/dev-package.sh'
PUBLISH_SCRIPT = SCRIPT.with_name('publish-dev-package.py')
SPEC = importlib.util.spec_from_file_location('owned_package_publication', PUBLISH_SCRIPT)
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)


class PackagePublicationTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        (root / 'zarf.yaml').write_text('package input fixture\n')
        subprocess.run(['git', '-C', str(root), 'add', 'zarf.yaml'], check=True)
        tools = root / 'bin'; tools.mkdir()
        publisher = root / '.github/scripts/publish-dev-package.py'
        publisher.parent.mkdir(parents=True)
        publisher.write_bytes(PUBLISH_SCRIPT.read_bytes())
        uds = tools / 'uds'
        uds.write_text('#!' + sys.executable + '''
import hashlib,json,os,pathlib,sys
a=sys.argv[1:]
with open(os.environ['PUBLISH_CALLS'],'a') as output: output.write(json.dumps(a)+'\\n')
if a==['version']: print('fixture UDS 0.41.0')
elif a[:4]==['zarf','tools','registry','digest']: sys.exit(0 if os.environ.get('PUBLISH_EXISTS')=='true' else 1)
elif a[:3]==['zarf','package','publish']:
    data=pathlib.Path(a[3]).read_bytes()
    pathlib.Path(os.environ['PUBLISH_ARCHIVE_HASH']).write_text(hashlib.sha256(data).hexdigest())
    print('fixture publisher stdout');print('fixture publisher stderr',file=sys.stderr)
    sys.exit(int(os.environ.get('PUBLISH_EXIT','0')))
else: sys.exit(99)
''')
        uds.chmod(0o755)
        env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
               'PUBLISH_CALLS': str(root / 'calls.jsonl'), 'PUBLISH_ARCHIVE_HASH': str(root / 'archive.sha'),
               'DEV_PACKAGE_REPO': 'ghcr.io/example/ci-packages', 'FLAVOR': 'upstream'}
        arch = 'arm64' if os.uname().machine in ('aarch64', 'arm64') else 'amd64'
        archive = root / ('zarf-package-takserver-' + arch + '-dev-upstream.tar.zst')
        archive.write_bytes(b'already-created and architecture-checked fixture')
        return root, env, archive

    def test_existing_tag_skip_missing_archive_and_exact_upstream_retry_arguments(self):
        for case in ('exists', 'missing', 'publish'):
            with self.subTest(case=case):
                root, env, archive = self.fixture()
                key = subprocess.check_output(['bash', str(SCRIPT), 'key'], cwd=root, env=env).decode().strip()
                before = archive.read_bytes()
                if case == 'exists':
                    env['PUBLISH_EXISTS'] = 'true'
                    (root / '.github/scripts/publish-dev-package.py').unlink()
                    archive.unlink()
                elif case == 'missing':
                    archive.unlink()
                result = subprocess.run(['bash', str(SCRIPT), 'publish'], cwd=root, env=env,
                                        capture_output=True, timeout=10)
                calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
                publications = [call for call in calls if call[:3] == ['zarf', 'package', 'publish']]
                self.assertEqual(result.returncode, 1 if case == 'missing' else 0)
                self.assertEqual(len(publications), 1 if case == 'publish' else 0)
                self.assertFalse(any('create' in call or 'build' in call for call in calls))
                if case == 'publish':
                    self.assertEqual(publications[0], ['zarf', 'package', 'publish', archive.name,
                        'oci://ghcr.io/example/ci-packages', '--tag', key, '--retries', '3', '--confirm', '--no-progress'])
                    self.assertEqual(archive.read_bytes(), before)
                    self.assertEqual((root / 'archive.sha').read_text(), hashlib.sha256(before).hexdigest())
                    self.assertIn(b'fixture publisher stdout', result.stdout)
                    self.assertIn(b'fixture publisher stderr', result.stderr)

    def test_final_publication_failure_propagates_without_rebuild_or_outer_retry(self):
        root, env, archive = self.fixture()
        env['PUBLISH_EXIT'] = '17'
        before = archive.read_bytes()
        result = subprocess.run(['bash', str(SCRIPT), 'publish'], cwd=root, env=env,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 17)
        calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        self.assertEqual(len([call for call in calls if call[:3] == ['zarf', 'package', 'publish']]), 1)
        self.assertEqual(archive.read_bytes(), before)
        self.assertNotIn(b'dev-package: published', result.stdout)
        self.assertIn(b'fixture publisher stderr', result.stderr)

    def process_fixture(self, root):
        uds = root / 'uds'
        uds.write_text('#!' + sys.executable + '''
import os,pathlib,signal,subprocess,sys,time
signal.signal(signal.SIGTERM,signal.SIG_IGN)
child="import os,pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(os.environ['PUBLISH_CHILD_PID']).write_text(str(os.getpid()));time.sleep(30)"
subprocess.Popen([sys.executable,'-c',child])
deadline=time.monotonic()+3
while not pathlib.Path(os.environ['PUBLISH_CHILD_PID']).exists() and time.monotonic()<deadline: time.sleep(.01)
if os.environ.get('PUBLISH_MODE')=='failure': sys.exit(23)
time.sleep(30)
''')
        uds.chmod(0o755)
        return {'PATH': str(root) + os.pathsep + os.environ['PATH'], 'PUBLISH_CHILD_PID': str(root / 'child.pid')}

    def assert_child_stopped(self, root):
        pid = (root / 'child.pid').read_text()
        path = Path('/proc') / pid / 'stat'
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                if path.read_text().split(') ', 1)[1].split()[0] == 'Z':
                    return
            except (FileNotFoundError, ProcessLookupError):
                return
            time.sleep(.02)
        self.fail('owned publication descendant survived cleanup')

    def test_real_timeout_and_failed_parent_clean_owned_ignoring_descendants(self):
        self.assertEqual(PUBLISH.PUBLICATION_SECONDS, 1200)
        self.assertEqual(PUBLISH.TERMINATION_SECONDS, 10)
        for mode in ('timeout', 'failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                env = {**self.process_fixture(root), 'PUBLISH_MODE': mode}
                started = time.monotonic()
                with patch.dict(os.environ, env):
                    result = PUBLISH.publish('same-archive', 'same-reference', 'same-key', seconds=.5, grace=.1)
                self.assertEqual(result, 124 if mode == 'timeout' else 23)
                self.assertLess(time.monotonic() - started, 4)
                self.assert_child_stopped(root)

    def test_terminating_wrapper_also_cleans_its_owned_publisher_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {**os.environ, **self.process_fixture(root)}
            child = subprocess.Popen([sys.executable, str(PUBLISH_SCRIPT), 'archive', 'reference', 'key'],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 4
                while not (root / 'child.pid').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'child.pid').exists())
                child.terminate()
                child.communicate(timeout=3)
                self.assertEqual(child.returncode, 143)
                self.assert_child_stopped(root)
            finally:
                if child.poll() is None:
                    child.kill(); child.wait()


class PackageKeyTests(unittest.TestCase):
    def test_docs_site_non_markdown_changes_preserve_key_and_runtime_inputs_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True)
            git('init', '-q')
            tools = root / 'bin'
            tools.mkdir()
            uds = tools / 'uds'
            uds.write_text('#!/bin/sh\n[ "$*" = version ] || exit 99\necho fixture-cli\n')
            uds.chmod(0o755)
            env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}')
            def key():
                return subprocess.check_output(['bash', str(SCRIPT), 'key'], cwd=root, env=env, text=True).strip()
            runtime = ['zarf.yaml', 'common/zarf.yaml', 'charts/cloudtak/files/icon.svg',
                       'values/common-values.yaml', 'assets/icon.svg']
            site = ['docs-site/src/content/docs/example.mdx', 'docs-site/astro.config.mjs',
                    'docs-site/package.json', 'docs-site/pnpm-lock.yaml', 'docs-site/public/logo.svg']
            for name in runtime + site:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original\n')
            git('add', *runtime, *site)
            baseline = key()
            # Non-.md files are essential: Markdown was already excluded.
            for name in site:
                with self.subTest(site=name):
                    path = root / name
                    path.write_text('edited\n')
                    self.assertEqual(key(), baseline)
                    git('rm', '-f', name)
                    self.assertEqual(key(), baseline)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('original\n')
                    git('add', name)
            addition = root / 'docs-site/public/new-brand.png'
            addition.write_bytes(b'synthetic image fixture')
            git('add', str(addition.relative_to(root)))
            self.assertEqual(key(), baseline)
            for name in runtime:
                with self.subTest(runtime=name):
                    path = root / name
                    path.write_text('changed\n')
                    self.assertNotEqual(key(), baseline)
                    path.write_text('original\n')
            self.assertEqual(key(), baseline)

    def test_exact_lint_metadata_preserves_key_but_build_inputs_invalidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True)
            git('init', '-q')
            tools = root / 'bin'
            tools.mkdir()
            uds = tools / 'uds'
            uds.write_text('#!/bin/sh\n[ "$*" = version ] || exit 99\necho fixture-cli\n')
            uds.chmod(0o755)
            env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}')
            def key():
                return subprocess.check_output(['bash', str(SCRIPT), 'key'], cwd=root, env=env, text=True).strip()
            runtime = ['zarf.yaml', 'common/zarf.yaml', 'charts/takserver/templates/server.yaml',
                       'pepr/src/policies.ts', 'values/upstream-values.yaml', 'tasks.yaml',
                       'mise.toml', '.gitattributes', 'runtime-helper.sh',
                       'charts/takserver/hk.pkl']
            for name in runtime:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original\n')
            git('add', *runtime)
            baseline = key()
            for name in ['.codespellrc', '.license_config.yaml', 'hk.pkl']:
                with self.subTest(metadata=name):
                    path = root / name
                    path.write_text('original\n')
                    git('add', name)
                    self.assertEqual(key(), baseline, 'adding lint metadata')
                    path.write_text('changed\n')
                    self.assertEqual(key(), baseline, 'editing lint metadata')
                    git('rm', '-f', name)
                    self.assertEqual(key(), baseline, 'removing lint metadata')
            for name in runtime:
                with self.subTest(runtime=name):
                    path = root / name
                    path.write_text('changed\n')
                    self.assertNotEqual(key(), baseline)
                    path.write_text('original\n')
            self.assertEqual(key(), baseline)

    def test_optional_sources_preserve_runtime_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True)
            git('init', '-q')
            tools = root / 'bin'
            tools.mkdir()
            uds = tools / 'uds'
            uds.write_text('#!/bin/sh\n[ "$*" = version ] || exit 99\necho fixture-cli\n')
            uds.chmod(0o755)
            env = dict(os.environ, PATH=f'{tools}:{os.environ["PATH"]}')
            def key():
                return subprocess.check_output(['bash', str(SCRIPT), 'key'], cwd=root, env=env, text=True).strip()
            modules = root / '.gitmodules'
            modules.write_text('[submodule "upstream/takserver"]\n\tpath = upstream/takserver\n\turl = https://example.test/server\n[submodule "upstream/cloudtak"]\n\tpath = upstream/cloudtak\n\turl = https://example.test/cloud\n')
            for name in ['values.yaml', 'zarf.yaml', 'tasks.yaml']:
                (root / name).write_text('runtime: original\n')
            git('add', '.gitmodules', 'values.yaml', 'zarf.yaml', 'tasks.yaml')
            for name in ['takserver', 'cloudtak']:
                git('update-index', '--add', '--cacheinfo', f'160000,{"1" * 40},upstream/{name}')
            baseline = key()
            git('config', '-f', '.gitmodules', 'submodule.upstream/takx.path', 'upstream/takx')
            git('config', '-f', '.gitmodules', 'submodule.upstream/takx.url', 'https://github.com/TAK-Product-Center/TAKX.git')
            git('update-index', '--add', '--cacheinfo', f'160000,{"2" * 40},upstream/takx')
            (root / 'takx').mkdir()
            (root / 'takx/source.py').write_text('optional = True\n')
            git('add', '.gitmodules', 'takx')
            self.assertEqual(key(), baseline)
            for name in ['takserver', 'cloudtak']:
                git('update-index', '--cacheinfo', f'160000,{"3" * 40},upstream/{name}')
                self.assertNotEqual(key(), baseline, name)
                git('update-index', '--cacheinfo', f'160000,{"1" * 40},upstream/{name}')
            for name in ['takserver', 'cloudtak']:
                original = modules.read_text()
                git('config', '-f', '.gitmodules', f'submodule.upstream/{name}.url', 'https://example.test/changed')
                self.assertNotEqual(key(), baseline, name)
                modules.write_text(original)
            for name in ['values.yaml', 'zarf.yaml', 'tasks.yaml']:
                path = root / name
                path.write_text('runtime: changed\n')
                self.assertNotEqual(key(), baseline, name)
                path.write_text('runtime: original\n')
            self.assertEqual(key(), baseline)


if __name__ == '__main__':
    unittest.main()
