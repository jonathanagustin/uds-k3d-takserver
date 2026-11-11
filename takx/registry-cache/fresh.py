#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Fresh v2 Draco capsule; independent of experimental local producer receipts."""
import gzip
import io
import json
from pathlib import Path
import re
import tarfile
import draco as local

HERE = Path(__file__).resolve().parent
ARTIFACT = 'application/vnd.uds-takserver.draco-cache.v2'
LAYER = ARTIFACT + '+tar+gzip'
CONFIG = 'application/vnd.oci.empty.v1+json'
REGISTRY = 'ghcr.io/jonathanagustin/uds-takserver/native-cache/draco'
PREDICATE = 'https://github.com/jonathanagustin/uds-takserver/attestations/native-component/v2'
IMAGE_MEDIA = 'application/vnd.oci.image.manifest.v1+json'
INDEX_MEDIA = 'application/vnd.oci.image.index.v1+json'


def key(identity):
    validate_identity(identity)
    return 'registry-v2-' + local.sha(local.canonical(identity))


def validate_identity(identity):
    lock = local.load(HERE / 'producer.lock.json')
    fields = {'schema', 'base_image', 'base_image_config', 'source', 'source_inventory_sha256', 'patches',
              'dependency_digests', 'recipes', 'tools', 'abi', 'configure_command', 'compile_commands', 'environment'}
    if (set(identity) != fields or identity.get('base_image_config') != lock['image_config'] or
            not re.fullmatch('[a-f0-9]{64}', identity.get('source_inventory_sha256', '')) or
            not identity.get('configure_command') or identity.get('environment') !=
            {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC', 'SOURCE_DATE_EPOCH': '1704067200'}):
        raise ValueError('missing fresh source/environment identity')
    if (identity.get('schema') != 'uds-draco-inputs-v2' or identity.get('base_image') != lock['image'] or
            identity.get('source') != lock['source'] or identity.get('dependency_digests') != [] or
            identity.get('patches') != [] or not identity.get('compile_commands') or
            not identity.get('recipes') or not identity.get('tools')):
        raise ValueError('incomplete fresh component identity')
    expected = {'gcc', 'g++', 'cc1', 'cc1plus', 'as', 'ld', 'ar', 'ranlib', 'make', 'cmake', 'python3', 'readelf'}
    if set(identity['tools']) != expected:
        raise ValueError('incomplete actual tool closure')
    for value in identity['tools'].values():
        if not re.fullmatch('[a-f0-9]{64}', value.get('sha256', '')) or not value.get('version'):
            raise ValueError('invalid tool identity')
    abi = identity.get('abi', {})
    if (abi.get('target') != 'x86_64-linux-gnu' or abi.get('pointer_bytes') != '8' or
            abi.get('byte_order') != '__ORDER_LITTLE_ENDIAN__' or abi.get('cxx11_abi') != '1' or
            abi.get('exceptions') != '1' or abi.get('rtti') != '1' or not abi.get('glibc') or
            not abi.get('cxx_standard') or not abi.get('providers')):
        raise ValueError('incomplete actual ABI observation')


def pack(prefix, identity, qualification, output):
    if output.exists():
        raise ValueError('capsule must be new')
    files = {}
    for p in sorted(prefix.rglob('*')):
        name = 'prefix/' + str(p.relative_to(prefix))
        if p.is_file() and local.allowed(name):
            s = local.regular(p, prefix)
            if s.st_mode & 0o111:
                raise ValueError('executable capsule input')
            files[name] = p.read_bytes()
    if not local.FIXED <= files.keys() or len(files) != 207:
        raise ValueError('incomplete pinned projection')
    manifest = {'schema': 'uds-draco-capsule-v2', 'input_key': key(identity), 'identity': identity,
                'qualification': qualification,
                'files': {n: {'bytes': len(v), 'sha256': local.sha(v), 'mode': 0o644}
                          for n, v in sorted(files.items())}}
    files['manifest.json'] = local.canonical(manifest)
    if len(files['manifest.json']) > local.MAX_JSON or sum(map(len, files.values())) > local.MAX_EXPANDED:
        raise ValueError('capsule expansion exceeds quota')
    with output.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(files.items()):
                item = tarfile.TarInfo(name)
                item.size, item.mode, item.mtime = len(data), 0o644, 0
                archive.addfile(item, io.BytesIO(data))
    return verify(output, local.file_sha(output), manifest['input_key'])[0]


def verify(capsule, expected_sha, expected_key):
    if (capsule.is_symlink() or not re.fullmatch('[a-f0-9]{64}', expected_sha) or
            capsule.stat().st_size > local.MAX_COMPRESSED or local.file_sha(capsule) != expected_sha):
        raise ValueError('capsule identity differs')
    with gzip.open(capsule, 'rb') as stream:
        expanded = stream.read(local.MAX_EXPANDED + 2 * 1024**2 + 1)
    if len(expanded) > local.MAX_EXPANDED + 2 * 1024**2:
        raise ValueError('tar expansion exceeds quota')
    files, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for item in archive:
            name = local.safe(item.name)
            if (not item.isfile() or item.mode != 0o644 or item.pax_headers or name in files or
                    item.size < 0 or (name != 'manifest.json' and not local.allowed(name))):
                raise ValueError('unapproved capsule entry')
            total += item.size
            if total > local.MAX_EXPANDED or len(files) >= local.MAX_FILES or (name == 'manifest.json' and item.size > local.MAX_JSON):
                raise ValueError('capsule quota exceeded')
            files[name] = archive.extractfile(item).read(item.size + 1)
            if len(files[name]) != item.size:
                raise ValueError('short archive entry')
    manifest = local.decode(files.pop('manifest.json'))
    if (set(manifest) != {'schema', 'input_key', 'identity', 'qualification', 'files'} or
            manifest['schema'] != 'uds-draco-capsule-v2' or key(manifest['identity']) != expected_key or
            manifest['input_key'] != expected_key or len(files) != 207 or not local.FIXED <= files.keys() or
            set(files) != set(manifest['files'])):
        raise ValueError('capsule contract differs')
    q = manifest['qualification']
    if (set(q) != {'fresh_source_build', 'codec', 'pic', 'object_count', 'archive_object_sha256', 'runtime_providers'} or
            q['fresh_source_build'] is not True or q['codec'] is not True or q['pic'] is not True or
            not q['object_count'] or not q['archive_object_sha256'] or not q['runtime_providers']):
        raise ValueError('missing native qualification evidence')
    for name, data in files.items():
        if manifest['files'][name] != {'bytes': len(data), 'sha256': local.sha(data), 'mode': 0o644}:
            raise ValueError('payload identity differs')
    return manifest, files


def restore(capsule, digest, input_key, output):
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.absolute().parents):
        raise ValueError('restore needs new ordinary prefix')
    manifest, files = verify(capsule, digest, input_key)
    output.mkdir(parents=True)
    for name, data in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o644)
    return manifest


def layout(capsule, digest, input_key, output):
    manifest, _ = verify(capsule, digest, input_key)
    if output.exists():
        raise ValueError('layout needs new output')
    (output / 'blobs/sha256').mkdir(parents=True)
    def blob(data):
        h = local.sha(data)
        (output / 'blobs/sha256' / h).write_bytes(data)
        return {'digest': 'sha256:' + h, 'size': len(data)}
    config = dict(blob(b'{}'), mediaType=CONFIG)
    layer = dict(blob(capsule.read_bytes()), mediaType=LAYER)
    oci = {'schemaVersion': 2, 'mediaType': IMAGE_MEDIA, 'artifactType': ARTIFACT,
           'config': config, 'layers': [layer],
           'annotations': {'org.opencontainers.image.source': 'https://github.com/jonathanagustin/uds-takserver',
                           'io.uds-takserver.input-key': input_key}}
    subject = dict(blob(local.canonical(oci)), mediaType=IMAGE_MEDIA)
    (output / 'index.json').write_bytes(local.canonical({'schemaVersion': 2, 'mediaType': INDEX_MEDIA,
                                                       'manifests': [subject]}))
    (output / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}\n')
    return subject['digest']
