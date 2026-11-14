#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Skip only package rendering after complete, verified non-runtime Git evidence."""
import argparse
from enum import Enum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

CLASSIFIER = '.github/scripts/runtime-paths.sh'
WORKFLOW = '.github/workflows/unit-tests.yaml'
GATE_DIRECTORY = '.github/test-infra/package-render/'
FORCE_FILES = {WORKFLOW, CLASSIFIER, 'tests/test_runtime_paths.sh',
    'tests/test_package_values.py', 'tests/test_agent_gate.py', 'tests/test_workflow_permissions.py',
    'tests/test_scorecard_permissions.py', 'tests/test_trust_bundle.py', 'tests/test_expose_annotations.py',
    'tests/test_workload_identities.py', 'tests/test_filesystem_backup_owner.py', 'tests/test_velero_handoff.py', 'tests/test_velero_clean_completion.py',
    'tests/test_ephemeral_cluster.py', 'tests/test_velero_transfer.py', 'tests/test_velero_trial.py',
    'tests/test_staged_migrations.py', 'tests/test_upgrade_agent_watch.py', 'tests/test_identity_rollout_driver.py',
    'tests/test_package_identity_driver.py',
    'tests/test_identity_cleanup_evidence.py', 'tests/test_identity_phase_evidence.py', 'tests/test_identity_public_evidence.py', 'tests/test_identity_retained_state.py', 'tests/test_identity_render_inputs.py', 'tests/test_identity_failure_evidence.py'}
MAX_BYTES = 2 * 1024 * 1024


class Reason(Enum):
    UNKNOWN = 'unclassified-unavailable'
    EVENT = 'event-unavailable'
    IDENTITY = 'identity-unavailable'
    REPOSITORY = 'repository-mismatch'
    CHECKOUT = 'checkout-mismatch'
    REF = 'ref-mismatch'
    COMMIT = 'commit-unavailable'
    PARENTS = 'merge-parents-mismatch'
    GIT = 'git-evidence-unavailable'
    PATHS = 'changed-paths-unavailable'
    CLASSIFIER = 'classifier-unavailable'


class EvidenceUnavailable(Exception):
    """Unusable optimization evidence always retains rendering."""

    def __init__(self, reason=Reason.IDENTITY):
        self.reason = reason if isinstance(reason, Reason) else Reason.IDENTITY
        super().__init__()


def git(repo, *arguments):
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0')
    try:
        result = subprocess.run(['git', '--no-replace-objects', '-C', str(repo), *arguments],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=20, check=True, env=env)
    except (OSError, subprocess.SubprocessError):
        raise EvidenceUnavailable(Reason.GIT) from None
    if len(result.stdout) > MAX_BYTES:
        raise EvidenceUnavailable(Reason.GIT)
    return result.stdout


def commit(repo, value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value) or value == '0' * 40:
        raise EvidenceUnavailable(Reason.COMMIT)
    if git(repo, 'cat-file', '-t', value) != b'commit\n':
        raise EvidenceUnavailable(Reason.COMMIT)
    if git(repo, 'rev-parse', '--verify', value).decode().strip() != value:
        raise EvidenceUnavailable(Reason.COMMIT)
    return value


def identities(repo, event, env):
    if event['repository']['full_name'] != env['GITHUB_REPOSITORY']:
        raise EvidenceUnavailable(Reason.REPOSITORY)
    actual = git(repo, 'rev-parse', '--verify', 'HEAD').decode().strip()
    checkout = commit(repo, env['GITHUB_SHA'])
    if actual != checkout or Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != repo:
        raise EvidenceUnavailable(Reason.CHECKOUT)
    if env['GITHUB_EVENT_NAME'] == 'push':
        if event['ref'] != env['GITHUB_REF'] or not event['ref'].startswith('refs/heads/'):
            raise EvidenceUnavailable(Reason.REF)
        base, head = commit(repo, event['before']), commit(repo, event['after'])
        if head != checkout:
            raise EvidenceUnavailable(Reason.CHECKOUT)
    elif env['GITHUB_EVENT_NAME'] == 'pull_request':
        number = event['number']
        if type(number) is not int or number <= 0 or env['GITHUB_REF'] != f'refs/pull/{number}/merge':
            raise EvidenceUnavailable(Reason.REF)
        request = event['pull_request']
        base, head = commit(repo, request['base']['sha']), commit(repo, request['head']['sha'])
        # GITHUB_SHA identifies the checked-out PR merge. The nullable cached
        # event merge_commit_sha is not authoritative and is deliberately ignored.
        parents = git(repo, 'show', '--no-patch', '--format=%P', checkout).decode().strip().split()
        if parents != [base, head]:
            raise EvidenceUnavailable(Reason.PARENTS)
    else:
        raise EvidenceUnavailable(Reason.IDENTITY)
    return base, head, checkout


def valid_path(raw):
    path = raw.decode('utf-8')
    if (not path or len(raw) > 4096 or path.startswith('/') or '\\' in path or
            any(part in ('', '.', '..') for part in path.split('/')) or
            any(unicodedata.category(char).startswith('C') for char in path)):
        raise EvidenceUnavailable(Reason.PATHS)
    return path


def changed_paths(data):
    if not data or len(data) > MAX_BYTES or not data.endswith(b'\0'):
        raise EvidenceUnavailable(Reason.PATHS)
    fields = data[:-1].split(b'\0')
    paths, index = [], 0
    while index < len(fields):
        status = fields[index].decode('ascii')
        index += 1
        if status in ('A', 'M', 'D', 'T'):
            count = 1
        elif re.fullmatch('[RC][0-9]{1,3}', status) and int(status[1:]) <= 100:
            count = 2
        else:
            raise EvidenceUnavailable(Reason.PATHS)
        if index + count > len(fields):
            raise EvidenceUnavailable(Reason.PATHS)
        paths.extend(valid_path(value) for value in fields[index:index + count])
        index += count
        if len(paths) > 10000:
            raise EvidenceUnavailable(Reason.PATHS)
    if not paths:
        raise EvidenceUnavailable(Reason.PATHS)
    return paths


def decision(repo, event, env):
    base, head, checkout = identities(repo, event, env)
    paths = []
    # Include source changes even if the merge reverts them, and merge-only
    # changes even when the source diff contains only documentation.
    for target in dict.fromkeys((head, checkout)):
        paths.extend(changed_paths(git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z',
                                       '--find-renames', base, target, '--')))
        if len(paths) > 10000:
            raise EvidenceUnavailable(Reason.PATHS)
    paths = sorted(set(paths))
    if any(path in FORCE_FILES or path.startswith(GATE_DIRECTORY) for path in paths):
        return True, 'gate or validation inputs changed'
    classifier = repo / CLASSIFIER
    if classifier.is_symlink() or not classifier.is_file() or classifier.read_bytes() != git(repo, 'show', checkout + ':' + CLASSIFIER):
        raise EvidenceUnavailable(Reason.CLASSIFIER)
    changed = '\n'.join(paths)
    if len(changed.encode()) > 64000:
        raise EvidenceUnavailable(Reason.CLASSIFIER)
    child_env = {**env, 'CHANGED': changed}
    child_env.pop('GITHUB_OUTPUT', None)
    try:
        result = subprocess.run(['bash', str(classifier), 'decide'], cwd=repo, env=child_env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=20, check=True)
    except (OSError, subprocess.SubprocessError):
        raise EvidenceUnavailable(Reason.CLASSIFIER) from None
    if result.stdout == b'runtime=false\n':
        return False, 'verified non-runtime paths'
    if result.stdout == b'runtime=true\n':
        return True, 'runtime paths changed'
    raise EvidenceUnavailable(Reason.CLASSIFIER)


def evaluate(repo, event_path, env):
    try:
        path = Path(event_path)
        if path.stat().st_size > MAX_BYTES:
            raise EvidenceUnavailable(Reason.EVENT)
        event = json.loads(path.read_text())
        return decision(repo.resolve(), event, env)
    except EvidenceUnavailable as error:
        return True, 'evidence unavailable; rendering retained [' + error.reason.value + ']'
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return True, 'evidence unavailable; rendering retained [' + Reason.UNKNOWN.value + ']'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    render, reason = evaluate(args.repo, os.environ.get('GITHUB_EVENT_PATH', ''), os.environ)
    line = 'render=' + str(render).lower() + '\n'
    if os.environ.get('GITHUB_OUTPUT'):
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
            output.write(line)
    else:
        sys.stdout.write(line)
    print('package-render: ' + reason, file=sys.stderr)


if __name__ == '__main__':
    main()
