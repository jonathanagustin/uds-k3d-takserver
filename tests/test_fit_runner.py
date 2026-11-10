# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run the real CI fit script against an explicit fake Kubernetes command."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FitRunnerTests(unittest.TestCase):
    def run_fit(self, replicas=None, second_unready=False, agent_missing=False):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            calls = directory / 'calls.jsonl'
            command = directory / 'kubectl'
            command.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
args=sys.argv[1:]
with open(os.environ['FIT_CALLS'],'a') as stream: stream.write(json.dumps(args)+'\\n')
if args[:2]==['get','deploy'] and 'agent-hook' in args and os.environ.get('FIT_MISSING')=='true': raise SystemExit(1)
if args[:3]==['rollout','status','deploy/agent-hook'] and os.environ.get('FIT_UNREADY')=='true': raise SystemExit(1)
if args[:2]==['describe','node']: print('Allocated resources:\\nEvents:')
''')
            command.chmod(0o755)
            k3d = directory / 'k3d'
            k3d.write_text('#!/usr/bin/env bash\nexit 0\n')
            k3d.chmod(0o755)
            env = {**os.environ, 'PATH': str(directory) + os.pathsep + os.defpath, 'FIT_CALLS': str(calls),
                   'FIT_UNREADY': str(second_unready).lower(), 'FIT_MISSING': str(agent_missing).lower()}
            env.pop('CI_AGENT_REPLICAS', None)
            if replicas is not None:
                env['CI_AGENT_REPLICAS'] = replicas
            result = subprocess.run(['bash', str(ROOT / '.github/scripts/fit-runner.sh')], env=env,
                                    text=True, capture_output=True, timeout=10)
            recorded = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, recorded

    def test_default_two_and_explicit_choices_preserve_rollout_checks(self):
        for choice, expected in ((None, '2'), ('1', '1'), ('2', '2')):
            result, calls = self.run_fit(choice)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(['scale', 'deploy/agent-hook', '-n', 'zarf', '--replicas=' + expected], calls)
            self.assertIn(['rollout', 'status', 'deploy/agent-hook', '-n', 'zarf', '--timeout=180s'], calls)

    def test_malformed_choice_refused_before_any_cluster_command(self):
        for choice in ('', '0', '3', '2 ', 'two', '2;true'):
            result, calls = self.run_fit(choice)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(calls)

    def test_two_replica_selection_requires_existing_agent_deployment(self):
        result, calls = self.run_fit('2', agent_missing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(args[:2] == ['describe', 'node'] for args in calls))

    def test_second_replica_not_ready_still_fails_real_script(self):
        result, calls = self.run_fit('2', second_unready=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(args[:3] == ['rollout', 'status', 'deploy/agent-hook'] for args in calls), 1)
        self.assertFalse(any(args[:2] == ['describe', 'node'] for args in calls))


if __name__ == '__main__':
    unittest.main()
