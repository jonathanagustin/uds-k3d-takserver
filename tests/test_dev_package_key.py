#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real package key without building a package."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/dev-package.sh'


class PackageKeyTests(unittest.TestCase):
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
