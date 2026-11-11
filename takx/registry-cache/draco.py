#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Experimental local Draco projection; neither registry trust nor SDK acceptance."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAX_COMPRESSED = 16 * 1024**2
MAX_EXPANDED = 32 * 1024**2
MAX_FILES = 1000
MAX_JSON = 2 * 1024**2
FIXED = {'prefix/lib/libdraco.a', 'prefix/licenses/draco/LICENSE',
         *('prefix/share/cmake/draco/' + n for n in (
             'draco-config.cmake', 'draco-config-version.cmake',
             'draco-targets.cmake', 'draco-targets-release.cmake'))}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(65536):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def key(identity):
    return 'local-v1-' + sha(canonical(identity))


def safe(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or '..' in p.parts or '\\' in name or
            str(p) != name or any(ord(c) < 32 for c in name)):
        raise ValueError('noncanonical relative path')
    return name


def allowed(name):
    safe(name)
    return name in FIXED or (name.startswith('prefix/include/draco/') and name.endswith('.h'))


def regular(path, root):
    # Inspect each ancestor, rather than following a disguised parent symlink.
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink input refused')
    s = path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_size > MAX_EXPANDED:
        raise ValueError('nonregular or oversized file')
    return s


def decode(data):
    def unique(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError('duplicate JSON key')
            value[name] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def load(path, limit=MAX_JSON):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('oversized or symlink JSON')
    return decode(path.read_bytes())


def native():
    spec = importlib.util.spec_from_file_location('draco_native', ROOT / 'takx/native-deps/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(proof, expected):
    """Observe a pinned local candidate; this is not publisher authentication."""
    if proof.is_symlink() or not proof.is_dir() or file_sha(proof / 'complete.json') != expected:
        raise ValueError('producer receipt differs from caller pin')
    n = native()
    record = load(proof / 'complete.json')
    lock = load(ROOT / 'takx/native-deps/inputs.lock.json')
    n.validate_lock(lock)
    if (record.get('profile') != 'public-native-dependencies' or record.get('schema_version') != 1 or
            record.get('source_revision') != n.REVISION or record.get('draco_version') != '1.5.7' or
            record.get('codec_fixture_probe_passed') is not True or record.get('pic_link_passed') is not True):
        raise ValueError('unsupported or unqualified local producer')
    expected_recipe = {name: file_sha(ROOT / 'takx/native-deps' / name)
                       for name in ('build.py', 'inputs.lock.json', 'DracoSourceProbe.cpp')}
    if record.get('recipe') != expected_recipe:
        raise ValueError('local candidate recipe differs from reviewed recipe')
    sources = load(proof / 'sources.json')
    if file_sha(proof / 'sources.json') != record['source_inventory_sha256'] or len(sources) != 984:
        raise ValueError('source inventory identity differs')
    seen = set()
    for item in sources:
        name = safe(item['path'])
        if not name.startswith('draco/') or name in seen:
            raise ValueError('ambiguous source entry')
        seen.add(name)
        p = proof / 'source' / name
        s = regular(p, proof)
        if s.st_size != item['bytes'] or file_sha(p) != item['sha256']:
            raise ValueError('source postimage differs')
        data = p.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != item['git_blob']:
            raise ValueError('source Git blob differs')
    if len(list((proof / 'source/draco').rglob('*'))) > 2000 or sum(p.is_file() for p in (proof / 'source/draco').rglob('*')) != len(sources):
        raise ValueError('source file set differs')
    if n.inventory(proof / 'install') != record['installed']:
        raise ValueError('installed producer inventory differs')
    n.verify_probe_outputs(proof, record['probe_outputs'])
    for tool in record['tools'].values():
        p = Path(tool['path'])
        if not p.is_file() or file_sha(p) != tool['sha256']:
            raise ValueError('recorded tool changed')
    # The historical producer did not capture an OCI build image, complete ABI,
    # compiler backend or binutils. Preserve that limitation instead of filling
    # historical facts with current host observations.
    identity = {'schema': 'uds-draco-local-inputs-v1', 'component': 'draco', 'version': '1.5.7',
                'source': {'repository': lock['repository'], 'revision': record['source_revision'], 'tree': lock['draco']['tree'],
                           'inventory_sha256': record['source_inventory_sha256'], 'patches': []},
                'recipe': record['recipe'], 'projection_recipe_sha256': file_sha(HERE / 'draco.py'),
                'tools_recorded_by_producer': record['tools'],
                'configure_command': record['configure_command'], 'build_jobs': record['build_jobs'],
                'configured_build_files': {name: file_sha(proof / 'build' / name)
                                           for name in ('CMakeCache.txt', 'build.ninja', 'CMakeFiles/rules.ninja')
                                           if (proof / 'build' / name).is_file()},
                'dependency_oci_digests': [],
                'build_environment_oci_digest': None,
                'target_abi_qualification': 'not-recorded-by-original-producer',
                'historical_backend_binutils_identity': 'not-recorded-by-original-producer',
                'qualification': 'experimental-local-only'}
    return record, identity


def pack(proof, expected, output):
    if (output.exists() or output.is_symlink() or proof.resolve() in output.resolve().parents or
            output.resolve() == proof.resolve()):
        raise ValueError('capsule output must be new and outside original producer')
    record, identity = candidate(proof, expected)
    files = {}
    for item in record['installed']:
        name = 'prefix/' + item['path']
        if allowed(name):
            p = proof / 'install' / item['path']
            s = regular(p, proof)
            if s.st_mode & 0o111:
                raise ValueError('executable payload refused')
            files[name] = p.read_bytes()
    if not FIXED <= files.keys() or not any(n.startswith('prefix/include/draco/') for n in files):
        raise ValueError('incomplete Draco projection')
    entries = {n: {'bytes': len(v), 'sha256': sha(v), 'mode': 0o644} for n, v in sorted(files.items())}
    manifest = {'schema': 'uds-draco-local-capsule-v1', 'qualification': 'experimental-local-only',
                'registry_qualified': False, 'sdk_accepted': False, 'input_key': key(identity),
                'identity': identity, 'producer_receipt_sha256': expected, 'files': entries}
    files['manifest.json'] = canonical(manifest)
    if len(files) > MAX_FILES or len(files['manifest.json']) > MAX_JSON or sum(map(len, files.values())) > MAX_EXPANDED:
        raise ValueError('projection exceeds quota')
    # Stable gzip/tar metadata, without UID/name/time leakage or archive links.
    with output.open('xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    archive.addfile(info, io.BytesIO(data))
    if output.stat().st_size > MAX_COMPRESSED:
        raise ValueError('compressed capsule exceeds quota')
    verify(output, file_sha(output), manifest['input_key'])
    return {'capsule_sha256': file_sha(output), 'input_key': manifest['input_key'],
            'files': len(entries), 'expanded_bytes': sum(e['bytes'] for e in entries.values()),
            'qualification': 'experimental-local-only', 'registry_qualified': False}


def verify(capsule, expected_sha, expected_key):
    if (not re.fullmatch('[a-f0-9]{64}', expected_sha) or capsule.is_symlink() or
            capsule.stat().st_size > MAX_COMPRESSED or file_sha(capsule) != expected_sha):
        raise ValueError('capsule digest or bound differs')
    files, total = {}, 0
    # Bound decompression before tarfile can allocate a GNU/PAX extension.
    with gzip.open(capsule, 'rb') as compressed:
        expanded = compressed.read(MAX_EXPANDED + 2 * 1024**2 + 1)
    if len(expanded) > MAX_EXPANDED + 2 * 1024**2:
        raise ValueError('tar stream exceeds expansion quota')
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for item in archive:
            name = safe(item.name)
            if (name in files or not item.isfile() or item.mode != 0o644 or item.pax_headers or
                    item.size < 0 or item.size > MAX_EXPANDED or
                    (name != 'manifest.json' and not allowed(name))):
                raise ValueError('unapproved archive entry')
            total += item.size
            if total > MAX_EXPANDED or len(files) >= MAX_FILES or (name == 'manifest.json' and item.size > MAX_JSON):
                raise ValueError('archive expansion exceeds quota')
            data = archive.extractfile(item).read(item.size + 1)
            if len(data) != item.size:
                raise ValueError('archive size differs')
            files[name] = data
    if 'manifest.json' not in files:
        raise ValueError('missing capsule manifest')
    manifest = decode(files.pop('manifest.json'))
    if (set(manifest) != {'schema', 'qualification', 'registry_qualified', 'sdk_accepted', 'input_key',
                         'identity', 'producer_receipt_sha256', 'files'} or
            manifest['schema'] != 'uds-draco-local-capsule-v1' or
            manifest['qualification'] != 'experimental-local-only' or
            manifest['registry_qualified'] is not False or manifest['sdk_accepted'] is not False or
            manifest['input_key'] != expected_key or key(manifest['identity']) != expected_key or
            set(files) != set(manifest['files']) or not FIXED <= files.keys()):
        raise ValueError('capsule contract or input key differs')
    for name, data in files.items():
        if manifest['files'][name] != {'bytes': len(data), 'sha256': sha(data), 'mode': 0o644}:
            raise ValueError('payload digest differs')
    return manifest, files


def restore(capsule, expected_sha, expected_key, output):
    # Local caller must pin BOTH values from a reviewed producer. This does not
    # authenticate remote metadata and never executes restored CMake or binaries.
    if output.exists() or output.is_symlink():
        raise ValueError('restore output must be new')
    for parent in output.absolute().parents:
        if parent.is_symlink():
            raise ValueError('symlink restore ancestor refused')
    manifest, files = verify(capsule, expected_sha, expected_key)
    output.mkdir(parents=True)
    for name, data in sorted(files.items()):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o644)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    a = commands.add_parser('pack')
    a.add_argument('--producer', type=Path, required=True)
    a.add_argument('--producer-receipt-sha256', required=True)
    a.add_argument('--output', type=Path, required=True)
    for name in ('verify', 'restore-local'):
        a = commands.add_parser(name)
        a.add_argument('--capsule', type=Path, required=True)
        a.add_argument('--sha256', required=True)
        a.add_argument('--input-key', required=True)
        if name == 'restore-local':
            a.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.command == 'pack':
        result = pack(args.producer, args.producer_receipt_sha256, args.output)
    elif args.command == 'verify':
        result = verify(args.capsule, args.sha256, args.input_key)[0]
    else:
        result = restore(args.capsule, args.sha256, args.input_key, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
