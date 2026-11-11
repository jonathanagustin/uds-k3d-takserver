#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Package the two existing charts from a validated release tag; no app deployment."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

import yaml

CHARTS = {'takserver': 'uds-takserver-config', 'cloudtak': 'uds-cloudtak'}
SOURCE = 'https://github.com/jonathanagustin/uds-takserver'
MEDIA = 'application/vnd.cncf.helm.chart.content.v1.tar+gzip'


def run(args, cwd=None, env=None, check=True):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.strip()}')
    return result


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def release(repo, tag, main_ref, expected_source=""):
    if expected_source and not re.fullmatch(r'[0-9a-f]{40}', expected_source):
        raise ValueError('Expected an exact release source SHA')
    if not re.fullmatch(r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', tag):
        raise ValueError('Expected an existing stable vMAJOR.MINOR.PATCH tag')
    revision = run(['git', 'rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}'], repo).stdout.strip()
    if expected_source and revision != expected_source:
        raise ValueError('Release tag does not match the expected source SHA')
    run(['git', 'merge-base', '--is-ancestor', revision, main_ref], repo)
    manifest = json.loads(run(['git', 'show', f'{revision}:.release-please-manifest.json'], repo).stdout)
    if manifest.get('.') != tag[1:]:
        raise ValueError('Tag and Release Please manifest version differ')
    timestamp = int(run(['git', 'show', '-s', '--format=%ct', revision], repo).stdout)
    return revision, timestamp


def normalize(archive, timestamp):
    output = io.BytesIO()
    with tarfile.open(archive, 'r:gz') as source, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as target:
            for member in sorted(source.getmembers(), key=lambda item: item.name):
                if not member.isfile() and not member.isdir():
                    raise ValueError('Unexpected chart archive link or special file')
                member.uid = member.gid = 0
                member.uname = member.gname = ''
                member.mtime = timestamp
                member.pax_headers = {}
                target.addfile(member, source.extractfile(member) if member.isfile() else None)
    archive.write_bytes(output.getvalue())


def prepare(repo, revision, timestamp, version, output):
    archives = []
    with tempfile.TemporaryDirectory(prefix='helm-source-') as temporary:
        stage = Path(temporary)
        archive = subprocess.check_output(['git', 'archive', revision, 'charts/takserver', 'charts/cloudtak', 'LICENSE'], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            for member in source.getmembers():
                name = PurePosixPath(member.name)
                if name.is_absolute() or '..' in name.parts or not (member.name == 'LICENSE' or member.name == 'charts' or name.parts[:2] in (('charts', 'takserver'), ('charts', 'cloudtak'))):
                    raise ValueError('Unsafe chart source archive path')
                if not member.isfile() and not member.isdir():
                    raise ValueError('Chart source must contain only ordinary files/directories')
            source.extractall(stage, filter='data')
        for directory, expected_name in CHARTS.items():
            chart = stage / 'charts' / directory
            license_bytes = (stage / 'LICENSE').read_bytes()
            if (chart / 'LICENSE').exists() and (chart / 'LICENSE').read_bytes() != license_bytes:
                raise ValueError('Chart has a distinct license; explicit review required')
            (chart / 'LICENSE').write_bytes(license_bytes)
            metadata_path = chart / 'Chart.yaml'
            metadata = yaml.safe_load(metadata_path.read_text())
            if metadata.get('name') != expected_name:
                raise ValueError('Unexpected chart identity')
            annotations = metadata.setdefault('annotations', {})
            annotations.update({'org.opencontainers.image.source': SOURCE,
                                'org.opencontainers.image.revision': revision,
                                'org.opencontainers.image.url': f'{SOURCE}/tree/v{version}/charts/{directory}',
                                'org.opencontainers.image.licenses': 'GPL-3.0-only'})
            metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False))
            run(['helm', 'package', str(chart), '--version', version, '--destination', str(output)])
            packaged = output / f'{expected_name}-{version}.tgz'
            normalize(packaged, timestamp)
            with tarfile.open(packaged, 'r:gz') as bundle:
                if bundle.extractfile(f'{expected_name}/LICENSE').read() != license_bytes:
                    raise ValueError('Packaged chart omits or changes the release license')
            archives.append((expected_name, packaged))
    return archives


def existing(reference, plain_http=False, env=None):
    command = ['crane', 'manifest', reference]
    if plain_http:
        command.append('--insecure')
    result = run(command, env=env, check=False)
    if result.returncode:
        if re.search(r'\b(?:UNAUTHORIZED|DENIED|401|403)\b', result.stderr):
            raise RuntimeError('Registry authentication/authorization failed; refusing publication')
        if re.search(r'\b(?:MANIFEST_UNKNOWN|NAME_UNKNOWN|404)\b', result.stderr):
            return None
        raise RuntimeError(f'Registry inspection failed closed: {result.stderr.strip()}')
    manifest = json.loads(result.stdout)
    digest = run(['crane', 'digest', reference, *(['--insecure'] if plain_http else [])], env=env).stdout.strip()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Invalid immutable OCI digest')
    return manifest, digest


def match_existing(record, archive, revision):
    manifest, digest = record
    layers = [layer for layer in manifest.get('layers', []) if layer.get('mediaType') == MEDIA]
    annotations = manifest.get('annotations', {})
    if len(layers) != 1 or layers[0].get('digest') != sha(archive.read_bytes()):
        raise ValueError('Immutable chart version collision: packaged bytes differ')
    directory = next((directory for directory, name in CHARTS.items() if archive.name.startswith(name + '-')), None)
    if directory is None:
        raise ValueError('Unexpected packaged chart name')
    chart_name = CHARTS[directory]
    version = archive.name[len(chart_name) + 1:-4]
    expected = {'org.opencontainers.image.source': SOURCE, 'org.opencontainers.image.revision': revision,
                'org.opencontainers.image.url': f'{SOURCE}/tree/v{version}/charts/{directory}',
                'org.opencontainers.image.licenses': 'GPL-3.0-only'}
    if any(annotations.get(key) != value for key, value in expected.items()):
        raise ValueError('Immutable chart version collision: source annotations differ')
    return digest


def verify_pull(reference, digest, archive, plain_http, anonymous=False):
    with tempfile.TemporaryDirectory(prefix='helm-verify-') as temporary:
        root = Path(temporary)
        env = dict(os.environ)
        extra = ['--plain-http'] if plain_http else []
        if anonymous:
            (root / 'config.json').write_text('{"auths":{}}')
            env['DOCKER_CONFIG'] = temporary
            env['HELM_REGISTRY_CONFIG'] = str(root / 'config.json')
            extra += ['--registry-config', str(root / 'config.json')]
        run(['helm', 'pull', f'oci://{reference.rsplit(":", 1)[0]}@{digest}',
             '--destination', temporary, *extra], env=env)
        pulled = list(root.glob('*.tgz'))
        if len(pulled) != 1 or pulled[0].read_bytes() != archive.read_bytes():
            raise ValueError('Pulled immutable chart differs from expected package')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--tag', required=True)
    parser.add_argument('--main-ref', default='origin/main')
    parser.add_argument('--source-sha', default='', help='Expected source SHA from Release Please')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registry', default='ghcr.io/jonathanagustin/uds-takserver/charts')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--plain-http', action='store_true', help='Local registry test only')
    args = parser.parse_args()
    if args.plain_http and not re.fullmatch(r'(?:localhost|127\.0\.0\.1):[0-9]+/[a-zA-Z0-9/_-]+', args.registry):
        parser.error('Plain HTTP is restricted to an explicit loopback test registry')
    if not args.plain_http and args.registry != 'ghcr.io/jonathanagustin/uds-takserver/charts':
        parser.error('Unexpected production registry')
    revision, timestamp = release(args.repo, args.tag, args.main_ref, args.source_sha)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archives = prepare(args.repo, revision, timestamp, args.tag[1:], output)
    results = []
    if args.publish:
        # Check both charts before publishing either. Workflow concurrency serializes tag publishers.
        preflight = {name: existing(f'{args.registry}/{name}:{args.tag[1:]}', args.plain_http) for name, _ in archives}
        for name, archive in archives:
            if preflight[name]:
                match_existing(preflight[name], archive, revision)
        for name, archive in archives:
            reference = f'{args.registry}/{name}:{args.tag[1:]}'
            current = existing(reference, args.plain_http)
            if current:
                digest = match_existing(current, archive, revision)
            else:
                run(['helm', 'push', str(archive), f'oci://{args.registry}', *(['--plain-http'] if args.plain_http else [])])
                published = existing(reference, args.plain_http)
                if not published:
                    raise ValueError('Published chart is not readable')
                digest = match_existing(published, archive, revision)
            verify_pull(reference, digest, archive, args.plain_http)
            # Public availability is an actual credential-free pull, not an assumption about package linking.
            verify_pull(reference, digest, archive, args.plain_http, anonymous=True)
            results.append({'name': reference.rsplit(':', 1)[0], 'digest': digest, 'source': revision})
    (output / 'published.json').write_text(json.dumps(results, indent=2) + '\n')
    (output / 'subjects.txt').write_text(''.join(f'{item["digest"][7:]}  {item["name"]}\n' for item in results))
    print(json.dumps({'tag': args.tag, 'revision': revision, 'charts': results}, indent=2))


if __name__ == '__main__':
    main()
