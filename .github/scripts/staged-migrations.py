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
import subprocess
import tempfile
import stat

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
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reviewed_bytes(relative):
    result = subprocess.run(['git', '-c', 'protocol.allow=never', 'show', 'HEAD:' + relative],
                            cwd=ROOT, capture_output=True, timeout=5,
                            env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'})
    require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024, 'reviewed source unavailable')
    return result.stdout


def regular_file(path):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)),
            'staged input must be a regular non-symlink file')


def regular(path, limit=1024 * 1024):
    regular_file(path)
    require(path.stat().st_size <= limit, 'staged text input exceeds bound')
    return path.read_bytes()


def restore_task_default(directory):
    """Restore only the exact trusted pin transform after archive/config binding."""
    import yaml  # Only the dependency-installed manual trial uses this operation.

    selection()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, timeout=5)
    require(head.returncode == 0 and head.stdout.decode().strip() == os.environ.get('GITHUB_SHA'),
            'staged restoration source differs from checkout')
    plan = json.loads(regular(directory / 'plan.json', 65536))
    require(set(plan) == {'schema', 'sourceSHA', 'files'} and plan['schema'] == 1
            and plan['sourceSHA'] == os.environ['GITHUB_SHA']
            and set(plan['files']) == {'core', 'detach', 'clean', 'config'}, 'valid bound candidate required')
    bound = {}
    for key, entry in plan['files'].items():
        require(set(entry) == {'path', 'sha256'} and re.fullmatch('[a-f0-9]{64}', entry['sha256']),
                'invalid bound input')
        relative = Path(entry['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'bound input escapes candidate')
        path = directory / relative
        regular_file(path)
        require(sha(path) == entry['sha256'], 'bound input changed')
        bound[key] = (path, entry['sha256'])
    task = ROOT / 'tasks.yaml'
    actual, reviewed = regular(task), reviewed_bytes('tasks.yaml')
    helpers = ('.github/container-and-chart/docker/build.sh', '.github/container-and-chart/docker/version.txt',
               '.github/scripts/pin-image-tags.sh')
    trusted = {name: reviewed_bytes(name) for name in helpers}
    require(all(regular(ROOT / name) == data for name, data in trusted.items()), 'unreviewed tag helper')
    version = trusted[helpers[1]].decode().strip()
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,80}', version), 'invalid reviewed image version')
    env = {key: value for key, value in os.environ.items() if key not in ('BASH_ENV', 'ENV')
           and not key.startswith('BASH_FUNC_')}
    result = subprocess.run(['bash', '--noprofile', '--norc', str(ROOT / helpers[0]), '--tag'],
                            cwd=ROOT, capture_output=True, timeout=10, env=env)
    require(result.returncode == 0 and len(result.stdout) <= 256, 'trusted image tag unavailable')
    tag = result.stdout.decode().strip()
    require(re.fullmatch(re.escape(version) + '-[a-f0-9]{12}', tag), 'unexpected trusted image tag')
    require(all(regular(ROOT / name) == data for name, data in trusted.items()), 'tag helper changed')
    old = ('  - name: TAK_IMAGE_TAG\n    default: ' + version + '\n').encode()
    new = ('  - name: TAK_IMAGE_TAG\n    default: ' + tag + '\n').encode()
    require(reviewed.count(old) == 1 and actual in (reviewed, reviewed.replace(old, new)),
            'tasks differ beyond the exact reviewed pin transform')
    try:
        config = yaml.safe_load(regular(bound['config'][0], 65536))
    except yaml.YAMLError:
        raise ValueError('bound trial config is not valid YAML') from None
    require(isinstance(config, dict) and set(config) == {'variables'}
            and isinstance(config['variables'], dict) and set(config['variables']) == {'takserver'},
            'bound config must contain only reviewed TAK variables')
    values = config['variables']['takserver']
    require(isinstance(values, dict) and set(values) == {'DOMAIN', 'TAK_IMAGE_TAG', 'FILESYSTEM_BACKUP',
                                                       'POSTGRES_STORAGE_CLASS', 'CLOUDTAK_STORAGE_CLASS'}
            and values['DOMAIN'] == 'uds.dev' and str(values['FILESYSTEM_BACKUP']).lower() == 'true'
            and values['POSTGRES_STORAGE_CLASS'] == values['CLOUDTAK_STORAGE_CLASS'] == 'local-path-local'
            and values['TAK_IMAGE_TAG'] == tag, 'bound config differs from reviewed pinned trial contract')
    require(all(sha(path) == digest for path, digest in bound.values()) and regular(task) == actual,
            'staged inputs changed before restoration')
    current = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, timeout=5)
    require(current.returncode == 0 and current.stdout == head.stdout, 'checkout changed before restoration')
    if actual != reviewed:
        descriptor, temporary = tempfile.mkstemp(prefix='.staged-task-', dir=ROOT)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(reviewed)
            os.chmod(temporary, task.stat().st_mode & 0o777)
            os.replace(temporary, task)
        finally:
            Path(temporary).unlink(missing_ok=True)
    require(regular(task) == reviewed and all(sha(path) == digest for path, digest in bound.values()),
            'staged inputs changed during restoration')
    print('Reviewed task defaults restored; bound archives and pinned config unchanged')


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
    if 'velero' in scenarios:
        result['daemonsetUID'] = json.loads((directory / 'owner/journal.json').read_text())['daemonsetUID']
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
        verify_public_proofs(directory.parent / 'proofs' / arch, value)
    return {'selectedArchitectures': arches, 'selectedScenarios': scenarios, 'accepted': True}


def verify_public_proofs(directory, value):
    hashes = value['publishedProofHashes']
    progress_path = directory / 'progress.json'
    require(sha(progress_path) == hashes['progress'], 'published progress differs')
    progress = bounded_json(progress_path)
    require(progress.get('accepted') is True, 'published progress is not accepted')
    if 'velero' in value['scenarios']:
        require(progress.get('ownerSteps') == [{'name': name, 'status': 'passed'} for name in OWNER_STEPS],
                'public owner progress is incomplete')
        for stage in ('fresh-core', 'core-after', 'local-after'):
            path = directory / (stage + '.json')
            require(sha(path) == hashes[stage], 'published observer proof differs or is absent')
            proof = bounded_json(path)
            require(sanitize_observer(proof, stage) == proof and proof['backupRestore'] is True
                    and proof['observerSHA256'] == sha(ROOT / 'tests/velero-ownership/observe.py')
                    and proof['clusterUID'] == value['clusterUID'] and proof['daemonsetUID'] == value['daemonsetUID'],
                    'published observer acceptance does not match receipt')
    if 'identities' in value['scenarios']:
        require({'traffic-baseline', 'traffic-dual-before-rollout', 'traffic-transition', 'traffic-strict',
                 'traffic-rollback', 'traffic-shared', 'reversed-and-verified'}.issubset(progress['identityStages'])
                and 'stopped' not in progress['identityStages'], 'public identity progress is incomplete')


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


# Classifications are signatures in an already-retained tail, never causal proof.
# Neither matches nor surrounding text may leave the private evidence directory.
FAILURE_PATTERNS = {
    'package-unavailable': r'manifest unknown|name unknown|package.{0,80}not found|failed to (?:pull|fetch) package',
    'package-integrity': r'checksum mismatch|invalid archive|invalid tar|not a tar archive|failed to extract|unexpected eof',
    'cli-arguments': r'unknown flag|unknown command|invalid argument|accepts [0-9]+ arg',
    'signature-verification': r'failed to verify (?:certificate|signature)|signature verification failed|no matching signatures',
    'authentication': r'unauthorized|\bforbidden\b|authentication required|access denied|denied: requested access|status(?: code)?[ :]+40[13]|http/[0-9.]+\s+403',
    'helm-operation': r'helm upgrade failed|helm install failed|upgrade failed:|installation failed:|another operation .{0,80}in progress',
    'schema-validation': r'validation (?:failed|error)|failed to validate|unknown field|additional propert(?:y|ies)|values don.t meet the specifications',
    'cluster-connectivity': r'kubernetes cluster unreachable|connection refused|unable to connect to the server|no route to host',
    'tls-certificate': r'x509:|certificate has expired|certificate signed by unknown authority|unknown ca|tls handshake timeout',
    'admission-webhook': r'failed calling webhook|admission webhook.{0,160}denied|no endpoints available for service',
    'timeout': r'context deadline exceeded|timed out waiting|i/o timeout|operation timed out',
}


def failure_categories(directory, progress):
    """Read one bounded regular private file; publish only fixed IDs/counts."""
    source, run, attempt = (os.environ.get(key, '') for key in
                            ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'))
    require(re.fullmatch('[a-f0-9]{40}', source) and re.fullmatch('[1-9][0-9]*', run)
            and re.fullmatch('[1-9][0-9]*', attempt), 'invalid diagnostic source/run identity')
    failed = [entry['name'] for entry in progress['ownerSteps']
              if entry.get('status') == 'failed' and entry.get('name') in OWNER_STEPS]
    result = {'schema': 1, 'sourceSHA': source, 'runID': run, 'runAttempt': attempt,
              'failedStep': failed[-1] if failed else 'unavailable',
              'scope': 'retained-tail-signatures-only', 'status': 'unavailable', 'categories': []}
    path = directory / 'owner/PRIVATE-command-failure.txt'
    try:
        regular_file(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                result['status'] = 'unavailable-oversized-or-nonregular'
                return result
            raw = stream.read(65537)
        if len(raw) > 65536 or b'\0' in raw:
            result['status'] = 'unavailable-oversized-or-invalid-text'
            return result
        text = raw.decode('utf-8', errors='strict')
        # Entire retained stream is classified before any selection or output.
        for identifier, pattern in FAILURE_PATTERNS.items():
            count = len(re.findall(pattern, text, re.IGNORECASE))
            if count:
                result['categories'].append({'patternID': identifier, 'count': min(count, 32)})
        result['status'] = 'classified' if result['categories'] else 'unclassified'
    except (OSError, ValueError, UnicodeError):
        pass  # Never publish exception text or captured private content.
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
    if not value['accepted']:
        diagnostic = failure_categories(directory, progress)
        (public / 'failure-categories.json').write_text(json.dumps(diagnostic, indent=2) + '\n')
    value['publishedProofHashes'] = {path.stem: sha(path) for path in public.glob('*.json')}
    if value['accepted']:
        try:
            verify_public_proofs(public, value)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            value['accepted'] = False
            value['results'] = {name: 'failed-or-incomplete' for name in scenarios}
    if progress['accepted'] != value['accepted']:
        progress['accepted'] = value['accepted']
        (public / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
        value['publishedProofHashes']['progress'] = sha(public / 'progress.json')
    (output / 'receipts' / (arch + '.json')).write_text(json.dumps(value, indent=2) + '\n')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'receipt', 'verify', 'publish', 'restore-task-default'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--arch', choices=('amd64', 'arm64'))
    args = parser.parse_args()
    if args.operation == 'restore-task-default':
        require(args.directory is not None, 'bound candidate directory required')
        restore_task_default(args.directory)
    elif args.operation == 'plan':
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
