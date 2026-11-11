#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in historical MDBTOOLS 1.0.0 static PIC source profile, not SDK acceptance."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import time
import sys

HERE = Path(__file__).resolve().parent
HELPERS = {'native': HERE.parent / 'native-deps/build.py', 'las': HERE.parent / 'native-las/build.py'}
MODULES = {}
for name, path in HELPERS.items():
    spec = importlib.util.spec_from_file_location('mdbtools_' + name, path)
    MODULES[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULES[name])
native, las = MODULES['native'], MODULES['las']
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
LOCK = json.loads((HERE / 'inputs.lock.json').read_text())
ARCHIVE = LOCK['archives']['mdbtools-1.0.0']
LICENSES = LOCK['licenses']
TOOLS = {'gcc': '14.2.0', 'make': '4.4.1', 'binutils': '2.44'}
PATCH = json.loads((HERE / 'patch.json').read_text())
FIXTURE = LOCK['fixture']
FILES = ('build.py', 'inputs.lock.json', 'patch.json', 'MdbControls.c', 'run-in.py')
LOCK_SHA256 = '5fa9481c074e0f67bba3b7e8e9da35a9ac2f538991fa5c783a58802a4138b610'


def validate_lock(lock):
    import hashlib
    canonical = json.dumps(lock, sort_keys=True).encode()
    if hashlib.sha256(canonical).hexdigest() != LOCK_SHA256:
        raise ValueError('unreviewed MDBTools source/license/tool/patch selection')
    if lock['source_patch'] != PATCH:
        raise ValueError('unreviewed patch selection')


def check_patch_images(src, phase):
    for name, hashes in PATCH['files'].items():
        path = src / name
        if hashes[phase] is None:
            if path.exists():
                raise ValueError('patch added path already exists: ' + name)
        elif native.digest(path) != hashes[phase]:
            raise ValueError('official MDBTools patch image differs: ' + name)


def recipe():
    return {name: native.digest(HERE / name) for name in FILES} | {
        '../' + str(path.relative_to(HERE.parent)): native.digest(path) for path in HELPERS.values()}


def environment(cc, cxx=None):
    env = las.environment({'cc': {'path': cc}, 'cxx': {'path': cxx or cc}})
    for key in list(env):
        if (key.startswith(('MDB', 'BASH_FUNC_')) or key in
                ('MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS', 'MAKEFILES', 'CONFIG_SITE', 'CONFIG_SHELL', 'SHELL',
                 'AR', 'RANLIB', 'LD', 'NM', 'AS', 'STRIP')):
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC', CXXFLAGS='-O2 -fPIC -std=c++17', CONFIG_SITE='/dev/null')
    return env


def validate_paths(output, cache):
    output, cache = native.external(output), native.external(cache)
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('output must be new and separate from cache')
    return output, cache


def source_inventory(root):
    found = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('source symlink refused')
        if path.is_file():
            found[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return found


def check_sources(root, expected):
    if source_inventory(root) != expected:
        raise ValueError('untouched MDBTOOLS source changed')


def outputs(root):
    result = {}
    for name in ('MdbControls.c', 'consumer', 'libmdb-pic-check.so'):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or nonregular positive control')
        result[name] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return result


def disk_bound(output, cache):
    size = sum(p.stat().st_size for root in (output, cache) for p in root.rglob('*')
               if p.is_file() and not p.is_symlink())
    if size > 4 * 1024 ** 3:
        raise ValueError('MDBTOOLS profile exceeds 4 GiB output/cache bound')
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    for name, default in (('cc', 'gcc'), ('cxx', 'g++'), ('make', 'make'), ('patch', 'patch'), ('readelf', 'readelf')):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--fetch-dependencies', action='store_true')
    parser.add_argument('--with-upstream-fixture', action='store_true',
                        help='explicit private use of Internet-sourced upstream Northwind test data')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 historical component profile validated')
    if not args.with_upstream_fixture:
        raise ValueError('explicit --with-upstream-fixture required for private data controls')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    initial = recipe()
    output, cache = validate_paths(args.output, args.cache)
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    deadline, commands = time.monotonic() + 600, []
    cc = str(Path(shutil.which(args.cc) or args.cc).resolve())
    cxx = str(Path(shutil.which(args.cxx) or args.cxx).resolve())
    env = environment(cc, cxx)

    def run(command, name, timeout=30, capture=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('MDBTOOLS profile total command deadline exhausted')
        limit = min(timeout, remaining)
        commands.append({'name': name, 'args': list(map(str, command)), 'timeout': limit})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        return native.run(list(map(str, command)), output, name, timeout=limit, env=env, capture=capture)

    tools = {}
    for name, value in (('cc', cc), ('cxx', cxx), ('make', args.make), ('patch', args.patch),
                        ('readelf', args.readelf), ('ar', 'ar'), ('ranlib', 'ranlib'), ('ldd', 'ldd')):
        path = Path(shutil.which(value) or value).resolve()
        version = run([path, '--version'], 'tool-' + name, capture=True).decode().strip()
        tools[name] = {'path': str(path), 'sha256': native.digest(path), 'version': version}
    if (not tools['cc']['version'].splitlines()[0].endswith(' ' + TOOLS['gcc']) or
            tools['make']['version'].splitlines()[0] != 'GNU Make ' + TOOLS['make'] or
            not tools['cxx']['version'].splitlines()[0].endswith(' ' + TOOLS['gcc']) or
            any(not tools[name]['version'].splitlines()[0].endswith(' ' + TOOLS['binutils'])
                for name in ('readelf', 'ar', 'ranlib'))):
        raise ValueError('toolchain differs from historical MDBTOOLS profile')
    env.update(AR=tools['ar']['path'], RANLIB=tools['ranlib']['path'])
    archive = native.acquire(cache, ARCHIVE, args.fetch_dependencies)
    source = output / 'source'
    source.mkdir()
    expected = las.unpack(archive, source, 'mdbtools-1.0.0', ARCHIVE)
    native.verified(archive, ARCHIVE)
    check_sources(source, expected)
    (output / 'sources.json').write_text(json.dumps(expected, sort_keys=True) + '\n')
    src = source / 'mdbtools-1.0.0'
    for name, checksum in LICENSES.items():
        if native.digest(src / name) != checksum:
            raise ValueError('MDBTools license differs')
    patch_entry = {key: PATCH[key] for key in ('url', 'bytes', 'sha256')}
    patch_file = native.acquire(cache, patch_entry, args.fetch_dependencies)
    check_patch_images(src, 'before')
    run([sys.executable, HERE / 'run-in.py', src, tools['patch']['path'], '--fuzz=0', '--batch',
         '--no-backup-if-mismatch', '-p1', '-i', patch_file], 'official-patch')
    check_patch_images(src, 'after')
    patched = source_inventory(source)
    changed = {name for name in set(expected) | set(patched) if expected.get(name) != patched.get(name)}
    if changed != {'mdbtools-1.0.0/' + name for name in PATCH['files']}:
        raise ValueError('unexpected source patch changes')
    expected = patched
    (output / 'sources.json').write_text(json.dumps(expected, sort_keys=True) + '\n')
    build, prefix = output / 'build', output / 'install'
    build.mkdir()
    fixture = native.acquire(cache, FIXTURE, args.fetch_dependencies)
    run([sys.executable, HERE / 'run-in.py', build, src / 'configure', '--disable-shared',
         '--enable-static', '--with-pic', '--disable-maintainer-mode', '--disable-glib', '--disable-man', '--disable-sql',
         '--enable-iconv', '--disable-nls', '--prefix=' + str(prefix)], 'configure', 90)
    check_sources(source, expected)
    disk_bound(output, cache)
    run([tools['make']['path'], '-C', build, '-j1'], 'source-build', 450)
    run([tools['make']['path'], '-C', build, '-j1', 'install'], 'source-install', 60)
    library = prefix / 'lib/libmdb.a'
    if not library.is_file() or library.is_symlink() or list((prefix / 'lib').glob('*.so*')):
        raise ValueError('expected genuine source-built static MDBTools only')
    for name in LICENSES:
        shutil.copyfile(src / name, prefix / name)
    installed = native.inventory(prefix)
    shutil.copyfile(HERE / 'MdbControls.c', output / 'MdbControls.c')
    run([cc, '-std=c11', '-D_XOPEN_SOURCE=700', '-O1', '-I' + str(prefix / 'include'), output / 'MdbControls.c',
         library, '-lm', '-o', output / 'consumer'], 'consumer-compile')
    text = run([output / 'consumer', fixture, output / 'missing.mdb'], 'mdb-controls', 10, True).decode()
    if text != 'File not found\nmdbtools=1.0.0\ncustomers=91\nalfki=Maria Anders\nreal_mdb_catalog_rows_and_missing_controls=true\n':
        raise ValueError('genuine MDBTools controls incomplete: ' + text)
    run([cc, '-shared', '-Wl,--whole-archive', library, '-Wl,--no-whole-archive',
         '-Wl,--no-undefined', '-lm', '-o', output / 'libmdb-pic-check.so'], 'strict-pic-link')
    if b'TEXTREL' in run([tools['readelf']['path'], '-d', output / 'libmdb-pic-check.so'], 'pic-relocations', capture=True):
        raise ValueError('TEXTREL in MDBTools')
    symbols = run([tools['readelf']['path'], '-Ws', output / 'libmdb-pic-check.so'],
                  'kernel-required-symbols', capture=True).decode()
    for symbol in ('mdb_ole_read_next', 'mdb_set_boolean_fmt_numbers'):
        if not any('GLOBAL' in line and ' UND ' not in line and line.split()[-1] == symbol
                   for line in symbols.splitlines() if line.split()):
            raise ValueError('missing actual Kernel-required MDB symbol: ' + symbol)
    closure = run([tools['ldd']['path'], output / 'consumer'], 'runtime-closure', capture=True).decode()
    if 'not found' in closure or any(name in closure.lower() for name in ('libmdb', 'libglib', 'libiconv')):
        raise ValueError('host third-party runtime fallback or missing dependency')
    runtime = {str(Path(word).resolve()): native.digest(Path(word)) for line in closure.splitlines()
               for word in line.split() if word.startswith('/') and Path(word).is_file()}
    if not runtime:
        raise ValueError('runtime closure unavailable')
    check_sources(source, expected)
    native.verified(archive, ARCHIVE)
    native.verified(fixture, FIXTURE)
    native.verified(patch_file, patch_entry)
    if installed != native.inventory(prefix) or initial != recipe():
        raise ValueError('installed MDBTOOLS or recipe changed during positive controls')
    if native.digest(output / 'MdbControls.c') != initial['MdbControls.c']:
        raise ValueError('positive consumer source changed')
    for tool in tools.values():
        if native.digest(Path(tool['path'])) != tool['sha256']:
            raise ValueError('build tool changed')
    record = {'schema_version': 1, 'profile': 'historical-mdbtools-native', 'version': '1.0.0',
              'source_revision': REVISION, 'recipe': initial, 'archive': ARCHIVE, 'licenses': LICENSES,
              'tools': tools, 'source_inventory': expected, 'installed': installed,
              'outputs': outputs(output), 'runtime_closure': runtime, 'build_jobs': 1,
              'disk_bytes': disk_bound(output, cache), 'command_deadline_s': 600,
              'source_patch': PATCH, 'fixture': FIXTURE, 'real_mdb_controls': True,
              'iconv_provider': 'glibc', 'required_kernel_symbols_linked': True,
              'ole_runtime_acceptance': False, 'strict_pic': True, 'kernel_provider_acceptance': False,
              'kernel_sdk_acceptance': False, 'jni_acceptance': False, 'takx_acceptance': False,
              'security_acceptance': False, 'target_image_abi_acceptance': False}
    (output / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    print('MDBTools 1.0.0 genuine source-built PIC and catalog/row controls passed')


if __name__ == '__main__':
    main()
