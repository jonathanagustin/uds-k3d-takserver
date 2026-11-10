#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in historical PROJ 4.9.1 static PIC source profile, not SDK acceptance."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import time

HERE = Path(__file__).resolve().parent
HELPERS = {'native': HERE.parent / 'native-deps/build.py', 'las': HERE.parent / 'native-las/build.py'}
MODULES = {}
for name, path in HELPERS.items():
    spec = importlib.util.spec_from_file_location('proj_' + name, path)
    MODULES[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULES[name])
native, las = MODULES['native'], MODULES['las']
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
ARCHIVE = {'url': 'https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/' + REVISION +
           '/takthirdparty/distfiles/proj.tar.gz', 'bytes': 876386,
           'sha256': 'fca0388f3f8bc5a1a803d2f6ff30017532367992b30cf144f2d39be88f36c319',
           'members': 292, 'regular_files': 281, 'expanded_bytes': 4243599}
LICENSE = {'source': 'proj-4.9.1/COPYING',
           'sha256': '2dcac4af6990093ef48b896bfb81452d46a31b08d46cce34b27e83f93b2e37f6'}
TOOLS = {'gcc': '14.2.0', 'make': '4.4.1', 'cmake': '3.31.6', 'binutils': '2.44'}
FILES = ('build.py', 'inputs.lock.json', 'ProjCoordinates.c')


def validate_lock(lock):
    if lock != {'schema_version': 1, 'revision': REVISION, 'version': '4.9.1',
                'archives': {'proj-4.9.1': ARCHIVE}, 'license': LICENSE, 'tools': TOOLS,
                'source_patches': []}:
        raise ValueError('unreviewed historical PROJ source/license/tool selection')


def recipe():
    return {name: native.digest(HERE / name) for name in FILES} | {
        '../' + str(path.relative_to(HERE.parent)): native.digest(path) for path in HELPERS.values()}


def environment(cc):
    env = las.environment({'cc': {'path': cc}, 'cxx': {'path': cc}})
    for key in list(env):
        if (key.startswith(('PROJ_', 'BASH_FUNC_')) or key in
                ('MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS', 'MAKEFILES', 'CONFIG_SITE', 'CONFIG_SHELL', 'SHELL',
                 'AR', 'RANLIB', 'LD', 'NM', 'AS', 'STRIP')):
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC', CXXFLAGS='-O2 -fPIC', CONFIG_SITE='/dev/null')
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
        raise ValueError('untouched PROJ source changed')


def outputs(root):
    result = {}
    for name in ('ProjCoordinates.c', 'consumer', 'libproj-pic-check.so'):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or nonregular positive control')
        result[name] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return result


def disk_bound(output, cache):
    size = sum(p.stat().st_size for root in (output, cache) for p in root.rglob('*')
               if p.is_file() and not p.is_symlink())
    if size > 256 * 1024 ** 2:
        raise ValueError('PROJ profile exceeds 256 MiB output/cache bound')
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    for name, default in (('cc', 'gcc'), ('make', 'make'), ('cmake', 'cmake'), ('readelf', 'readelf')):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--fetch-dependencies', action='store_true')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 historical component profile validated')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    initial = recipe()
    output, cache = validate_paths(args.output, args.cache)
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    deadline, commands = time.monotonic() + 900, []
    cc = str(Path(shutil.which(args.cc) or args.cc).resolve())
    env = environment(cc)

    def run(command, name, timeout=30, capture=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('PROJ profile total command deadline exhausted')
        limit = min(timeout, remaining)
        commands.append({'name': name, 'args': list(map(str, command)), 'timeout': limit})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        return native.run(list(map(str, command)), output, name, timeout=limit, env=env, capture=capture)

    tools = {}
    for name, value in (('cc', cc), ('make', args.make), ('cmake', args.cmake),
                        ('readelf', args.readelf), ('ar', 'ar'), ('ranlib', 'ranlib'), ('ldd', 'ldd')):
        path = Path(shutil.which(value) or value).resolve()
        version = run([path, '--version'], 'tool-' + name, capture=True).decode().strip()
        tools[name] = {'path': str(path), 'sha256': native.digest(path), 'version': version}
    if (not tools['cc']['version'].splitlines()[0].endswith(' ' + TOOLS['gcc']) or
            tools['make']['version'].splitlines()[0] != 'GNU Make ' + TOOLS['make'] or
            tools['cmake']['version'].splitlines()[0] != 'cmake version ' + TOOLS['cmake'] or
            any(not tools[name]['version'].splitlines()[0].endswith(' ' + TOOLS['binutils'])
                for name in ('readelf', 'ar', 'ranlib'))):
        raise ValueError('toolchain differs from historical PROJ profile')
    env.update(AR=tools['ar']['path'], RANLIB=tools['ranlib']['path'])
    archive = native.acquire(cache, ARCHIVE, args.fetch_dependencies)
    source = output / 'source'
    source.mkdir()
    expected = las.unpack(archive, source, 'proj-4.9.1', ARCHIVE)
    native.verified(archive, ARCHIVE)
    check_sources(source, expected)
    (output / 'sources.json').write_text(json.dumps(expected, sort_keys=True) + '\n')
    src = source / 'proj-4.9.1'
    if native.digest(source / LICENSE['source']) != LICENSE['sha256']:
        raise ValueError('historical PROJ license differs')
    if '#define PJ_VERSION 491' not in (src / 'src/proj_api.h').read_text():
        raise ValueError('historical PROJ header version differs')
    build, prefix = output / 'build', output / 'install'
    build.mkdir()
    run([tools['cmake']['path'], '-E', 'chdir', build, src / 'configure', '--disable-shared',
         '--enable-static', '--without-jni', '--prefix=' + str(prefix)], 'configure', 120)
    check_sources(source, expected)
    disk_bound(output, cache)
    run([tools['make']['path'], '-C', build, '-j1'], 'source-build', 600)
    run([tools['make']['path'], '-C', build, '-j1', 'install'], 'source-install', 60)
    library = prefix / 'lib/libproj.a'
    if not library.is_file() or library.is_symlink() or list((prefix / 'lib').glob('*.so*')):
        raise ValueError('expected source-built static PROJ only')
    if native.digest(prefix / 'include/proj_api.h') != expected['proj-4.9.1/src/proj_api.h']['sha256']:
        raise ValueError('installed header differs from source')
    shutil.copyfile(source / LICENSE['source'], prefix / 'COPYING')
    installed = native.inventory(prefix)
    shutil.copyfile(HERE / 'ProjCoordinates.c', output / 'ProjCoordinates.c')
    run([cc, '-std=c11', '-O1', '-I' + str(prefix / 'include'), output / 'ProjCoordinates.c',
         library, '-lm', '-o', output / 'consumer'], 'consumer-compile')
    text = run([output / 'consumer'], 'positive-coordinates', 10, True).decode()
    if ('actual_release=Rel. 4.9.1, 04 March 2015\n' not in text or
            'known_spherical_mercator_positive_coordinates_and_inverse=true\n' not in text):
        raise ValueError('historical PROJ positive coordinates incomplete')
    run([cc, '-shared', '-Wl,--whole-archive', library, '-Wl,--no-whole-archive',
         '-Wl,--no-undefined', '-lm', '-o', output / 'libproj-pic-check.so'], 'strict-pic-link')
    if b'TEXTREL' in run([tools['readelf']['path'], '-d', output / 'libproj-pic-check.so'], 'pic-relocations', capture=True):
        raise ValueError('TEXTREL in historical PROJ')
    closure = run([tools['ldd']['path'], output / 'consumer'], 'runtime-closure', capture=True).decode()
    if 'not found' in closure or 'libproj' in closure.lower():
        raise ValueError('host PROJ runtime fallback or missing dependency')
    runtime = {str(Path(word).resolve()): native.digest(Path(word)) for line in closure.splitlines()
               for word in line.split() if word.startswith('/') and Path(word).is_file()}
    if not runtime:
        raise ValueError('runtime closure unavailable')
    check_sources(source, expected)
    native.verified(archive, ARCHIVE)
    if installed != native.inventory(prefix) or initial != recipe():
        raise ValueError('installed PROJ or recipe changed during positive controls')
    if native.digest(output / 'ProjCoordinates.c') != initial['ProjCoordinates.c']:
        raise ValueError('positive consumer source changed')
    for tool in tools.values():
        if native.digest(Path(tool['path'])) != tool['sha256']:
            raise ValueError('build tool changed')
    record = {'schema_version': 1, 'profile': 'historical-proj-native', 'version': '4.9.1',
              'pj_version': 491, 'actual_release': 'Rel. 4.9.1, 04 March 2015', 'source_revision': REVISION,
              'recipe': initial, 'archive': ARCHIVE, 'license': LICENSE, 'tools': tools,
              'source_inventory': expected, 'installed': installed, 'outputs': outputs(output),
              'runtime_closure': runtime, 'build_jobs': 1, 'disk_bytes': disk_bound(output, cache),
              'command_deadline_s': 900, 'source_patches': [], 'known_coordinates_forward_inverse': True,
              'strict_pic': True, 'jni_acceptance': False, 'modern_proj_api_compatibility': False,
              'security_acceptance': False, 'target_image_abi_acceptance': False, 'full_ttp_acceptance': False,
              'kernel_sdk_acceptance': False, 'takx_acceptance': False, 'full_upstream_test_suite_ran': False,
              'fault_parser_experiments_run': False}
    (output / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Historical PROJ 4.9.1 source-built PIC and known coordinate controls passed')


if __name__ == '__main__':
    main()
