#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline release-binding policy; consumes trusted checked metadata, never API writes."""
import argparse
import hashlib
import importlib.util
import os
import subprocess
import urllib.parse
import urllib.request
import json
from pathlib import Path
import re
import resource
import sys

REPO = 'jonathanagustin/uds-takserver'
REPOSITORY = 'https://github.com/' + REPO
SUBJECT = 'ghcr.io/' + REPO + '/takserver'
WORKFLOW = REPOSITORY + '/.github/workflows/release.yaml'
PREDICATE = REPOSITORY + '/attestations/release-binding/v1'
INDEX_TYPE = 'application/vnd.oci.image.index.v1+json'
MANIFEST_TYPE = 'application/vnd.oci.image.manifest.v1+json'
LIMIT = 1024 * 1024


def require(condition):
    if not condition:
        raise ValueError('release binding policy rejected')


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    require(len(raw) <= LIMIT)
    return json.loads(raw, object_pairs_hook=unique)


def architectures(raw, digest):
    require(matches(digest, r'sha256:[0-9a-f]{64}'))
    require('sha256:' + hashlib.sha256(raw).hexdigest() == digest)
    index = decode(raw)
    exact(index, ('schemaVersion', 'mediaType', 'manifests'))
    require(type(index['schemaVersion']) is int and index['schemaVersion'] == 2)
    require(index['mediaType'] == INDEX_TYPE)
    descriptors = index['manifests']
    require(type(descriptors) is list and 2 <= len(descriptors) <= 4)
    result, ancillary, seen = {}, [], set()
    for item in descriptors:
        require(type(item) is dict)
        exact(item, ('mediaType', 'digest', 'size', 'platform') if 'annotations' not in item
              else ('mediaType', 'digest', 'size', 'platform', 'annotations'))
        require(item['mediaType'] == MANIFEST_TYPE)
        require(matches(item['digest'], r'sha256:[0-9a-f]{64}') and item['digest'] not in seen)
        seen.add(item['digest'])
        require(type(item['size']) is int and 0 < item['size'] <= 16 * 1024 * 1024)
        exact(item['platform'], ('architecture', 'os'))
        arch = item['platform']['architecture']
        if arch in ('amd64', 'arm64'):
            require('annotations' not in item and item['platform']['os'] == 'multi' and arch not in result)
            result[arch] = item['digest']
        else:
            require(item['platform'] == {'architecture': 'unknown', 'os': 'unknown'})
            annotations = item.get('annotations')
            exact(annotations, ('vnd.docker.reference.type', 'vnd.docker.reference.digest'))
            require(annotations['vnd.docker.reference.type'] == 'attestation-manifest')
            ancillary.append(annotations['vnd.docker.reference.digest'])
    require(set(result) == {'amd64', 'arm64'})
    require(len(set(ancillary)) == len(ancillary) and set(ancillary) <= set(result.values()))
    return [{'architecture': arch, 'digest': result[arch]} for arch in sorted(result)]


def predicate(metadata, raw_index):
    """Metadata must come from trusted release/API/tag checks, not manual input alone."""
    exact(metadata, ('repository', 'release', 'workflow', 'indexDigest'))
    require(metadata['repository'] == REPO)
    release, workflow = metadata['release'], metadata['workflow']
    exact(release, ('tag', 'id', 'applicationCommit'))
    require(matches(release['tag'], r'v[0-9]+\.[0-9]+\.[0-9]+'))
    require(matches(release['id'], r'[1-9][0-9]*'))
    require(matches(release['applicationCommit'], r'[0-9a-f]{40}'))
    exact(workflow, ('commit', 'runID', 'runAttempt', 'ref'))
    require(matches(workflow['commit'], r'[0-9a-f]{40}'))
    for key in ('runID', 'runAttempt'):
        require(matches(workflow[key], r'[1-9][0-9]*'))
    require(workflow['ref'] in ('refs/heads/main', 'refs/tags/' + release['tag']))
    return {'schemaVersion': 1, 'repository': REPO, 'release': dict(release),
            'workflow': dict(workflow), 'architectures': architectures(raw_index, metadata['indexDigest'])}


def verify_verified_output(output, metadata, raw_index):
    """Policy on successful modern gh verify JSON; not a cryptographic verifier.

    The caller MUST check gh's exit status and use the expected subject,
    predicate-type, issuer, signer-workflow, signer-digest and source-digest.
    This function cannot authenticate a JSON file or an attestation bundle.
    """
    expected = predicate(metadata, raw_index)
    require(type(output) is list and 1 <= len(output) <= 256)
    workflow = metadata['workflow']
    identity = WORKFLOW + '@' + workflow['ref']
    invocation = REPOSITORY + '/actions/runs/' + workflow['runID'] + '/attempts/' + workflow['runAttempt']
    candidates = []
    for entry in output:
        result = entry['verificationResult']
        certificate = result['signature']['certificate']
        for key, value in {
            'issuer': 'https://token.actions.githubusercontent.com',
            'buildSignerDigest': workflow['commit'],
            'sourceRepositoryURI': REPOSITORY, 'sourceRepositoryDigest': workflow['commit'],
            'sourceRepositoryIdentifier': '1427088300',
            'sourceRepositoryOwnerIdentifier': '5193877',
        }.items():
            require(certificate.get(key) == value)
        trusted_identities = (WORKFLOW + '@refs/heads/main',
                              WORKFLOW + '@refs/tags/' + metadata['release']['tag'])
        require(certificate.get('subjectAlternativeName') in trusted_identities and
                certificate.get('buildSignerURI') == certificate['subjectAlternativeName'])
        require(matches(certificate.get('runInvocationURI'),
                        re.escape(REPOSITORY) + r'/actions/runs/[1-9][0-9]*/attempts/[1-9][0-9]*'))
        require(type(result.get('verifiedTimestamps')) is list and bool(result['verifiedTimestamps']))
        if certificate['runInvocationURI'] == invocation:
            require(certificate['subjectAlternativeName'] == identity)
            candidates.append(result)
    # Never substitute an old attempt or choose the first of duplicate current records.
    require(len(candidates) == 1)
    result = candidates[0]
    statement = result['statement']
    exact(statement, ('_type', 'subject', 'predicateType', 'predicate'))
    require(statement['_type'] == 'https://in-toto.io/Statement/v1')
    require(statement['predicateType'] == PREDICATE)
    require(statement['subject'] == [{'name': SUBJECT, 'digest': {'sha256': metadata['indexDigest'][7:]}}])
    require(json.dumps(statement['predicate'], sort_keys=True, separators=(',', ':')) ==
            json.dumps(expected, sort_keys=True, separators=(',', ':')))
    require(type(result.get('verifiedTimestamps')) is list and bool(result['verifiedTimestamps']))


def read(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    require(len(raw) <= LIMIT)
    return raw


def trusted_metadata(digest, environment=None, api=None, head=None):
    """Revalidate application identity via API; workflow identity is a separate input."""
    env = os.environ if environment is None else environment
    spec = importlib.util.spec_from_file_location('release_readiness', Path(__file__).with_name('release-readiness.py'))
    readiness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(readiness)
    require(env.get('GITHUB_REPOSITORY') == REPO)
    workflow_sha = env.get('WORKFLOW_SHA', '')
    require(matches(workflow_sha, r'[0-9a-f]{40}'))
    if head is None:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], timeout=10).decode().strip()
    require(head == workflow_sha)
    require(env.get('GITHUB_EVENT_NAME') in ('push', 'release', 'workflow_dispatch'))
    release_id, source = env.get('RELEASE_ID', ''), env.get('RELEASE_SOURCE_SHA', '')
    if release_id or source:
        require(env.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch') and
                env.get('GITHUB_REF') == 'refs/heads/main')
    checked = env.get('CHECKED_SOURCE_SHA', '')
    require(matches(checked, r'[0-9a-f]{40}'))
    if api is None:
        api = readiness.API(env.get('GH_TOKEN', ''), allow_write=False)
    record = readiness.check_release(api, env.get('RELEASE_TAG', ''), release_id, source, checked)
    return {'repository': REPO,
            'release': {'tag': record['tag_name'], 'id': str(record['id']), 'applicationCommit': checked},
            'workflow': {'commit': workflow_sha, 'runID': env.get('GITHUB_RUN_ID', ''),
                         'runAttempt': env.get('GITHUB_RUN_ATTEMPT', ''), 'ref': env.get('GITHUB_REF', '')},
            'indexDigest': digest}


def registry_index(digest, tag=None):
    """Anonymous public GHCR read, exact bounded bytes; no redirect or key change."""
    require(matches(digest, r'sha256:[0-9a-f]{64}'))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            raise ValueError('registry redirect refused')
    opener = urllib.request.build_opener(NoRedirect())
    def get(url, headers=None):
        with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=20) as response:
            raw = response.read(LIMIT + 1)
            require(len(raw) <= LIMIT)
            return raw
    query = urllib.parse.urlencode({'service': 'ghcr.io', 'scope': 'repository:'+REPO+'/takserver:pull'})
    token = decode(get('https://ghcr.io/token?'+query)).get('token')
    require(type(token) is str and 0 < len(token) < 16384 and '\n' not in token and '\r' not in token)
    reference = digest
    if tag is not None:
        require(matches(tag, r'v[0-9]+\.[0-9]+\.[0-9]+'))
        reference = tag[1:]+'-upstream'
    raw = get('https://ghcr.io/v2/'+REPO+'/takserver/manifests/'+reference,
              {'Authorization': 'Bearer '+token, 'Accept': INDEX_TYPE})
    architectures(raw, digest)
    return raw


def verify_live(metadata, raw, runner=subprocess.run):
    """Cryptography succeeds before policy; neither stdout nor stderr is published."""
    workflow = metadata['workflow']
    command = ['gh', 'attestation', 'verify', 'oci://'+SUBJECT+'@'+metadata['indexDigest'],
               '--owner', REPO.split('/')[0], '--signer-workflow', REPO+'/.github/workflows/release.yaml',
               '--signer-digest', workflow['commit'], '--source-digest', workflow['commit'],
               '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com',
               '--predicate-type', PREDICATE, '--bundle-from-oci', '--format=json']
    # Files bound capture memory; reject oversized output rather than publish it.
    import tempfile
    def limit_capture():
        resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = runner(command, stdout=stdout, stderr=stderr, timeout=90, check=False,
                        preexec_fn=limit_capture)
        require(result.returncode == 0)
        require(stdout.tell() <= LIMIT and stderr.tell() <= LIMIT)
        stdout.seek(0)
        output = decode(stdout.read(LIMIT + 1))
    verify_verified_output(output, metadata, raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('generate', 'verify', 'prepare', 'verify-live'))
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--index', required=True)
    parser.add_argument('--digest')
    parser.add_argument('--verified-output')
    args = parser.parse_args()
    try:
        if args.mode == 'prepare':
            require(bool(args.digest) and args.verified_output is None)
            metadata = trusted_metadata(args.digest)
            raw = registry_index(args.digest)
            generated = predicate(metadata, raw)
            Path(args.metadata).write_text(json.dumps(metadata, sort_keys=True))
            Path(args.index).write_bytes(raw)
            print(json.dumps(generated, sort_keys=True, separators=(',', ':')))
            return 0
        metadata, raw = decode(read(args.metadata)), read(args.index)
        if args.mode == 'verify-live':
            require(args.digest is None and args.verified_output is None)
            require(trusted_metadata(metadata['indexDigest']) == metadata)
            # Fresh immutable registry read before signature/policy acceptance.
            require(registry_index(metadata['indexDigest'], metadata['release']['tag']) == raw)
            verify_live(metadata, raw)
            print('Release binding: cryptographic and checked identity verification passed')
        elif args.mode == 'generate':
            require(args.verified_output is None)
            print(json.dumps(predicate(metadata, raw), sort_keys=True, separators=(',', ':')))
        else:
            require(bool(args.verified_output))
            verify_verified_output(decode(read(args.verified_output)), metadata, raw)
            print('Release binding policy: verified output matches checked identity')
        return 0
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError, subprocess.SubprocessError):
        print('Release binding policy rejected; no success inferred', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
