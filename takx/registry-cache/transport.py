#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded OCI publication and authenticated readback for one fresh Draco cache."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import draco as local
import fresh
import producer

REPO = 'jonathanagustin/uds-takserver'
WORKFLOW = REPO + '/.github/workflows/native-cache.yaml'


def context(env):
    if (env.get('GITHUB_REPOSITORY') != REPO or env.get('GITHUB_REF') != 'refs/heads/main' or
            env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch' or
            not re.fullmatch('[a-f0-9]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch('[0-9]+', env.get('GITHUB_RUN_ID', ''))):
        raise ValueError('publication requires the fixed protected-main manual workflow')
    return env['GITHUB_SHA'], env['GITHUB_RUN_ID']


def command(args, output, name, env=None):
    return producer.run(args, output, name, 120, env)


def inspect(reference, output, name, env=None):
    try:
        data = command(['crane','manifest',reference], output, name, env)
    except ValueError:
        # Only a definitive missing object is a cache miss. Never classify an
        # authentication/network failure as permission to publish over it.
        error = (output / (name + '.log')).read_bytes()
        if re.search(rb'\b(?:401|403|UNAUTHORIZED|DENIED)\b', error):
            raise ValueError('registry access denied') from None
        if re.search(rb'\b(?:404|MANIFEST_UNKNOWN|NAME_UNKNOWN)\b', error):
            return None
        raise
    return local.decode(data)


def expected_oci(value, digest, capsule_sha, input_key):
    if (value.get('schemaVersion') != 2 or value.get('mediaType') != fresh.IMAGE_MEDIA or
            value.get('artifactType') != fresh.ARTIFACT or
            value.get('config') != {'mediaType': fresh.CONFIG, 'digest': 'sha256:' + local.sha(b'{}'), 'size': 2} or
            len(value.get('layers', [])) != 1 or
            value['layers'][0].get('mediaType') != fresh.LAYER or
            value['layers'][0].get('digest') != 'sha256:' + capsule_sha or
            not 0 < value['layers'][0].get('size', 0) <= local.MAX_COMPRESSED or
            value.get('annotations',{}).get('io.uds-takserver.input-key') != input_key or
            value.get('annotations',{}).get('org.opencontainers.image.source') != 'https://github.com/' + REPO or
            not re.fullmatch('sha256:[a-f0-9]{64}',digest)):
        raise ValueError('OCI subject contract differs')


def stage(inputs, output):
    commit, run_id = context(os.environ)
    if output.exists(): raise ValueError('new publication output required')
    output.mkdir(parents=True)
    receipt = local.load(inputs / 'registry-receipt.json')
    capsule = inputs / 'draco.tar.gz'
    manifest, _ = fresh.verify(capsule, receipt['capsule_sha256'], receipt['input_key'])
    if (receipt.get('schema') != 'uds-draco-fresh-result-v2' or
            receipt['identity'] != manifest['identity'] or receipt['qualification'] != manifest['qualification'] or
            receipt['identity']['recipes'] != producer.recipes()):
        raise ValueError('fresh build receipt and capsule differ')
    if (len(receipt.get('relocated_consumers', [])) != 2 or
            not all(r.get('codec') is True and r.get('pic') is True for r in receipt['relocated_consumers'])):
        raise ValueError('fresh relocated consumers missing')
    digest = fresh.layout(capsule, receipt['capsule_sha256'], receipt['input_key'], output / 'layout')
    tag = receipt['input_key']
    existing = inspect(fresh.REGISTRY + ':' + tag, output, 'existing-key')
    if existing is not None:
        # Do not overwrite a key, including a different source annotation.
        raw = (output / 'layout/blobs/sha256' / digest.split(':')[1]).read_bytes()
        if local.canonical(existing) != raw:
            raise ValueError('immutable input-key collision')
    reference = fresh.REGISTRY + ':staging-' + run_id
    command(['crane','push',str(output / 'layout'),reference], output, 'push')
    actual = command(['crane','digest',reference], output, 'pushed-digest').decode().strip()
    if actual != digest:
        raise ValueError('pushed manifest digest differs')
    qualification = {'schema': 'uds-draco-qualification-v2', 'repository': REPO, 'source_commit': commit,
                     'workflow': WORKFLOW, 'run_id': run_id, 'subject_digest': digest,
                     'capsule_sha256': receipt['capsule_sha256'], 'input_key': tag,
                     'identity': receipt['identity'], 'native_qualification': receipt['qualification'],
                     'relocated_consumers': receipt['relocated_consumers']}
    (output / 'qualification.json').write_bytes(local.canonical(qualification))
    (output / 'subjects.txt').write_text(digest.split(':')[1] + ' ' + fresh.REGISTRY + '\n')
    (output / 'publication.json').write_bytes(local.canonical(qualification))
    return qualification


def verified_statements(results, predicate_type, expected, digest):
    statements = []
    for result in results:
        statement = result.get('verificationResult',{}).get('statement',{})
        subjects = statement.get('subject', [])
        if (statement.get('predicateType') == predicate_type and
                any(s.get('digest',{}).get('sha256') == digest.split(':')[1] for s in subjects)):
            statements.append(statement)
    if not statements or (expected is not None and not any(s.get('predicate') == expected for s in statements)):
        raise ValueError('authenticated subject/predicate differs')


def verify_attestations(q, output, env, commit):
    if not re.fullmatch('[a-f0-9]{40}', commit): raise ValueError('exact approved producer commit required')
    if q['source_commit'] != commit or q['repository'] != REPO or q['workflow'] != WORKFLOW:
        raise ValueError('unexpected trusted producer identity')
    reference = 'oci://' + fresh.REGISTRY + '@' + q['subject_digest']
    common = ['gh','attestation','verify',reference,'--repo',REPO,'--signer-workflow',WORKFLOW,
              '--source-digest',commit,'--signer-digest',commit,'--source-ref','refs/heads/main',
              '--deny-self-hosted-runners','--format','json']
    for i, (kind, expected) in enumerate((('https://slsa.dev/provenance/v1',None), (fresh.PREDICATE,q))):
        results = local.decode(command([*common,'--predicate-type',kind], output, 'verify-attestation-' + str(i), env))
        verified_statements(results, kind, expected, q['subject_digest'])


def readback(q, output, trusted_source):
    if output.exists(): raise ValueError('new readback output required')
    output.mkdir(parents=True)
    # Registry data and attestation lookups use no saved registry credentials.
    # GH_TOKEN is only consumed by gh for GitHub's attestation API.
    with tempfile.TemporaryDirectory(prefix='draco-anonymous-') as temporary:
        Path(temporary,'config.json').write_text('{"auths":{}}')
        env = dict(os.environ, DOCKER_CONFIG=temporary)
        verify_attestations(q, output, env, trusted_source)
        reference = fresh.REGISTRY + '@' + q['subject_digest']
        raw = command(['crane','manifest',reference], output, 'anonymous-manifest', env)
        if local.sha(raw) != q['subject_digest'].split(':')[1]:
            if not raw.endswith(b'\n') or local.sha(raw[:-1]) != q['subject_digest'].split(':')[1]:
                raise ValueError('anonymous manifest digest differs')
        value = local.decode(raw)
        expected_oci(value,q['subject_digest'],q['capsule_sha256'],q['input_key'])
        for i, desc in enumerate([value['config'], *value['layers']]):
            data = command(['crane','blob',fresh.REGISTRY + '@' + desc['digest']], output, 'anonymous-blob-' + str(i), env)
            if len(data) != desc['size'] or 'sha256:' + local.sha(data) != desc['digest']:
                raise ValueError('anonymous OCI blob differs')
            if i == 1: (output / 'draco.tar.gz').write_bytes(data)
        manifest, _ = fresh.verify(output / 'draco.tar.gz', q['capsule_sha256'], q['input_key'])
        if manifest['identity'] != q['identity'] or manifest['qualification'] != q['native_qualification']:
            raise ValueError('signed qualification and fetched capsule differ')
        (output / 'registry-receipt.json').write_bytes(local.canonical(q))
    return q


def validate_consumer(receipt, q):
    if (receipt.get('schema') != 'uds-draco-registry-consumer-v2' or
            receipt.get('input_key') != q['input_key'] or receipt.get('capsule_sha256') != q['capsule_sha256'] or
            receipt.get('identity_sha256') != local.sha(local.canonical(q['identity'])) or
            len(receipt.get('results', [])) != 2 or
            not all(r.get('codec') is True and r.get('pic') is True for r in receipt['results'])):
        raise ValueError('authenticated exact-capsule two-prefix consumers missing')


def promote(q, read_output, output):
    commit, _ = context(os.environ)
    if output.exists(): raise ValueError('new promotion output required')
    output.mkdir(parents=True)
    receipt = local.load(read_output / 'consumer/restored.json')
    validate_consumer(receipt, q)
    manifest, _ = fresh.verify(read_output / 'draco.tar.gz',q['capsule_sha256'],q['input_key'])
    if manifest['identity'] != q['identity']: raise ValueError('consumer bytes differ')
    verify_attestations(q, output, os.environ, commit)
    current = inspect(fresh.REGISTRY + ':' + q['input_key'], output, 'promotion-preflight')
    if current is not None:
        digest = command(['crane','digest',fresh.REGISTRY + ':' + q['input_key']],output,'existing-key-digest').decode().strip()
        if digest != q['subject_digest']: raise ValueError('immutable input-key collision')
    command(['crane','tag',fresh.REGISTRY + '@' + q['subject_digest'],q['input_key']],output,'promote')
    actual = command(['crane','digest',fresh.REGISTRY + ':' + q['input_key']],output,'promoted-digest').decode().strip()
    if actual != q['subject_digest']: raise ValueError('promoted key digest differs')
    accepted = {'schema': 'uds-draco-registry-accepted-v2', 'subject_digest': actual,
                'input_key': q['input_key'], 'capsule_sha256': q['capsule_sha256'],
                'trusted_source_commit': commit, 'authenticated': True, 'anonymous_readback': True,
                'consumer_receipt_sha256': local.file_sha(read_output / 'consumer/restored.json')}
    (output / 'accepted.json').write_bytes(local.canonical(accepted))
    return accepted


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command',required=True)
    a = commands.add_parser('stage'); a.add_argument('--input',type=Path,required=True); a.add_argument('--output',type=Path,required=True)
    for name in ('readback','promote'):
        a = commands.add_parser(name); a.add_argument('--publication',type=Path,required=True); a.add_argument('--output',type=Path,required=True)
        if name == 'promote': a.add_argument('--readback',type=Path,required=True)
        else: a.add_argument('--trusted-source-sha',required=True)
    args = p.parse_args()
    if args.command == 'stage': result = stage(args.input,args.output)
    else:
        q = local.load(args.publication)
        if args.command == 'readback': result = readback(q,args.output,args.trusted_source_sha)
        else: result = promote(q,args.readback,args.output)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__': main()
