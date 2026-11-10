#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Optional checkpoint acquisition evidence; never authorizes a cache hit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile

MAX_JSON = 1024 * 1024
REPOSITORIES = {'ghcr.io/defenseunicorns/dev/uds/checkpoints/k3d-core-slim-dev',
                'ghcr.io/jonathanagustin/uds-takserver/checkpoints/k3d-core-slim-dev'}
INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'


def require(value):
    if not value:
        raise ValueError('unproven checkpoint identity')


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def descriptor(value):
    require(isinstance(value, dict) and
            re.fullmatch(r'sha256:[a-f0-9]{64}', value.get('digest', '')) and
            type(value.get('size')) is int and 0 < value['size'] <= 64 * 1024**3 and
            isinstance(value.get('mediaType'), str))
    return value


def decode(data):
    require(len(data) <= MAX_JSON)
    value = json.loads(data)
    require(isinstance(value, dict) and value.get('schemaVersion') == 2)
    return value


def resolve(index_bytes, manifest_bytes, index_digest, arch):
    require(sha(index_bytes) == index_digest)
    index = decode(index_bytes)
    require(index.get('mediaType') == INDEX and isinstance(index.get('manifests'), list) and
            all(isinstance(item, dict) for item in index['manifests']))
    matches = [descriptor(item) for item in index['manifests']
               if item.get('platform') == {'architecture': arch, 'os': 'multi'}]
    require(len(matches) == 1)
    selected = matches[0]
    require(selected['mediaType'] == MANIFEST and selected['size'] == len(manifest_bytes) and
            selected['digest'] == sha(manifest_bytes))
    manifest = decode(manifest_bytes)
    require(manifest.get('mediaType') == MANIFEST)
    require(descriptor(manifest.get('config', {}))['mediaType'] == 'application/vnd.zarf.config.v1+json')
    require(isinstance(manifest.get('layers'), list) and 0 < len(manifest['layers']) <= 10000)
    require(all(descriptor(item)['mediaType'] == 'application/vnd.zarf.layer.v1.blob'
                for item in manifest['layers']))
    return selected['digest']


def archive_hash(archive):
    hasher = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return 'sha256:' + hasher.hexdigest()


def validate(value, archive, source, version, arch):
    require(source in REPOSITORIES and arch in ('amd64', 'arm64') and
            re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) and
            archive.name == f'zarf-package-k3d-core-slim-dev-{arch}-{version}.tar.zst')
    require(isinstance(value, dict) and set(value) ==
            {'schema_version', 'source', 'version', 'architecture', 'archive_sha256',
             'index_digest', 'manifest_digest'})
    require(value['schema_version'] == 1 and value['source'] == source and
            value['version'] == version and value['architecture'] == arch and
            value['archive_sha256'] == archive_hash(archive))
    require(all(isinstance(value[key], str) and re.fullmatch(r'sha256:[a-f0-9]{64}', value[key])
                for key in ('index_digest', 'manifest_digest')))
    return value


def fetch(command, ref):
    # Bound both command time and output written by the registry client.
    def limit_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_JSON, MAX_JSON))
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([*command, 'tools', 'registry', 'manifest', ref],
                                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                timeout=8, check=False, preexec_fn=limit_output)
        require(result.returncode == 0)
        output.seek(0)
        data = output.read(MAX_JSON + 1)
        require(len(data) <= MAX_JSON)
        return data


def acquire(archive, source, version, arch, index_digest, command):
    require(source in REPOSITORIES and isinstance(index_digest, str) and
            re.fullmatch(r'sha256:[a-f0-9]{64}', index_digest))
    index_bytes = fetch(command, f'{source}@{index_digest}')
    index = decode(index_bytes)
    require(sha(index_bytes) == index_digest and index.get('mediaType') == INDEX and
            isinstance(index.get('manifests'), list) and
            all(isinstance(item, dict) for item in index['manifests']))
    matches = [descriptor(item) for item in index.get('manifests', [])
               if item.get('platform') == {'architecture': arch, 'os': 'multi'}]
    require(len(matches) == 1)
    manifest_bytes = fetch(command, f"{source}@{matches[0]['digest']}")
    manifest_digest = resolve(index_bytes, manifest_bytes, index_digest, arch)
    return validate({'schema_version': 1, 'source': source, 'version': version,
                     'architecture': arch, 'archive_sha256': archive_hash(archive),
                     'index_digest': index_digest, 'manifest_digest': manifest_digest},
                    archive, source, version, arch)


class OmissionParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Checkpoint acquisition identity omitted: invalid arguments\n')


def main():
    parser = OmissionParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--architecture', required=True)
    parser.add_argument('--digest')
    parser.add_argument('--selection-output', type=Path)
    parser.add_argument('--registry-command', nargs='+')
    args = parser.parse_args()
    sidecar = Path(str(args.archive) + '.receipt.json')
    try:
        if args.registry_command:
            value = acquire(args.archive, args.source, args.version, args.architecture,
                            args.digest, args.registry_command)
            # Same-directory atomic publication: interrupted acquisition leaves no partial proof.
            with tempfile.NamedTemporaryFile(mode='w', dir=sidecar.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(value, output, sort_keys=True)
                output.write('\n')
            temporary.replace(sidecar)
        else:
            require(sidecar.stat().st_size <= 4096)
            value = validate(json.loads(sidecar.read_bytes()), args.archive,
                             args.source, args.version, args.architecture)
            require(args.digest is None or value['index_digest'] == args.digest)
        if args.selection_output:
            run_id, attempt = os.environ.get('GITHUB_RUN_ID', ''), os.environ.get('GITHUB_RUN_ATTEMPT', '')
            require(all(re.fullmatch(r'[1-9][0-9]*', item) for item in (run_id, attempt)))
            selection = {'archive': str(args.archive.resolve()), 'acquisition': value,
                         'run_id': int(run_id), 'attempt': int(attempt)}
            with args.selection_output.open('x') as output:
                json.dump(selection, output, sort_keys=True)
                output.write('\n')
            with Path(os.environ['GITHUB_ENV']).open('a') as output:
                output.write('INSTALL_RECEIPT_CHECKPOINT_VALIDATED=true\n')
        print('Checkpoint acquisition identity recorded' if args.registry_command else
              'Checkpoint acquisition identity validated')
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print('Checkpoint acquisition identity omitted: evidence unavailable')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
