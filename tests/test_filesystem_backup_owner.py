# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Render the ownership staging gate without transferring any live objects."""
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(enabled, owner=None):
    args = ["helm", "template", "takserver", "charts/takserver", "--namespace", "takserver",
            "--set-string", f"backup.filesystem.enabled={str(enabled).lower()}"]
    if owner is not None:
        args += ["--set-string", f"backup.filesystem.owner={owner}"]
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True)


def documents(enabled, owner=None):
    result = render(enabled, owner)
    if result.returncode:
        raise AssertionError(result.stderr)
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    # Offline Helm intentionally creates a fresh keystore password each render.
    # Normalize only that unrelated random field for whole-chart comparisons.
    for doc in docs:
        if doc['kind'] == 'Secret' and doc['metadata']['name'] == 'takserver-keystore':
            doc['stringData'] = {'CAPASS': '<generated>', 'PASS': '<generated>'}
    return docs


def agent_resources(docs):
    return {(doc['kind'], doc['metadata']['name']): doc for doc in docs
            if doc['metadata'].get('namespace') == 'velero'}


class FilesystemBackupOwnerTests(unittest.TestCase):
    def test_default_matches_explicit_local_without_changing_other_resources(self):
        self.assertEqual(documents(True), documents(True, 'local'))
        resources = agent_resources(documents(True))
        self.assertIn(('DaemonSet', 'node-agent'), resources)
        config = resources[('ConfigMap', 'node-agent-config')]
        self.assertIn('"privilegedFsBackup": true', config['data']['node-agent-config.json'])
        agent = resources[('DaemonSet', 'node-agent')]['spec']['template']['spec']
        self.assertEqual(agent['serviceAccountName'], 'velero-server')
        self.assertTrue(agent['containers'][0]['securityContext']['privileged'])

    def test_core_omits_only_local_agent_and_configuration(self):
        local = documents(True, 'local')
        core = documents(True, 'core')
        expected = [doc for doc in local if not (
            doc['metadata'].get('namespace') == 'velero' and
            (doc['kind'], doc['metadata']['name']) in
            {('DaemonSet', 'node-agent'), ('ConfigMap', 'node-agent-config')})]
        self.assertEqual(core, expected)
        self.assertEqual(agent_resources(core), {})
        self.assertTrue(any(doc['kind'] == 'Exemption' and
                            doc['metadata']['name'] == 'velero-node-agent' for doc in core))

    def test_disabled_owner_never_renders_agent_or_exemption(self):
        for owner in ('local', 'core'):
            with self.subTest(owner=owner):
                docs = documents(False, owner)
                self.assertEqual(agent_resources(docs), {})
                self.assertFalse(any(doc['kind'] == 'Exemption' and
                                     doc['metadata']['name'] == 'velero-node-agent' for doc in docs))

    def test_invalid_owner_fails_even_when_filesystem_backup_is_disabled(self):
        for enabled in (True, False):
            for owner in ('', 'other', 'LOCAL', 'false'):
                with self.subTest(enabled=enabled, owner=owner):
                    result = render(enabled, owner)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('backup.filesystem.owner must be local or core', result.stderr)


if __name__ == '__main__':
    unittest.main()
