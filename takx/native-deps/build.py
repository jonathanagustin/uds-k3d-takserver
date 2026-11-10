#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in source-built Draco and verified public headers; not a Kernel SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import selectors
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
MAX_LOG = 16 * 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def relative(name):
    value = PurePosixPath(name)
    if not value.parts or value.is_absolute() or '..' in value.parts or '\\' in name:
        raise ValueError('unsafe input path')
    return value


def external(path):
    if path.is_symlink():
        raise ValueError('symlink build/cache root refused')
    path = path.resolve()
    if path == REPOSITORY or REPOSITORY in path.parents:
        raise ValueError('build/cache must be outside repository')
    return path


def run(command, directory, name, timeout=60, env=None, capture=False, limit=MAX_LOG):
    """Bound process-group lifetime and complete output, never inherited file writes."""
    output = directory / (name + '.log')
    child = None
    data = bytearray()
    count = 0
    deadline = time.monotonic() + timeout
    try:
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        with output.open('xb') as log, selectors.DefaultSelector() as selector:
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('native dependency command timed out')
                for key, _ in selector.select(min(remaining, 0.1)):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    count += len(block)
                    if count > limit:
                        raise ValueError('native dependency output exceeds bound')
                    log.write(block)
                    if capture:
                        data.extend(block)
            try:
                code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ValueError('native dependency command timed out') from None
            if code:
                raise ValueError('native dependency command failed; inspect local bounded log')
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            child.stdout.close()
    return bytes(data)


def git(source, *args):
    return subprocess.check_output(['git', '--no-lazy-fetch', '-C', str(source), *args], timeout=60)


def validate_lock(lock):
    if (lock.get('schema_version') != 1 or lock.get('revision') != REVISION or
            lock.get('repository') != 'https://github.com/TAK-Product-Center/atak-civ' or
            lock.get('platform') != 'Linux-x86_64' or
            lock.get('draco', {}).get('tree') != 'cdb45ced759d4f6bf697cb3885830bfc47ec6996' or
            lock['draco'].get('version') != '1.5.7' or lock['draco'].get('files') != 984 or
            lock['draco'].get('bytes') != 84642797 or set(lock.get('archives', {})) != {'tinygltf', 'tinygltfloader'}):
        raise ValueError('unsupported native source lock')
    if len(lock.get('headers', [])) != 11:
        raise ValueError('unexpected Khronos header selection')
    entries = [*lock['headers'], *lock['archives'].values()]
    for entry in entries:
        if (type(entry.get('bytes')) is not int or not 0 < entry['bytes'] <= 8 * 1024 * 1024 or
                not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', ''))):
            raise ValueError('invalid source hash or size')
        allowed = ('https://raw.githubusercontent.com/TAK-Product-Center/atak-civ/' + REVISION + '/khronos/',
                   'https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/' + REVISION + '/depends/')
        if not entry.get('url', '').startswith(allowed):
            raise ValueError('unreviewed source origin')
    for header in lock['headers']:
        relative(header['path'])
        relative(header['destination'])
        if header['url'] != allowed[0] + header['path'].removeprefix('khronos/'):
            raise ValueError('header URL differs from selected source path')
    for archive in lock['archives'].values():
        for item in archive['files']:
            relative(item['path'])
            relative(item['destination'])


def verified(path, entry):
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes'] or
            digest(path) != entry['sha256']):
        raise ValueError('input checksum mismatch')
    if 'git_blob' in entry:
        data = path.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != entry['git_blob']:
            raise ValueError('source Git blob differs from lock')
    return path


def acquire(cache, entry, fetch):
    target = cache / entry['sha256']
    if target.exists() or target.is_symlink():
        return verified(target, entry)
    if not fetch:
        raise ValueError('verified offline source cache entry missing')
    descriptor, name = tempfile.mkstemp(prefix='source-download-', dir=cache)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream, urllib.request.urlopen(entry['url'], timeout=30) as response:
            count = 0
            deadline = time.monotonic() + 60
            while block := response.read1(65536):
                if time.monotonic() > deadline:
                    raise ValueError('source download timed out')
                count += len(block)
                if count > entry['bytes']:
                    raise ValueError('source download exceeds lock')
                stream.write(block)
        verified(temporary, entry)
        # Never overwrite a concurrent or unverified cache entry.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def unpack_selected(archive, entries, destination):
    """Materialize selected, exact-hash regular headers/licenses, never extractall."""
    with tarfile.open(archive) as files:
        expected = {str(relative(entry['path'])): entry for entry in entries}
        found = set()
        for member in files:
            name = str(relative(member.name))
            if name not in expected:
                continue
            if name in found or not member.isfile():
                raise ValueError('ambiguous or nonregular selected archive member')
            entry = expected[name]
            if member.size != entry['bytes'] or member.size > 1024 * 1024:
                raise ValueError('selected archive member size mismatch')
            data = files.extractfile(member).read(member.size + 1)
            if len(data) != member.size or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('selected archive member checksum mismatch')
            path = destination / relative(entry['destination'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            found.add(name)
        if found != set(expected):
            raise ValueError('selected archive member missing')


def freeze(source, output, lock):
    source = source.resolve()
    if Path(git(source, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != source:
        raise ValueError('source must be initialized Git root')
    if git(source, 'rev-parse', 'HEAD').decode().strip() != lock['revision']:
        raise ValueError('source revision mismatch')
    if git(source, 'rev-parse', 'HEAD:draco').decode().strip() != lock['draco']['tree']:
        raise ValueError('Draco source tree mismatch')
    if git(source, 'diff', '--name-only', 'HEAD', '--', 'draco').strip():
        raise ValueError('modified native source refused')
    for options in (['--others', '--exclude-standard'], ['--others', '--ignored', '--exclude-standard']):
        if git(source, 'ls-files', *options, '--', 'draco').strip():
            raise ValueError('untracked native source refused')
    # Verify worktree bytes against every pinned Git blob before freezing.
    # This avoids archive/promisor reads while retaining immutable source identity.
    listing = git(source, 'ls-tree', '-rz', lock['revision'], '--', 'draco')
    if len(listing) > 1024 * 1024:
        raise ValueError('source inventory exceeds bound')
    destination = output / 'source'
    destination.mkdir()
    inventory = []
    total = 0
    seen = set()
    for entry in listing.split(b'\0'):
        if not entry:
            continue
        metadata, raw_name = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        name = relative(raw_name.decode())
        if kind != 'blob' or mode not in ('100644', '100755') or name.parts[0] != 'draco' or str(name) in seen:
            raise ValueError('unexpected native source entry')
        origin = source / name
        if origin.is_symlink() or not origin.is_file() or source not in origin.resolve().parents:
            raise ValueError('nonregular source input')
        with origin.open('rb') as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('oversized native source entry')
        identity = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if identity != blob:
            raise ValueError('native source Git blob mismatch')
        total += len(data)
        if total > lock['draco']['bytes'] or len(inventory) >= lock['draco']['files']:
            raise ValueError('source inventory exceeds lock')
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if mode == '100755' else 0o644)
        seen.add(str(name))
        inventory.append({'path': str(name), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                          'git_blob': blob})
    if len(inventory) != lock['draco']['files'] or total != lock['draco']['bytes']:
        raise ValueError('source inventory differs from lock')
    fixture = destination / 'draco' / relative(lock['draco']['fixture'])
    if digest(fixture) != lock['draco']['fixture_sha256']:
        raise ValueError('codec fixture differs from lock')
    (output / 'sources.json').write_text(json.dumps(inventory, indent=2) + '\n')
    return destination / 'draco'


def inventory(root):
    values = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            if root.resolve() not in path.resolve().parents:
                raise ValueError('installed symlink leaves prefix')
            values.append({'path': str(path.relative_to(root)), 'symlink': os.readlink(path), 'sha256': digest(path)})
        elif path.is_file():
            values.append({'path': str(path.relative_to(root)), 'sha256': digest(path), 'bytes': path.stat().st_size})
    return values


PROBE_OUTPUTS = ('consumer', 'libdraco-pic-check.so', 'cube.drc', 'cube.obj')


def probe_inventory(output):
    values = {}
    for name in PROBE_OUTPUTS:
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or nonregular native probe output')
        values[name] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    return values


def verify_probe_outputs(output, expected):
    if set(expected) != set(PROBE_OUTPUTS) or probe_inventory(output) != expected:
        raise ValueError('native probe output integrity mismatch')


def tool(path, args, output, name):
    resolved = Path(shutil.which(str(path)) or str(path)).resolve()
    if not resolved.is_file():
        raise ValueError('required build tool unavailable')
    version = run([str(resolved), *args], output, 'tool-' + name, capture=True).decode().strip()
    return {'path': str(resolved), 'sha256': digest(resolved), 'version': version}


def build_environment(tools):
    env = dict(os.environ)
    ignored = {'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CPATH', 'C_INCLUDE_PATH',
               'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH', 'COMPILER_PATH', 'GCC_EXEC_PREFIX',
               'LD_PRELOAD', 'LD_LIBRARY_PATH'}
    for key in list(env):
        if key in ignored or key.startswith('CMAKE_'):
            env.pop(key)
    env.update(VCPKG_BINARY_SOURCES='clear', CC=tools['cc']['path'], CXX=tools['cxx']['path'])
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cxx', default='g++')
    parser.add_argument('--jobs', type=int, choices=(1, 2), default=1)
    parser.add_argument('--fetch-dependencies', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('only native Linux x86_64 has a validated profile')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    output, cache = external(args.output), external(args.cache)
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('output must be new and separate from cache')
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    tools = {name: tool(getattr(args, name), ['--version'], output, name)
             for name in ('cmake', 'ninja', 'cc', 'cxx')}
    if (tools['cmake']['version'].splitlines()[0] != 'cmake version ' + lock['tools']['cmake'] or
            tools['ninja']['version'] != lock['tools']['ninja'] or
            any(not tools[name]['version'].splitlines()[0].endswith(' ' + lock['tools']['gcc'])
                for name in ('cc', 'cxx'))):
        raise ValueError('toolchain differs from tested native profile')
    tools['git'] = tool('git', ['--no-lazy-fetch', '--version'], output, 'git')
    tools['git']['required_feature'] = '--no-lazy-fetch'
    recipe = {p.name: digest(p) for p in (HERE / 'build.py', HERE / 'inputs.lock.json', HERE / 'DracoSourceProbe.cpp')}
    probe = output / 'DracoSourceProbe.cpp'
    shutil.copyfile(HERE / 'DracoSourceProbe.cpp', probe)
    source = freeze(args.source, output, lock)
    prefix = output / 'install'
    for entry in lock['headers']:
        path = prefix / 'include' / relative(entry['destination'])
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(acquire(cache, entry, args.fetch_dependencies), path)
    for entry in lock['archives'].values():
        unpack_selected(acquire(cache, entry, args.fetch_dependencies), entry['files'], prefix)
    build = output / 'build'
    env = build_environment(tools)
    configure = [tools['cmake']['path'], '-S', str(source), '-B', str(build), '-G', 'Ninja',
                 '-DCMAKE_MAKE_PROGRAM=' + tools['ninja']['path'], '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_C_COMPILER=' + tools['cc']['path'], '-DCMAKE_CXX_COMPILER=' + tools['cxx']['path'],
                 '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
                 '-DDRACO_TESTS=OFF', '-DDRACO_TRANSCODER_SUPPORTED=OFF']
    run(configure, output, 'configure', env=env)
    run([tools['cmake']['path'], '--build', str(build), '--parallel', str(args.jobs)],
        output, 'build', timeout=1200, env=env)
    run([tools['cmake']['path'], '--install', str(build)], output, 'install', env=env)
    fixture = source / lock['draco']['fixture']
    stream = output / 'cube.drc'
    run([str(prefix / 'bin/draco_encoder'), '-i', str(fixture), '-o', str(stream)], output, 'encode', env=env)
    run([str(prefix / 'bin/draco_decoder'), '-i', str(stream), '-o', str(output / 'cube.obj')], output, 'decode', env=env)
    compiler = tools['cxx']['path']
    library = prefix / 'lib/libdraco.a'
    run([compiler, '-std=c++17', '-O1', '-I' + str(prefix / 'include'), str(probe),
         str(library), '-pthread', '-o', str(output / 'consumer')], output, 'consumer-compile', env=env)
    run([str(output / 'consumer'), str(stream)], output, 'consumer', env=env)
    run([compiler, '-shared', '-Wl,--whole-archive', str(library), '-Wl,--no-whole-archive',
         '-pthread', '-o', str(output / 'libdraco-pic-check.so')], output, 'pic-link', env=env)
    readelf = shutil.which('readelf')
    if not readelf or b'TEXTREL' in run([readelf, '-d', str(output / 'libdraco-pic-check.so')], output,
                                      'pic-relocations', capture=True, env=env):
        raise ValueError('PIC link has unverified/text relocation state')
    licenses = prefix / 'licenses/draco'
    licenses.mkdir(parents=True)
    shutil.copyfile(source / 'LICENSE', licenses / 'LICENSE')
    expected_sources = json.loads((output / 'sources.json').read_text())
    for item in expected_sources:
        path = output / 'source' / item['path']
        if path.is_symlink() or not path.is_file() or digest(path) != item['sha256']:
            raise ValueError('frozen source changed during build')
    if sum(p.is_file() for p in source.rglob('*')) != len(expected_sources):
        raise ValueError('frozen source inventory changed during build')
    if recipe != {name: digest(HERE / name) for name in recipe} or digest(probe) != recipe['DracoSourceProbe.cpp']:
        raise ValueError('recipe or probe changed during build')
    record = {'schema_version': 1, 'profile': 'public-native-dependencies',
              'source_revision': REVISION, 'draco_version': lock['draco']['version'], 'tools': tools,
              'recipe': recipe,
              'configure_command': configure, 'build_jobs': args.jobs,
              'source_inventory_sha256': digest(output / 'sources.json'), 'installed': inventory(prefix),
              'probe_outputs': probe_inventory(output),
              'codec_fixture_probe_passed': True, 'pic_link_passed': True,
              'upstream_test_suite_ran': False, 'kernel_sdk_acceptance': False,
              'jni_or_renderer_acceptance': False, 'texture_fill_acceptance': False, 'takx_acceptance': False}
    (output / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Verified public Draco codec/PIC fixture and header inputs; not a Kernel SDK or TAKX build')


if __name__ == '__main__':
    main()
