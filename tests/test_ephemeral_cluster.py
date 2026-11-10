# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline guard fixtures; no Docker, Kubernetes, or cluster mutation is run."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('ephemeral_cluster', Path(__file__).with_name('ephemeral-cluster.py'))
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)
ENV = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': GUARD.REPOSITORY, 'GITHUB_RUN_ID': '123',
       'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40}
UID = '11111111-2222-3333-4444-555555555555'


class Fixture:
    def __init__(self):
        self.context, self.server, self.uid = GUARD.CONTEXT, 'https://127.0.0.1:6444', UID
        self.local_uid, self.sha = UID, ENV['GITHUB_SHA']
        self.nodes = {GUARD.NODE: {'id': 'b' * 64, 'running': True,
                     'labels': {'app': 'k3d', 'k3d.cluster': 'uds'}, 'ports': {}},
                      GUARD.GATEWAY: {'id': 'c' * 64, 'running': True,
                     'labels': {'app': 'k3d', 'k3d.cluster': 'uds'}, 'ports': {'6443/tcp': [{'HostPort': '6444'}]}}}
        self.marker, self.writes = None, []

    def command(self, argv, input_text=None):
        if argv[:3] == ['git', 'rev-parse', 'HEAD']:
            return self.sha
        if argv == ['kubectl', 'config', 'current-context']:
            return self.context
        if argv[:1] == ['docker']:
            if argv[1] == 'ps':
                return '\n'.join(self.nodes)
            if argv[1] == 'inspect':
                self.assert_safe_format(argv[-1])
                return json.dumps(self.nodes[argv[2]])
            if argv[1] == 'exec':
                return self.local_uid
        if 'config' in argv and 'view' in argv:
            return self.server
        if argv[3:6] == ['get', 'namespace', 'kube-system']:
            return json.dumps({'metadata': {'uid': self.uid}})
        if argv[3:6] == ['get', 'configmap', GUARD.MARKER]:
            return json.dumps(self.marker) if self.marker else ''
        if argv[3:5] == ['create', '-f']:
            if self.marker:
                raise ValueError('must not replace marker')
            self.writes.append(copy.deepcopy(argv))
            self.marker = json.loads(input_text)
            self.marker['metadata'].update(uid='marker-uid', resourceVersion='1')
            return json.dumps(self.marker)
        raise AssertionError(argv)

    @staticmethod
    def assert_safe_format(value):
        if '.Env' in value or '.Mounts' in value:
            raise AssertionError('sensitive Docker inspection')


class EphemeralClusterTests(unittest.TestCase):
    def test_explicit_marker_creation_is_idempotent_and_verification_is_read_only(self):
        fixture = Fixture()
        with patch.dict('os.environ', ENV, clear=True):
            first = GUARD.mark(GUARD.CONTEXT, fixture.command)
            second = GUARD.mark(GUARD.CONTEXT, fixture.command)
            self.assertEqual(first, second)
            self.assertEqual(first['clusterUID'], UID)
            self.assertEqual(first['nodeContainerID'], 'b' * 64)
            self.assertEqual(len(fixture.writes), 1)
            self.assertEqual(GUARD.verify(GUARD.CONTEXT, fixture.command), first)
            self.assertEqual(len(fixture.writes), 1)

    def test_missing_or_foreign_run_source_and_context_are_rejected_before_creation(self):
        for changed in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_REPOSITORY': 'other/repo'},
                        {'GITHUB_RUN_ID': ''}, {'GITHUB_RUN_ATTEMPT': '0'}, {'GITHUB_SHA': 'not-a-sha'}):
            fixture = Fixture()
            with patch.dict('os.environ', {**ENV, **changed}, clear=True), self.assertRaises(ValueError):
                GUARD.mark(GUARD.CONTEXT, fixture.command)
            self.assertFalse(fixture.writes)
        fixture = Fixture()
        with patch.dict('os.environ', ENV, clear=True):
            with self.assertRaises(ValueError):
                GUARD.mark('production', fixture.command)
            fixture.sha = 'd' * 40
            with self.assertRaises(ValueError):
                GUARD.mark(GUARD.CONTEXT, fixture.command)
        self.assertFalse(fixture.writes)

    def test_remote_endpoint_wrong_port_node_and_cluster_identity_are_rejected(self):
        changes = [lambda f: setattr(f, 'server', 'https://production.example:6444'),
                   lambda f: setattr(f, 'server', 'http://127.0.0.1:6444'),
                   lambda f: setattr(f, 'server', 'https://127.0.0.1:9999'),
                   lambda f: setattr(f, 'local_uid', 'another-cluster'),
                   lambda f: setattr(f, 'context', 'another-context'),
                   lambda f: f.nodes[GUARD.NODE].update(running=False),
                   lambda f: f.nodes[GUARD.NODE]['labels'].update({'k3d.cluster': 'production'})]
        for change in changes:
            fixture = Fixture()
            change(fixture)
            with patch.dict('os.environ', ENV, clear=True), self.assertRaises(ValueError):
                GUARD.mark(GUARD.CONTEXT, fixture.command)
            self.assertFalse(fixture.writes)

    def test_verify_requires_same_nonterminating_marker_and_never_overwrites(self):
        fixture = Fixture()
        with patch.dict('os.environ', ENV, clear=True):
            with self.assertRaises(ValueError):
                GUARD.verify(GUARD.CONTEXT, fixture.command)
            GUARD.mark(GUARD.CONTEXT, fixture.command)
            original = copy.deepcopy(fixture.marker)
            for change in (lambda value: value['data'].update(runID='old'),
                           lambda value: value['data'].update(sourceSHA='d' * 40),
                           lambda value: value['data'].update(clusterUID='another'),
                           lambda value: value['metadata'].update(deletionTimestamp='now')):
                fixture.marker = copy.deepcopy(original)
                change(fixture.marker)
                with self.assertRaises(ValueError):
                    GUARD.mark(GUARD.CONTEXT, fixture.command)
                with self.assertRaises(ValueError):
                    GUARD.verify(GUARD.CONTEXT, fixture.command)
            self.assertEqual(len(fixture.writes), 1)


if __name__ == '__main__':
    unittest.main()
