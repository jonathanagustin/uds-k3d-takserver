#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Manual-only staged trial selection and sanitized fail-closed receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import datetime

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {'velero': ['velero'], 'identities': ['identities'], 'all': ['velero', 'identities']}
REVERSE_STEPS = ['prepare-local-config', 'detach-core-agent-retain-config', 'transfer-to-local',
                 'deploy-local-agent', 'wait-local-agent', 'retire-core-config']
OWNER_STEPS = (['bootstrap-exemption', 'fresh-core-agent', 'fresh-core-app', 'wait-fresh-agent', 'prepare-api-user', 'prepare-api-group', 'prepare-api-gateway', 'fresh-ready', 'fresh-acceptance']
               + REVERSE_STEPS + ['local-before', 'protect-local-agent', 'transfer-to-core', 'deploy-core-agent',
                                  'detach-local-agent', 'wait-core-agent', 'core-ready', 'core-acceptance']
               + REVERSE_STEPS + ['local-ready', 'local-acceptance'])
ARCHES = {'amd64': ['amd64'], 'arm64': ['arm64'], 'both': ['amd64', 'arm64']}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def selection():
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_REF') == 'refs/heads/main'
            and os.environ.get('GITHUB_REPOSITORY') == 'jonathanagustin/uds-takserver',
            'staged trials require manual dispatch from this repository main')
    scenario, architecture = os.environ.get('SCENARIO', ''), os.environ.get('ARCHITECTURE', '')
    require(scenario in SCENARIOS and architecture in ARCHES, 'invalid staged selection')
    return SCENARIOS[scenario], ARCHES[architecture]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt(directory, arch):
    scenarios, arches = selection()
    require(arch in arches and {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine()) == arch,
            'trial must run on its selected native architecture')
    result = {'schema': 1, 'sourceSHA': os.environ['GITHUB_SHA'], 'runID': os.environ['GITHUB_RUN_ID'],
              'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'], 'architecture': arch,
              'scenarios': scenarios, 'results': {}, 'proofHashes': {}, 'accepted': True}
    guard = None
    for scenario in scenarios:
        if scenario == 'velero':
            journal_path = directory / 'owner/journal.json'
            journal = bounded_json(journal_path)
            require(journal.get('schema') == 1 and journal.get('accepted') is True
                    and not journal.get('recoveryOnly') and not journal.get('baselineOnly')
                    and journal.get('driverSHA256') == sha(ROOT / 'tests/velero-ownership/drive.py')
                    and [step.get('name') for step in journal['steps']] == OWNER_STEPS
                    and all(step.get('status') == 'passed' for step in journal['steps']), 'owner round-trip not accepted')
            guard = journal['cluster']
            for group, stage in [('fresh', 'fresh-core'), ('handoff', 'core-after'), ('handoff', 'local-after')]:
                path = directory / 'owner' / group / (stage + '.json')
                proof = bounded_json(path)
                require(proof.get('stage') == stage and proof.get('backupRestore') is True
                        and proof.get('observerSHA256') == sha(ROOT / 'tests/velero-ownership/observe.py')
                        and proof.get('clusterUID') == guard['clusterUID']
                        and proof.get('daemonsetUID') == journal['daemonsetUID']
                        and (stage != 'local-after' or proof.get('retiredCoreConfigAbsent') is True), 'missing same-cluster owner acceptance')
                result['proofHashes'][stage] = sha(path)
        else:
            journal_path = directory / 'identity/journal.json'
            journal = bounded_json(journal_path)
            require(journal.get('schema') == 1 and journal.get('completed') is True
                    and journal.get('accepted') is True and journal.get('recoveryOnly') is False
                    and journal.get('scenario') == 'identities' and journal.get('architecture') == arch
                    and journal.get('driverSHA256') == sha(ROOT / 'tests/workload-identities/drive.py')
                    and journal.get('probeSourceSHA256') == sha(ROOT / 'tests/workload-identities/ProtocolProbe.java'),
                    'identity trial or restored baseline is incomplete')
            stages = {entry['stage'] for entry in journal['stages']}
            require({'traffic-baseline', 'traffic-dual-before-rollout', 'traffic-transition', 'traffic-strict',
                     'traffic-rollback', 'traffic-shared', 'reversed-and-verified'}.issubset(stages)
                    and 'stopped' not in stages, 'identity acceptance is missing a required phase')
            require(guard is None or guard == journal['guard'], 'scenario cluster/run receipts differ')
            guard = journal['guard']
        require(guard['sourceSHA'] == result['sourceSHA'] and guard['runID'] == result['runID']
                and guard['runAttempt'] == result['runAttempt'], 'scenario source/run differs')
        result['proofHashes'][scenario + '-journal'] = sha(journal_path)
        result['results'][scenario] = 'passed'
    result['clusterUID'] = guard['clusterUID']
    return result


def verify(directory):
    scenarios, arches = selection()
    paths = list(directory.glob('*.json'))
    require({p.stem for p in paths} == set(arches), 'missing or unexpected architecture receipt')
    for arch in arches:
        value = json.loads((directory / (arch + '.json')).read_text())
        require(value.get('schema') == 1 and value.get('architecture') == arch
                and value.get('sourceSHA') == os.environ['GITHUB_SHA']
                and value.get('runID') == os.environ['GITHUB_RUN_ID']
                and value.get('runAttempt') == os.environ['GITHUB_RUN_ATTEMPT']
                and value.get('accepted') is True
                and value.get('scenarios') == scenarios
                and value.get('results') == {scenario: 'passed' for scenario in scenarios},
                'selected architecture/scenario lacks exact-run acceptance')
    return {'selectedArchitectures': arches, 'selectedScenarios': scenarios, 'accepted': True}


def bounded_json(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 * 1024,
            'proof is absent or exceeds bounded JSON size')
    return json.loads(path.read_text())


def sanitize_observer(proof, stage):
    require(proof.get('schema') == 1 and proof.get('stage') == stage, 'wrong observer schema/stage')
    result = {'schema': 1, 'stage': stage}
    for key, pattern in [('observerSHA256', '[a-f0-9]{64}'), ('clusterUID', '[a-f0-9-]{36}'),
                         ('daemonsetUID', '[a-f0-9-]{36}')]:
        require(isinstance(proof.get(key), str) and re.fullmatch(pattern, proof[key]), 'invalid proof identity')
        result[key] = proof[key]
    datetime.datetime.fromisoformat(proof['observedAt'].replace('Z', '+00:00'))
    result['observedAt'] = proof['observedAt']
    require(type(proof.get('backupRestore')) is bool, 'unknown backup acceptance')
    result['backupRestore'] = proof['backupRestore']
    if stage in ('local-before', 'local-ready', 'local-after'):
        require(proof.get('retiredCoreConfigAbsent') is True, 'Core configuration absence not proven')
        result['retiredCoreConfigAbsent'] = True
    hashes = proof['releaseManifestHashes']
    require(set(hashes) == {'localManifest', 'coreManifest'} and
            all(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) for value in hashes.values()), 'invalid manifest hashes')
    result['releaseManifestHashes'] = hashes
    spec = proof['agentSpec']
    require(spec['selector'] == {'matchLabels': {'name': 'node-agent'}} and
            spec['owner'] in (['uds-takserver-config', 'takserver'], ['velero', 'velero']) and
            re.fullmatch('[0-9]+', spec['resourceVersion']), 'invalid public agent identity')
    counters = ('desiredNumberScheduled', 'numberReady', 'numberAvailable', 'updatedNumberScheduled',
                'numberUnavailable', 'numberMisscheduled', 'currentNumberScheduled', 'observedGeneration')
    status = {key: spec['status'][key] for key in counters if key in spec['status']}
    require(all(type(value) is int and value >= 0 for value in status.values()), 'invalid agent counters')
    result['agentSpec'] = {**{key: spec[key] for key in ('selector', 'owner', 'resourceVersion')}, 'status': status}
    if result['backupRestore']:
        suffix = {'fresh-core': 'fresh', 'core-after': 'core', 'local-after': 'local'}.get(stage)
        name = 'tak-ci-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'] + '-' + str(suffix)
        require(suffix and proof['backup'] == name and proof['restore'] == name + '-r', 'unexpected acceptance backup names')
        result.update(backup=name, restore=name + '-r')
        result['volumeCopies'] = {}
        for key in ('pvb', 'pvr'):
            entries = proof['volumeCopies'][key]
            require(isinstance(entries, list) and 0 < len(entries) <= 32, 'invalid volume-copy proof')
            result['volumeCopies'][key] = []
            for entry in entries:
                require(entry['namespace'] in ('takserver', 'cloudtak') and entry['volume'] == 'data'
                        and entry['phase'] == 'Completed' and re.fullmatch('[a-z0-9.-]{1,253}', entry['name']), 'unexpected volume-copy fields')
                result['volumeCopies'][key].append({field: entry[field] for field in ('namespace', 'volume', 'phase', 'name')})
    return result


def publish(directory, output, arch):
    """Always publish a small allowlist; never recursively copy private evidence."""
    scenarios, arches = selection()
    require(arch in arches and not output.exists(), 'invalid or reused public evidence destination')
    public = output / 'proofs' / arch
    public.mkdir(parents=True)
    (output / 'receipts').mkdir()
    try:
        value = receipt(directory, arch)
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        value = {'schema': 1, 'sourceSHA': os.environ['GITHUB_SHA'], 'runID': os.environ['GITHUB_RUN_ID'],
                 'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'], 'architecture': arch, 'scenarios': scenarios,
                 'accepted': False, 'results': {name: 'failed-or-incomplete' for name in scenarios}}
    (output / 'receipts' / (arch + '.json')).write_text(json.dumps(value, indent=2) + '\n')
    progress = {'schema': 1, 'accepted': value['accepted'], 'ownerSteps': [], 'identityStages': []}
    try:
        journal = bounded_json(directory / 'owner/journal.json')
        for entry in journal.get('steps', [])[:64]:
            if entry.get('name') in OWNER_STEPS and entry.get('status') in ('running', 'passed', 'failed'):
                progress['ownerSteps'].append({'name': entry['name'], 'status': entry['status']})
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        pass
    try:
        journal = bounded_json(directory / 'identity/journal.json')
        allowed = {'preflight', 'probe-compiled', 'traffic-baseline', 'traffic-dual-before-rollout',
                   'traffic-transition', 'traffic-strict', 'traffic-rollback', 'traffic-shared',
                   'reversed-and-verified', 'stopped'}
        progress['identityStages'] = [entry['stage'] for entry in journal.get('stages', [])[:200]
                                      if entry.get('stage') in allowed]
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        pass
    (public / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
    for group, stage in [('fresh', 'fresh-ready'), ('fresh', 'fresh-core'), ('handoff', 'local-before'),
                         ('handoff', 'core-ready'), ('handoff', 'core-after'), ('handoff', 'local-ready'), ('handoff', 'local-after')]:
        try:
            proof = bounded_json(directory / 'owner' / group / (stage + '.json'))
            require(proof.get('stage') == stage, 'wrong observer stage')
            allowed = sanitize_observer(proof, stage)
            (public / (stage + '.json')).write_text(json.dumps(allowed, indent=2) + '\n')
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            continue
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'receipt', 'verify', 'publish'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--arch', choices=('amd64', 'arm64'))
    args = parser.parse_args()
    if args.operation == 'plan':
        scenarios, arches = selection()
        print(json.dumps({'include': [{'arch': arch, 'runner': 'ubuntu-22.04' + ('-arm' if arch == 'arm64' else '')}
                                     for arch in arches]}))
    elif args.operation == 'receipt':
        require(args.directory is not None and args.arch is not None, 'receipt directory and arch required')
        print(json.dumps(receipt(args.directory, args.arch), indent=2))
    elif args.operation == 'publish':
        require(args.directory is not None and args.output is not None and args.arch is not None, 'publish arguments required')
        print(json.dumps(publish(args.directory, args.output, args.arch), indent=2))
    else:
        require(args.directory is not None, 'receipt directory required')
        print(json.dumps(verify(args.directory), indent=2))


if __name__ == '__main__':
    main()
