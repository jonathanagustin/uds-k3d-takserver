#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only evidence qualification; never authorizes or implements CI reuse."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import tempfile
import time
import zipfile
import zlib

REPO = 'jonathanagustin/uds-takserver'
WORKFLOW = '.github/workflows/test.yaml'
POLICY_FILES = (WORKFLOW, '.github/scripts/install-receipt.py',
                '.github/scripts/collect-install-receipt.py',
                '.github/scripts/install-artifact-inputs.py',
                '.github/scripts/checkpoint-identity.py', '.github/scripts/dev-package.sh')
MAX_BYTES = 4 * 1024 * 1024
MAX_PAGES = 10
COMMAND_TIMEOUT = 45
SHA = re.compile(r'[a-f0-9]{40}')
SPEC = importlib.util.spec_from_file_location('install_receipt', Path(__file__).with_name('install-receipt.py'))
ENCODER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENCODER)


class Unavailable(Exception):
    """A bounded reason to execute fresh; never contains remote response bodies."""


def require(ok, reason):
    if not ok:
        raise Unavailable(reason)


def unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def command(args, binary=False):
    """Drain bounded pipes; child caches are not subject to file-size limits."""
    child = None
    captured = bytearray()
    counts = {'stdout': 0, 'stderr': 0}
    deadline = time.monotonic() + COMMAND_TIMEOUT
    try:
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            for pipe, name in ((child.stdout, 'stdout'), (child.stderr, 'stderr')):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'command-timeout')
                for key, _ in selector.select(min(remaining, 0.1)):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    counts[key.data] += len(block)
                    require(counts[key.data] <= MAX_BYTES, 'command-output-too-large')
                    if key.data == 'stdout':
                        captured.extend(block)
            try:
                result = child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise Unavailable('command-timeout') from None
        require(result == 0, 'command-failed')
    except OSError:
        raise Unavailable('command-unavailable') from None
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, 9)
            except ProcessLookupError:
                pass
            child.wait()
            child.stdout.close()
            child.stderr.close()
    if binary:
        return bytes(captured)
    try:
        return json.loads(captured, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError, RecursionError):
        raise Unavailable('command-json-invalid') from None


class GitHub:
    def __init__(self, gh):
        self.gh = gh

    def get(self, path):
        return command([self.gh, 'api', '--hostname', 'github.com', f'repos/{REPO}/{path}'])

    def artifact(self, artifact_id):
        raw = command([self.gh, 'api', '--hostname', 'github.com',
                       f'repos/{REPO}/actions/artifacts/{artifact_id}/zip'], binary=True)
        return archive_receipt(raw)

    def pages(self, path, key):
        """Fetch all pages, including the final empty page for exact multiples."""
        values = []
        expected = None
        for page in range(1, MAX_PAGES + 1):
            sep = '&' if '?' in path else '?'
            data = self.get(f'{path}{sep}per_page=100&page={page}')
            require(isinstance(data, dict) and type(data.get('total_count')) is int and
                    isinstance(data.get(key), list), 'api-page-invalid')
            if expected is None:
                expected = data['total_count']
            require(expected == data['total_count'] and expected <= MAX_PAGES * 100,
                    'api-pagination-changed-or-too-large')
            rows = data[key]
            values.extend(rows)
            require(len(values) <= expected and len(rows) <= 100, 'api-page-count-invalid')
            if len(rows) < 100:
                require(len(values) == expected, 'api-pages-incomplete')
                ids = [row.get('id') for row in values]
                require(all(type(item) is int for item in ids) and len(set(ids)) == len(ids),
                        'api-pages-ambiguous')
                return values
        raise Unavailable('api-pagination-limit')

    def file(self, commit, path):
        data = self.get(f'contents/{path}?ref={commit}')
        require(data.get('encoding') == 'base64' and data.get('type') == 'file' and
                type(data.get('size')) is int and data['size'] <= 1024 * 1024,
                'policy-file-unavailable')
        try:
            content = base64.b64decode(data['content'], validate=False)
        except (ValueError, KeyError):
            raise Unavailable('policy-file-invalid') from None
        require(len(content) == data['size'], 'policy-file-size-invalid')
        return content


def archive_receipt(raw):
    require(len(raw) <= MAX_BYTES, 'artifact-archive-too-large')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1, 'artifact-archive-entries-invalid')
            item = entries[0]
            require(re.fullmatch(r'install-receipt-install(?:-airgap)?-(?:amd64|arm64)\.json', item.filename)
                    and not item.is_dir() and item.file_size <= 64 * 1024 and
                    not item.flag_bits & 1 and
                    stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG),
                    'artifact-archive-entry-invalid')
            return archive.read(item)
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, EOFError, zlib.error):
        raise Unavailable('artifact-archive-invalid') from None


def validate_receipt(value):
    try:
        ENCODER.fields(value, {'schema_version', 'kind', 'reuse_authorized', 'source', 'workflow',
                               'run', 'scenario', 'execution', 'inputs'}, 'receipt')
        require(type(value['schema_version']) is int and value['schema_version'] == 1 and
                value['kind'] == 'install-execution' and value['reuse_authorized'] is False,
                'receipt-schema-or-authorization-invalid')
        ENCODER.fields(value['source'], {'repository', 'checkout_commit', 'checkout_tree'}, 'source')
        ENCODER.fields(value['workflow'], {'path', 'sha256'}, 'workflow')
        ENCODER.fields(value['run'], {'id', 'attempt', 'event', 'job'}, 'run')
        ENCODER.fields(value['scenario'], {'name', 'architecture', 'mode'}, 'scenario')
        ENCODER.fields(value['execution'], {'step', 'result'}, 'execution')
        src, run, scenario = value['source'], value['run'], value['scenario']
        require(src['repository'] == REPO and all(isinstance(src[k], str) and SHA.fullmatch(src[k])
                for k in ('checkout_commit', 'checkout_tree')), 'receipt-source-invalid')
        require(run['event'] == 'pull_request' and run['job'] == 'validate-install' and
                all(type(run[k]) is int and run[k] > 0 for k in ('id', 'attempt')), 'receipt-run-invalid')
        require(scenario['mode'] == 'ordinary' and scenario['architecture'] in ('amd64', 'arm64') and
                scenario['name'] in ('install', 'install-airgap') and
                (scenario['name'] == 'install' or scenario['architecture'] == 'amd64'),
                'receipt-scenario-invalid')
        step = 'Test' if scenario['name'] == 'install' else 'Install and test without node internet egress'
        require(value['execution'] == {'step': step, 'result': 'success'}, 'receipt-execution-invalid')
        require(value['workflow']['path'] == WORKFLOW and
                isinstance(value['workflow']['sha256'], str) and
                re.fullmatch(r'[a-f0-9]{64}', value['workflow']['sha256']), 'receipt-workflow-invalid')
        ENCODER.validate_inputs(value['inputs'], scenario['architecture'])
    except (KeyError, TypeError, ValueError):
        raise Unavailable('receipt-schema-invalid') from None


def validate_signature(verified, raw, receipt, pr):
    require(isinstance(verified, list) and len(verified) == 1, 'signature-result-ambiguous')
    result = verified[0]['verificationResult']
    cert = result['signature']['certificate']
    source = receipt['source']['checkout_commit']
    ref = f'refs/pull/{pr}/merge'
    signer = f'https://github.com/{REPO}/{WORKFLOW}@{ref}'
    invocation = (f'https://github.com/{REPO}/actions/runs/{receipt["run"]["id"]}'
                  f'/attempts/{receipt["run"]["attempt"]}')
    expected = {'issuer': 'https://token.actions.githubusercontent.com',
                'subjectAlternativeName': signer, 'buildSignerURI': signer,
                'buildSignerDigest': source, 'sourceRepositoryDigest': source,
                'sourceRepositoryURI': f'https://github.com/{REPO}',
                'sourceRepositoryRef': ref, 'sourceRepositoryIdentifier': '1427088300',
                'sourceRepositoryOwnerIdentifier': '5193877', 'runnerEnvironment': 'github-hosted',
                'runInvocationURI': invocation, 'buildTrigger': 'pull_request',
                'buildConfigURI': signer, 'buildConfigDigest': source}
    require(all(cert.get(k) == v for k, v in expected.items()), 'signature-identity-mismatch')
    statement = result['statement']
    require(statement['_type'] == 'https://in-toto.io/Statement/v1' and
            statement['predicateType'] == 'https://slsa.dev/provenance/v1', 'signature-predicate-invalid')
    subjects = statement['subject']
    subject_name = f'install-receipt-{receipt["scenario"]["name"]}-{receipt["scenario"]["architecture"]}.json'
    require(len(subjects) == 1 and subjects[0].get('name') == subject_name and
            subjects[0]['digest'] == {'sha256': hashlib.sha256(raw).hexdigest()},
            'signature-subject-mismatch')
    predicate = statement['predicate']
    definition = predicate['buildDefinition']
    require(definition['buildType'] == 'https://actions.github.io/buildtypes/workflow/v1' and
            definition['externalParameters']['workflow'] ==
            {'path': WORKFLOW, 'ref': ref, 'repository': f'https://github.com/{REPO}'},
            'signature-workflow-mismatch')
    require(definition['resolvedDependencies'] ==
            [{'digest': {'gitCommit': source}, 'uri': f'git+https://github.com/{REPO}@{ref}'}] and
            predicate['runDetails']['metadata']['invocationId'] == invocation,
            'signature-source-or-invocation-mismatch')


def successful_step(job, name):
    steps = [step for step in job['steps'] if step.get('name') == name]
    require(len(steps) == 1 and steps[0].get('status') == 'completed' and
            steps[0].get('conclusion') == 'success', 'execution-or-cleanup-not-successful')


def qualify(api, receipt, raw, verified, pr_number, target, policy_ref):
    """Pure read-only policy over injected API/crypto evidence; no skip output exists."""
    validate_receipt(receipt)
    validate_signature(verified, raw, receipt, pr_number)
    pr = api.get(f'pulls/{pr_number}')
    require(pr['number'] == pr_number and pr['state'] == 'closed' and pr['merged'] is True and pr['base']['ref'] == 'main' and
            pr['base']['repo']['full_name'] == REPO and pr['head']['repo']['full_name'] == REPO and
            pr['merge_commit_sha'] == target, 'not-unambiguous-same-repository-main-merge')
    source = api.get(f'git/commits/{receipt["source"]["checkout_commit"]}')
    pushed = api.get(f'git/commits/{target}')
    source_parents = [parent['sha'] for parent in source['parents']]
    target_parents = [parent['sha'] for parent in pushed['parents']]
    # PR base.sha can retain an older fork-point snapshot after main advances.
    # The immutable commits must prove that the ACTUAL tested/merged bases match.
    require(source['sha'] == receipt['source']['checkout_commit'] and pushed['sha'] == target and
            len(source_parents) == 2 and len(target_parents) == 1 and
            all(isinstance(parent, str) and SHA.fullmatch(parent)
                for parent in source_parents + target_parents) and
            source_parents[0] == target_parents[0] and source_parents[1] == pr['head']['sha'],
            'synthetic-merge-or-squash-ancestry-mismatch')
    require(source['tree']['sha'] == receipt['source']['checkout_tree'] == pushed['tree']['sha'],
            'tested-and-pushed-trees-differ')
    for path in POLICY_FILES:
        content = api.file(source['sha'], path)
        require(content == api.file(policy_ref, path), 'unreviewed-producer-or-workflow')
        if path == WORKFLOW:
            require(hashlib.sha256(content).hexdigest() == receipt['workflow']['sha256'],
                    'committed-workflow-hash-mismatch')
    workflow = api.get(f'actions/workflows/{WORKFLOW.rsplit("/", 1)[1]}')
    run = api.get(f'actions/runs/{receipt["run"]["id"]}')
    require(run['id'] == receipt['run']['id'] and run['workflow_id'] == workflow['id'] and run['path'] == WORKFLOW and
            run['event'] == 'pull_request' and run['head_sha'] == pr['head']['sha'] and
            run['head_repository']['full_name'] == REPO and run['status'] == 'completed' and
            run['conclusion'] == 'success' and run['run_attempt'] == receipt['run']['attempt'],
            'run-identity-attempt-or-result-mismatch')
    runs = api.pages(f'actions/workflows/{workflow["id"]}/runs?event=pull_request&head_sha={pr["head"]["sha"]}',
                     'workflow_runs')
    # GitHub clears pull_requests after merge. The signed PR merge ref already
    # binds the selected run; conservatively consider EVERY same-repo PR run for
    # this exact workflow/head, including newer failed/queued unassociated rows.
    applicable = []
    seen = set()
    for item in runs:
        repository = item.get('head_repository')
        require(type(item.get('id')) is int and item['id'] > 0 and item['id'] not in seen and
                type(item.get('workflow_id')) is int and item['workflow_id'] == workflow['id'] and
                item.get('event') == 'pull_request' and item.get('head_sha') == pr['head']['sha'] and
                type(item.get('run_attempt')) is int and item['run_attempt'] > 0 and
                isinstance(repository, dict) and type(repository.get('id')) is int and
                repository['id'] > 0 and isinstance(repository.get('full_name'), str) and
                re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}', repository['full_name']) and
                (repository['full_name'] == REPO) == (repository['id'] == 1427088300),
                'run-list-identity-missing-contradictory-or-ambiguous')
        seen.add(item['id'])
        if repository['full_name'] != REPO:
            continue  # A positively identified foreign fork is not same-repo evidence.
        applicable.append(item)
    require(applicable and max(item['id'] for item in applicable) == run['id'],
            'not-latest-applicable-run')
    selected_run = next(item for item in applicable if item['id'] == run['id'])
    require(selected_run['run_attempt'] == run['run_attempt'] and
            selected_run.get('status') == run['status'] and
            selected_run.get('conclusion') == run['conclusion'],
            'selected-run-list-attempt-or-result-changed')
    jobs = api.pages(f'actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs', 'jobs')
    scenario = receipt['scenario']
    offline = scenario['name'] == 'install-airgap'
    name = f'validate-install ({scenario["architecture"]}{", airgap" if offline else ""})'
    selected = [job for job in jobs if job.get('name') == name]
    require(len(selected) == 1 and selected[0]['status'] == 'completed' and
            selected[0]['conclusion'] == 'success' and selected[0]['run_id'] == run['id'] and
            selected[0]['run_attempt'] == run['run_attempt'], 'scenario-job-missing-ambiguous-or-failed')
    successful_step(selected[0], receipt['execution']['step'])
    if offline:
        successful_step(selected[0], 'Restore airgap node egress')
    successful_step(selected[0], 'Authenticate optional install receipt')
    successful_step(selected[0], 'Upload authenticated install receipt')
    artifacts = api.pages(f'actions/runs/{run["id"]}/artifacts', 'artifacts')
    arch = 'X64' if scenario['architecture'] == 'amd64' else 'ARM64'
    artifact_name = f'install-receipt-{arch}-{"airgap" if offline else "online"}-{run["id"]}-{run["run_attempt"]}'
    found = [item for item in artifacts if item.get('name') == artifact_name]
    require(len(found) == 1 and found[0].get('expired') is False, 'artifact-missing-expired-or-ambiguous')
    require(api.artifact(found[0]['id']) == raw, 'artifact-receipt-bytes-mismatch')
    return {'source_run': run['id'], 'attempt': run['run_attempt'], 'job_id': selected[0]['id'],
            'artifact_id': found[0]['id'], 'scenario': scenario['name'],
            'architecture': scenario['architecture'], 'tested_commit': source['sha'],
            'tested_tree': source['tree']['sha'], 'target_commit': target}


def shadow(api, raw, verified, pr, target, policy):
    result = {'schema_version': 1, 'mode': 'shadow', 'reuse_authorized': False,
              'decision': 'execute-fresh', 'evidence_qualified': False,
              'blockers': ['prospective-input-equivalence-not-proven',
                           'execution-class-policy-not-established',
                           'complete-producer-dependency-policy-not-established',
                           'consumer-enforcement-not-enabled']}
    try:
        require(len(raw) <= 64 * 1024, 'receipt-too-large')
        receipt = json.loads(raw, object_pairs_hook=unique_fields)
        result['evidence'] = qualify(api, receipt, raw, verified, pr, target, policy)
        result['evidence_qualified'] = True
    except Unavailable as exc:
        result['blockers'].insert(0, str(exc))
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        result['blockers'].insert(0, 'evidence-malformed-or-unavailable')
    return result


def bounded_file(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), 'evidence-not-regular-file')
        data = source.read(maximum + 1)
        require(len(data) <= maximum, 'evidence-file-too-large')
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--target', required=True, help='Exact proposed pushed squash commit SHA')
    parser.add_argument('--policy-ref', required=True, help='Exact independently reviewed producer/workflow commit')
    parser.add_argument('--gh', default='gh', help='GitHub CLI with attestation verification support')
    args = parser.parse_args()
    result = None
    try:
        require(args.pr > 0 and SHA.fullmatch(args.target) and SHA.fullmatch(args.policy_ref), 'arguments-invalid')
        raw = bounded_file(args.receipt, 64 * 1024)
        bundle = bounded_file(args.bundle, MAX_BYTES)
        receipt = json.loads(raw, object_pairs_hook=unique_fields)
        validate_receipt(receipt)
        ref = f'refs/pull/{args.pr}/merge'
        # Freeze bounded bytes before handing paths to the external verifier.
        with tempfile.TemporaryDirectory(prefix='install-shadow-') as directory:
            subject_path = Path(directory) / 'receipt.json'
            bundle_path = Path(directory) / 'bundle.jsonl'
            subject_path.write_bytes(raw)
            bundle_path.write_bytes(bundle)
            verified = command([args.gh, 'attestation', 'verify', str(subject_path), '--bundle', str(bundle_path),
                                '--repo', REPO, '--hostname', 'github.com', '--format', 'json',
                                '--cert-identity', f'https://github.com/{REPO}/{WORKFLOW}@{ref}',
                                '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com',
                                '--deny-self-hosted-runners', '--source-ref', ref,
                                '--source-digest', receipt['source']['checkout_commit'],
                                '--signer-digest', receipt['source']['checkout_commit']])
        result = shadow(GitHub(args.gh), raw, verified, args.pr, args.target, args.policy_ref)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, Unavailable):
        result = {'schema_version': 1, 'mode': 'shadow', 'reuse_authorized': False,
                  'decision': 'execute-fresh', 'evidence_qualified': False,
                  'blockers': ['crypto-command-or-evidence-unavailable']}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
