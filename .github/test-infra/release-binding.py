#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline release-binding policy; consumes trusted checked metadata, never API writes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
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
    require(type(output) is list and len(output) == 1)
    result = output[0]['verificationResult']
    certificate = result['signature']['certificate']
    workflow = metadata['workflow']
    identity = WORKFLOW + '@' + workflow['ref']
    for key, value in {
        'issuer': 'https://token.actions.githubusercontent.com',
        'subjectAlternativeName': identity, 'buildSignerURI': identity,
        'buildSignerDigest': workflow['commit'],
        'sourceRepositoryURI': REPOSITORY, 'sourceRepositoryDigest': workflow['commit'],
        'sourceRepositoryIdentifier': '1427088300',
        'sourceRepositoryOwnerIdentifier': '5193877',
        'runInvocationURI': REPOSITORY + '/actions/runs/' + workflow['runID'] + '/attempts/' + workflow['runAttempt'],
    }.items():
        require(certificate.get(key) == value)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('generate', 'verify'))
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--index', required=True)
    parser.add_argument('--verified-output')
    args = parser.parse_args()
    try:
        metadata, raw = decode(read(args.metadata)), read(args.index)
        if args.mode == 'generate':
            require(args.verified_output is None)
            print(json.dumps(predicate(metadata, raw), sort_keys=True, separators=(',', ':')))
        else:
            require(bool(args.verified_output))
            verify_verified_output(decode(read(args.verified_output)), metadata, raw)
            print('Release binding policy: verified output matches checked identity')
        return 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        print('Release binding policy rejected; no success inferred', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
