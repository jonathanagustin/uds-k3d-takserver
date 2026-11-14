# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import re
import unittest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('render_gate_wiring', HERE / 'decide.py')
GATE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GATE)


class WorkflowWiringTests(unittest.TestCase):
    def test_runner_and_agent_failure_fixtures_are_unconditional(self):
        document = yaml.safe_load((ROOT / GATE.WORKFLOW).read_text())
        step = next(step for step in document['jobs']['coverage']['steps']
                    if step.get('name') == 'Profiles, benchmark harness, and Full Core summary')
        self.assertNotIn('if', step)
        modules = set(re.findall(r'tests\.test_[A-Za-z_]+', step['run']))
        self.assertTrue({'tests.test_runner_wedge_probe', 'tests.test_runner_wedge_kernel',
                         'tests.test_upgrade_agent_diagnostics', 'tests.test_upgrade_agent_api_snapshot'} <= modules)

    def test_only_pepr_and_real_render_class_are_conditional(self):
        document = yaml.safe_load((ROOT / GATE.WORKFLOW).read_text())
        steps = document['jobs']['package-values']['steps']
        by_name = {step['name']: step for step in steps}
        gated = {step['name'] for step in steps if 'if' in step}
        self.assertEqual(gated, {'Build the Pepr chart', 'Package values follow the variables'})
        expected = "steps.package_render.outcome != 'success' || steps.package_render.outputs.render != 'false'"
        for name in gated:
            self.assertEqual(by_name[name]['if'], expected)
        self.assertEqual(by_name['Checkout']['with']['fetch-depth'], 2)
        gate = next(step for step in steps if step.get('id') == 'package_render')
        self.assertTrue(gate['continue-on-error'])
        self.assertIn(GATE.GATE_DIRECTORY + 'decide.py', gate['run'])
        self.assertLess(steps.index(gate), steps.index(by_name['Build the Pepr chart']))
        self.assertIn('aqua:defenseunicorns/uds-cli', by_name['Install Node, uv, Helm, and UDS CLI']['with']['install_args'])
        self.assertEqual(by_name['Native upgrade admission gate contracts']['run'], 'python3 -B -m unittest tests.test_agent_gate -v')
        render = by_name['Package values follow the variables']['run']
        self.assertIn('tests.test_package_values.PackageValuesTests', render)
        safety = by_name['Package policy and safety contracts']
        self.assertNotIn('if', safety)
        self.assertLess(steps.index(safety), steps.index(by_name['Build the Pepr chart']))
        expected_modules = {'tests.test_workflow_permissions', 'tests.test_scorecard_permissions',
            'tests.test_package_values.RenderFailureTests', 'tests.test_trust_bundle',
            'tests.test_expose_annotations', 'tests.test_workload_identities', 'tests.test_filesystem_backup_owner',
            'tests.test_velero_handoff', 'tests.test_velero_clean_completion', 'tests.test_ephemeral_cluster', 'tests.test_velero_transfer',
            'tests.test_velero_trial', 'tests.test_staged_migrations', 'tests.test_upgrade_agent_watch',
            'tests.test_identity_rollout_driver',
            'tests.test_package_identity_driver', 'tests.test_identity_cleanup_evidence', 'tests.test_identity_phase_evidence', 'tests.test_identity_public_evidence', 'tests.test_identity_retained_state', 'tests.test_identity_render_inputs', 'tests.test_identity_failure_evidence'}
        modules = set(re.findall(r'tests\.test_[A-Za-z_]+(?:\.[A-Za-z]+)?', safety['run']))
        self.assertEqual(modules, expected_modules)
        for module in modules:
            self.assertIn(module.split('.')[1] + '.py', {Path(path).name for path in GATE.FORCE_FILES})
        coverage = document['jobs']['coverage']['steps']
        guard = next(step for step in coverage if step['name'] == 'Package rendering evidence and wiring')
        self.assertNotIn('if', guard)
        self.assertIn(GATE.GATE_DIRECTORY.rstrip('/'), guard['run'])


if __name__ == '__main__':
    unittest.main()
