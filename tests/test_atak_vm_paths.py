# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""VM workflow consumption contracts; no Docker, VM, registry or hosted run."""
import copy
from pathlib import Path
import re
import shlex
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = '.github/workflows/atak-vm.yaml'


def workflow():
    # BaseLoader preserves the GitHub Actions `on` key under YAML 1.1 readers.
    return yaml.load((ROOT / WORKFLOW).read_text(), Loader=yaml.BaseLoader)


def triggered(path, patterns):
    """The contract deliberately permits only exact paths and directory/**."""
    for pattern in patterns:
        if pattern.endswith('/**'):
            if path.startswith(pattern[:-2]):
                return True
        elif any(character in pattern for character in '*?![]{}'):
            raise ValueError('Review unsupported path-filter pattern: ' + pattern)
        elif path == pattern:
            return True
    return False


def repository_references(text, owner):
    # Ignore prose/examples in comments; inspect actual shell/Docker bodies.
    body = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    result = set(re.findall(r'(?<![\w/])((?:atak/|\.github/scripts/)[A-Za-z0-9_./-]+)', body))
    result.update(re.findall(r'(?<![\w/.])\./([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)', body))
    for relative in re.findall(r'\$\{here\}/([A-Za-z0-9_.-]+)', body):
        result.add(str(Path(owner).parent / relative))
    return result


def consumed_inputs(document):
    """Inspect checked-in run paths and transitive Docker COPY/local helpers.

    This is a deliberately constrained source guard, not a general shell parser.
    Dynamic/glob Docker inputs require explicit review instead of silent admission.
    """
    pending = {WORKFLOW}
    for step in document['jobs']['vm']['steps']:
        pending.update(repository_references(step.get('run', ''), WORKFLOW))
    result = {'.dockerignore'}  # Creation/changes affect both root build contexts.
    while pending:
        name = pending.pop()
        if name in result:
            continue
        path = ROOT / name
        if not path.is_file():
            raise ValueError('New consumed repository input must be reviewed: ' + name)
        result.add(name)
        if name == WORKFLOW:
            continue
        text = path.read_text()
        pending.update(repository_references(text, name) - result)
        if path.name == 'Dockerfile':
            for line in text.replace('\\\n', ' ').splitlines():
                if not re.match(r'^\s*(COPY|ADD)\s', line):
                    continue
                words = shlex.split(line, comments=True)
                if not words or words[0] not in ('COPY', 'ADD'):
                    continue
                if any(word.startswith('--from=') for word in words[1:]):
                    continue  # Earlier stages, not repository files.
                inputs = [word for word in words[1:] if not word.startswith('--')][:-1]
                if not inputs or any(any(c in word for c in '$*?[]{}') for word in inputs):
                    raise ValueError('Review dynamic Docker context inputs')
                pending.update(word for word in inputs if not re.match(r'https?://', word))
    return result


def require_covered(document, patterns):
    missing = sorted(name for name in consumed_inputs(document) if not triggered(name, patterns))
    if missing:
        raise ValueError('Unfiltered VM consumer inputs: ' + ', '.join(missing))


class VmPaths(unittest.TestCase):
    def setUp(self):
        self.document = workflow()
        self.patterns = self.document['on']['pull_request']['paths']

    def test_all_actual_workflow_docker_and_smoke_inputs_are_covered(self):
        require_covered(self.document, self.patterns)
        actual = consumed_inputs(self.document)
        self.assertTrue({'atak/vm/build-disk.sh', 'atak/viewer/phone.html',
                         'atak/viewer/entrypoint.sh', 'atak/deploy/kubevirt-cr.yaml',
                         'atak/ci/vm-smoke.sh', 'atak/ci/viewer-smoke.sh',
                         '.github/scripts/redact-then-filter.sh',
                         '.github/scripts/redact-logs.py'} <= actual)

    def test_scenario_peer_and_reuse_changes_do_not_boot_an_unrelated_vm(self):
        for name in ['atak/ci/interoperability.py', 'atak/ci/interoperability.sh',
                     'atak/ci/cleanup-scenario.py', 'atak/ci/reverse-marker.py',
                     'atak/ci/push-reuse.py', 'atak/ci/e2e.sh',
                     'atak/scenarios/android-ui.py', 'atak/scenarios/observe-peer.py',
                     'atak/scenarios/android-interoperability.py', 'atak/scenarios/README.md']:
            with self.subTest(path=name):
                self.assertFalse(triggered(name, self.patterns))

    def test_vm_viewer_deploy_and_smoke_changes_always_trigger(self):
        for name in ['atak/vm/Dockerfile', 'atak/vm/build-disk.sh', 'atak/vm/new-boot-input',
                     'atak/viewer/Dockerfile', 'atak/viewer/new-render-input',
                     'atak/deploy/kubevirt-cr.yaml', 'atak/deploy/new-vm-setting.yaml',
                     'atak/ci/vm-smoke.sh', 'atak/ci/viewer-smoke.sh', WORKFLOW,
                     '.dockerignore', '.github/scripts/redact-then-filter.sh',
                     '.github/scripts/redact-logs.py']:
            with self.subTest(path=name):
                self.assertTrue(triggered(name, self.patterns))

    def test_future_actual_helper_consumption_fails_closed_until_filter_review(self):
        changed = copy.deepcopy(self.document)
        changed['jobs']['vm']['steps'].append({'run': './atak/ci/e2e.sh'})
        # This existing, currently unrelated helper would become a VM input.
        # Its omitted path must be caught when a caller starts consuming it.
        with self.assertRaisesRegex(ValueError, 'New consumed|Unfiltered'):
            require_covered(changed, self.patterns)

    def test_missing_existing_helper_or_docker_input_filter_is_rejected(self):
        for pattern in ['atak/vm/**', 'atak/viewer/**', 'atak/deploy/**',
                        'atak/ci/vm-smoke.sh', 'atak/ci/viewer-smoke.sh',
                        '.github/scripts/redact-logs.py']:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, 'Unfiltered'):
                require_covered(self.document, [p for p in self.patterns if p != pattern])

    def test_manual_smoke_remains_available(self):
        self.assertIn('workflow_dispatch', self.document['on'])
        self.assertNotIn('push', self.document['on'])
        self.assertEqual(self.document['jobs']['vm']['timeout-minutes'], '60')


if __name__ == '__main__':
    unittest.main()
