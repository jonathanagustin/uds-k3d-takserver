#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Read allowlisted install identities from the actual generated OCI bundle."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time

SPEC = importlib.util.spec_from_file_location('checkpoint_identity',
                                            Path(__file__).with_name('checkpoint-identity.py'))
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)
require = checkpoint.require
TITLE = 'org.opencontainers.image.title'
IMAGE_NAME = 'org.opencontainers.image.base.name'
REGISTRY = 'ghcr.io/jonathanagustin/uds-takserver/'
IMAGES = {'takserver-api', 'takserver-messaging', 'takserver-config',
          'takserver-plugins', 'takserver-database-setup', 'takserver-ignite', 'cloudtak', 'postgis'}
MAX_METADATA = 32 * 1024 * 1024
IMAGE_MANIFESTS = {checkpoint.MANIFEST, 'application/vnd.docker.distribution.manifest.v2+json'}
IMAGE_CONFIGS = {'application/vnd.oci.image.config.v1+json',
                 'application/vnd.docker.container.image.v1+json'}


def metadata(archive):
    """Never extract archive paths, image contents, config values or secrets."""
    result = {}
    retained = 0
    scanned = 0
    start = time.monotonic()
    process = subprocess.Popen(['zstd', '-dc', '--', str(archive)], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as bundle:
            for count, member in enumerate(bundle):
                scanned += member.size
                require(count < 100000 and scanned <= 32 * 1024**3 and
                        time.monotonic() - start < 90)
                name = member.name.removeprefix('./')
                if not (name == 'index.json' or re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', name)):
                    continue
                require(member.isfile())
                if member.size > checkpoint.MAX_JSON:
                    continue
                stream = bundle.extractfile(member)
                prefix = stream.read(min(member.size, 128))
                # OCI manifests/indexes are schemaVersion=2 JSON. Configs are
                # also needed to validate package names and image architecture.
                if not prefix.lstrip().startswith(b'{'):
                    continue
                data = prefix + stream.read()
                try:
                    value = json.loads(data)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                require(name not in result)
                if name.startswith('blobs/'):
                    require(hashlib.sha256(data).hexdigest() == name.rsplit('/', 1)[1])
                retained += len(data)
                require(retained <= MAX_METADATA)
                result[name] = data
        require(process.wait(timeout=5) == 0)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()
    return result


def blob(objects, descriptor):
    checkpoint.descriptor(descriptor)
    data = objects['blobs/sha256/' + descriptor['digest'].split(':')[1]]
    require(len(data) == descriptor['size'] and checkpoint.sha(data) == descriptor['digest'])
    value = json.loads(data)
    require(isinstance(value, dict))
    return value


def manifest(objects, descriptor, package=False):
    value = blob(objects, descriptor)
    require(value.get('schemaVersion') == 2 and value.get('mediaType') in
            ({checkpoint.MANIFEST} if package else IMAGE_MANIFESTS))
    checkpoint.descriptor(value.get('config', {}))
    require(isinstance(value.get('layers'), list) and 0 < len(value['layers']) <= 10000)
    for layer in value['layers']:
        checkpoint.descriptor(layer)
        if package:
            require(layer['mediaType'] == 'application/vnd.zarf.layer.v1.blob')
    return value


def identities(objects, arch, package_digest):
    index = json.loads(objects['index.json'])
    require(isinstance(index, dict) and index.get('schemaVersion') == 2 and
            index.get('mediaType') == checkpoint.INDEX and
            isinstance(index.get('manifests'), list) and len(index['manifests']) == 1)
    root = blob(objects, index['manifests'][0])
    require(root.get('schemaVersion') == 2 and root.get('mediaType') == checkpoint.MANIFEST and
            isinstance(root.get('layers'), list))
    root_config = blob(objects, root['config'])
    require(root_config.get('annotations', {}).get(TITLE) == 'takserver-dev' and
            root_config.get('architecture') == arch)
    packages = {}
    for layer in root['layers']:
        checkpoint.descriptor(layer)
        if layer.get('annotations', {}).get(TITLE) in ('uds-bundle.yaml', 'uds-bundle.yaml.sig'):
            continue
        value = blob(objects, layer)
        name = value.get('annotations', {}).get(TITLE)
        if name not in ('core-base', 'takserver'):
            continue
        require(name not in packages)
        package = manifest(objects, layer, package=True)
        require(package['config']['mediaType'] == 'application/vnd.zarf.config.v1+json')
        config = blob(objects, package['config'])
        require(config.get('kind') == 'ZarfPackageConfig' and
                config.get('metadata', {}).get('name') == name and
                config['metadata'].get('architecture') == arch)
        packages[name] = (layer['digest'], package)
    require(set(packages) == {'core-base', 'takserver'})
    require(packages['takserver'][0] == package_digest)
    app = packages['takserver'][1]
    image_indexes = [layer for layer in app['layers']
                     if layer.get('annotations', {}).get(TITLE) == 'images/index.json']
    require(len(image_indexes) == 1)
    images = blob(objects, image_indexes[0])
    require(images.get('schemaVersion') == 2 and images.get('mediaType') == checkpoint.INDEX and
            isinstance(images.get('manifests'), list))
    known = {layer['digest']: layer for layer in app['layers']}
    result = {}
    for image in images['manifests']:
        checkpoint.descriptor(image)
        ref = image.get('annotations', {}).get(IMAGE_NAME, '')
        if not isinstance(ref, str) or not ref.startswith(REGISTRY):
            continue
        name = ref[len(REGISTRY):].split(':', 1)[0].split('@', 1)[0]
        if name not in IMAGES:
            continue
        require(name not in result and image['digest'] in known)
        image_manifest = manifest(objects, image)
        require(image_manifest['config']['mediaType'] in IMAGE_CONFIGS and
                image_manifest['config']['digest'] in known)
        config = blob(objects, image_manifest['config'])
        require(config.get('architecture') == arch and config.get('os') == 'linux')
        require(all(layer['digest'] in known for layer in image_manifest['layers']))
        result[name] = image['digest']
    require(set(result) == IMAGES)
    return {'core_oci_digest': packages['core-base'][0], 'image_digests': result}
