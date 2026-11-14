# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only integrity verification of the current fresh CommonCommo producer.

An explicit reviewed receipt digest is necessary but never substitutes for source,
recipe, dependency, tool, installed-file and control checks. This is local proof
integrity, not publisher authentication or a registry-cache restore contract.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
KEYS = frozenset(('source', 'spatial', 'zlib', 'quictls', 'tools', 'metadata', 'cache'))
MAX_JSON = 16 * 1024 * 1024


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def canonical(path, directory=False):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink input refused')
    require(path.resolve() == path and (path.is_dir() if directory else path.is_file()), 'canonical regular input required')
    return path


def read(path, limit=MAX_JSON):
    path = canonical(path)
    require(path.stat().st_size <= limit, 'bounded JSON input required')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    require(len(raw) <= limit, 'bounded JSON input required')
    return raw


def decode(raw):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            require(name not in result, 'duplicate JSON field')
            result[name] = value
        return result
    def nonfinite(_value):
        raise ValueError('nonfinite JSON value')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def load(path, limit=MAX_JSON):
    return decode(read(path, limit))


def bindings(path):
    data = load(path, 16384)
    require(isinstance(data, dict) and set(data) == KEYS, 'complete fresh producer bindings required')
    require(all(isinstance(value, str) and Path(value).is_absolute() for value in data.values()),
            'explicit absolute input roots required')
    return {key: canonical(value, directory=True) for key, value in data.items()}


def scope(record):
    require(record.get('profile') == 'public-commoncommo-native-jni' and
            record.get('version') == '1.17.2' and
            record.get('source_revision') == '9f6893dd657feacc35ec5de03dad721c2e44170e',
            'current public CommonCommo producer required')
    for key in ('fresh_dependency_build', 'fresh_core_build', 'fresh_jni_build',
                'actual_commoncommo_jni', 'throwing_logger_exceptions_isolated', 'quic_compiled'):
        require(record.get(key) is True, 'incomplete fresh producer')
    for key in ('all_callback_exception_paths', 'quic_peer_handshake', 'takserver_interoperability', 'full_sdk', 'takx_client'):
        require(record.get(key) is False, 'unsupported producer scope')


def builder():
    path = HERE.parent/'native-commoncommo/build.py'
    spec = importlib.util.spec_from_file_location('cot_fresh_commoncommo', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def official_sources(build, root, source, workspace, patch_tool):
    """Reconstruct patched postimages from Git and owned patches, not metadata."""
    pin = build.LOCK['revision']
    require(build.native.git(source, 'rev-parse', 'HEAD').decode().strip() == pin, 'official revision differs')
    old_lock = json.loads((HERE.parent/'sources.lock.json').read_text())
    patches = [(path, False) for path in build.inputs.verify_patches(HERE.parent/'sources.lock.json', old_lock)]
    patches.append((build.HERE/build.LOCK['jni_patch']['path'], True))
    require(digest(patches[-1][0]) == build.LOCK['jni_patch']['sha256'], 'owned JNI patch differs')
    changed = set()
    for path, jni in patches:
        for line in path.read_text().splitlines():
            if line.startswith('+++ b/'):
                name = line[6:].split('\t')[0]
                name = 'commoncommo/'+name if jni else name
                require(name.startswith('commoncommo/') and '..' not in Path(name).parts, 'patch target differs')
                changed.add(name)
    actual = load(root/'commoncommo-sources.json')
    official, expected = {}, {}
    rows = build.native.git(source, 'ls-tree', '-r', '-z', pin, '--', 'commoncommo').rstrip(b'\0').split(b'\0')
    with tempfile.TemporaryDirectory(prefix='producer-source-', dir=workspace) as directory:
        stage = Path(directory)
        for row in rows:
            meta, raw_name = row.split(b'\t'); mode, kind, oid = meta.decode().split()
            require(kind == 'blob' and mode in ('100644', '100755'), 'nonregular official source')
            name = raw_name.decode(); data = build.native.git(source, 'cat-file', 'blob', oid)
            entry = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            official[name] = {**entry, 'git_blob': oid}
            expected[name.removeprefix('commoncommo/')] = entry
            if name in changed:
                destination = stage/build.native.relative(name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        require(actual['git'] == official and changed <= set(official), 'official Git inventory differs')
        for path, jni in patches:
            subprocess.run([str(patch_tool), '--batch', '--fuzz=0', '--get=0', '--no-backup-if-mismatch',
                            '-p1', '-d', str(stage/'commoncommo' if jni else stage), '-i', str(path)],
                           check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        for name in changed:
            path = canonical(stage/name)
            expected[name.removeprefix('commoncommo/')] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    require(actual['patched'] == expected, 'patched source inventory differs')
    build.check_record(canonical(root/'commoncommo', True), expected)
    return actual


def verify(config, prefix, receipt, jdk, expected_sha, workspace):
    require(isinstance(expected_sha, str) and re.fullmatch('[0-9a-f]{64}', expected_sha), 'reviewed receipt SHA256 required')
    receipt, prefix, jdk = canonical(receipt), canonical(prefix, True), canonical(jdk, True)
    raw_receipt = read(receipt)
    require(hashlib.sha256(raw_receipt).hexdigest() == expected_sha, 'reviewed receipt differs')
    require((platform.system(), platform.machine()) == ('Linux', 'x86_64'), 'supported Linux amd64 producer required')
    root = receipt.parent
    require(receipt.name == 'complete.json' and prefix == root/'install' and not (root/'failed.json').exists(),
            'complete original producer root required')
    selected = bindings(config)
    for path in (root, jdk, HERE, *selected.values()):
        require(workspace != path and path not in workspace.parents and workspace not in path.parents,
                'output overlaps producer input')
    build = builder(); record = decode(raw_receipt); scope(record)
    require(record['recipe'] == build.recipe() and record['jni_patch'] == build.LOCK['jni_patch'], 'normative producer recipe differs')
    require(record['archives'] == build.LOCK['archives'] and record['license'] == build.LOCK['license'] and
            record['official_patches'] == build.LOCK['official_patches'], 'producer source contract differs')
    prepared = load(root/'prepared.json')
    require(digest(root/'prepared.json') == record['prepared_sha256'] and prepared['recipe'] == record['recipe'] and prepared['source'] == build.LOCK['revision'],
            'prepared producer binding differs')
    providers = build.verify_providers(selected['spatial'], selected['zlib'], selected['quictls'])
    require(providers == record['providers'] == prepared['providers'], 'producer dependency proof differs')
    require(build.verify_tools(selected['tools'], selected['metadata']) == prepared['tools'] and
            prepared['tool_lock'] == build.LOCK['tools'], 'signed tool inputs differ')
    require(build.native.inventory(jdk) == record['jdk_inventory'] == prepared['jdk_inventory'], 'producer JDK differs')
    require(digest('/usr/share/keyrings/debian-archive-keyring.gpg') == record['debian_keyring_sha256'] ==
            prepared['debian_keyring_sha256'], 'Debian trust input differs')
    require(prepared['host_tools'] == record['host_tools'], 'producer host tools differ')
    for tool in record['host_tools'].values():
        require(digest(canonical(tool['path'])) == tool['sha256'], 'producer host tool changed')
    for name in ('java', 'javac'):
        require(Path(record['host_tools'][name]['path']) == (jdk/'bin'/name).resolve(), 'selected JDK tool differs')
    patch_tool = Path('/usr/bin/patch').resolve()
    require(str(patch_tool) == record['host_tools']['patch']['path'], 'fixed patch tool differs')
    common = official_sources(build, root, selected['source'], workspace, patch_tool)
    require(digest(root/'commoncommo-sources.json') == prepared['commoncommo_source'], 'source receipt differs')
    sources = load(root/'source-inputs.json')
    require(digest(root/'source-inputs.json') == record['source_inputs_sha256'] == prepared['dependency_sources'] and
            set(sources) == {entry['name'] for entry in build.LOCK['archives']}, 'dependency source receipt differs')
    for entry in build.LOCK['archives']:
        build.native.verified(canonical(selected['cache']/entry['sha256']), entry)
    for entry in sources.values():
        path = canonical(entry['path'], True)
        require(root in path.parents, 'dependency source leaves producer')
        build.check_record(path, entry['postimages'])
    require(build.native.inventory(prefix) == record['installed'], 'installed producer files differ')
    generated = record['generated_protobuf']
    expected_generated = {name.removesuffix('.proto')+suffix for name in common['patched']
                          if name.startswith('core/impl/protobuf/') and name.endswith('.proto') for suffix in ('.pb.cc', '.pb.h')}
    require(set(generated) == expected_generated, 'generated protobuf inventory differs')
    for name, sha in generated.items():
        require(digest(canonical(root/'commoncommo'/build.native.relative(name))) == sha, 'generated protobuf differs')
    require(digest(canonical(root/'host-protobuf/bin/protoc')) == record['generator']['sha256'] and
            record['generator']['version'] == 'libprotoc 3.21.0', 'real source-built protoc differs')
    names = set(build.SMOKES) | {'CommonCommoThrowingLogger'}
    require(set(record['outcomes']) == names, 'complete producer controls required')
    for name in names:
        text = record['outcomes'][name]
        require(text == canonical(root/(name+'.log')).read_text() and 'PASS' in text and
                not any(word in text for word in ('WARNING in native method', 'WARNING: JNI', 'FATAL ERROR')),
                'strict producer control evidence differs')
    for path, sha in record['runtime_closure'].items():
        require(digest(canonical(path)) == sha, 'runtime provider changed')
    require(build.runtime_closure(canonical(root/'jni-runtime.log').read_text()) == record['runtime_closure'], 'runtime closure differs')
    return record, {'kind': 'current-fresh-source-producer', 'receipt_sha256': expected_sha,
                    'bindings_sha256': digest(config), 'commoncommo_sources_sha256': digest(root/'commoncommo-sources.json'),
                    'producer_recipe_sha256': hashlib.sha256(json.dumps(record['recipe'], sort_keys=True).encode()).hexdigest()}
