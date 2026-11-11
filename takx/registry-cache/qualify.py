#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run genuine CMake/codec/PIC consumers at two new experimental local prefixes."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import draco

CMAKE = '''# Local relocation control; upstream target bytes remain unchanged.
cmake_minimum_required(VERSION 3.24)
project(DracoCacheConsumer LANGUAGES CXX)
find_package(draco CONFIG REQUIRED PATHS "${DRACO_PREFIX}/share/cmake/draco" NO_DEFAULT_PATH)
get_target_property(actual draco::draco IMPORTED_LOCATION_RELEASE)
get_target_property(headers draco::draco INTERFACE_INCLUDE_DIRECTORIES)
if(NOT actual STREQUAL "${DRACO_PREFIX}/lib/libdraco.a" OR NOT headers STREQUAL "${DRACO_PREFIX}/include")
  message(FATAL_ERROR "Draco target escaped restored prefix")
endif()
add_executable(consumer DracoSourceProbe.cpp)
target_compile_options(consumer PRIVATE -UNDEBUG)
target_link_libraries(consumer PRIVATE draco::draco)
add_library(piccheck SHARED anchor.cpp)
target_link_options(piccheck PRIVATE -Wl,--no-undefined -Wl,-z,defs)
target_link_libraries(piccheck PRIVATE "$<LINK_LIBRARY:WHOLE_ARCHIVE,draco::draco>")
'''


def qualify(capsule, expected, input_key, fixture, output, cmake, ninja, cxx):
    if output.exists() or output.is_symlink():
        raise ValueError('qualification output must be new')
    if draco.file_sha(fixture) != '0564c778421e0b1ed4756bf0325c34cee945432af42ff66a18776803e79753bf':
        raise ValueError('codec fixture differs from genuine producer fixture')
    original = draco.file_sha(capsule)
    draco.verify(capsule, expected, input_key)
    output.mkdir(parents=True)
    frozen = output / 'producer'
    frozen.mkdir()
    recipe = {name: draco.file_sha(draco.HERE / name) for name in ('draco.py', 'qualify.py')}
    for name in recipe:
        shutil.copyfile(draco.HERE / name, frozen / name)
    n = draco.native()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'CMAKE_', 'BASH_FUNC_')) and
           k not in {'CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LIBRARY_PATH', 'CPATH',
                     'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'GCC_EXEC_PREFIX', 'COMPILER_PATH',
                     'MAKEFLAGS', 'GNUMAKEFLAGS', 'BASH_ENV', 'ENV'}}
    tools = {name: n.tool(path, ['--version'], output, name) for name, path in
             [('cmake', cmake), ('ninja', ninja), ('cxx', cxx), ('readelf', 'readelf')]}
    source = output / 'consumer-source'
    source.mkdir()
    probe = draco.ROOT / 'takx/native-deps/DracoSourceProbe.cpp'
    shutil.copyfile(probe, source / probe.name)
    shutil.copyfile(fixture, source / 'cube.drc')
    (source / 'CMakeLists.txt').write_text(CMAKE)
    (source / 'anchor.cpp').write_text('extern "C" int draco_pic_probe_anchor() { return 1; }\n')
    results = []
    for index, relative in enumerate(('first', 'unrelated/deeper/second')):
        restored = output / relative
        manifest = draco.restore(capsule, expected, input_key, restored)
        prefix, build = restored / 'prefix', output / ('build-' + str(index))
        command = [tools['cmake']['path'], '-S', str(source), '-B', str(build), '-G', 'Ninja',
                   '-DCMAKE_MAKE_PROGRAM=' + tools['ninja']['path'], '-DCMAKE_CXX_COMPILER=' + tools['cxx']['path'],
                   '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_BUILD_TYPE=Release',
                   '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF', '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF',
                   '-DDRACO_PREFIX=' + str(prefix)]
        n.run(command, output, f'configure-{index}', timeout=60, env=env)
        n.run([tools['cmake']['path'], '--build', str(build), '--parallel', '1'], output,
              f'build-{index}', timeout=120, env=env)
        runtime_env = dict(env, LD_DEBUG='libs,files')
        data = n.run([str(build / 'consumer'), str(source / 'cube.drc')], output,
                     f'codec-{index}', capture=True, env=runtime_env)
        if b'draco_source_codec_consumer=pass;' not in data:
            raise ValueError('missing actual codec control')
        dynamic = n.run([tools['readelf']['path'], '-d', str(build / 'libpiccheck.so')], output,
                        f'pic-{index}', capture=True, env=env)
        if b'TEXTREL' in dynamic:
            raise ValueError('PIC consumer contains text relocations')
        providers = {}
        allowed = {'libstdc++.so.6', 'libm.so.6', 'libgcc_s.so.1', 'libc.so.6', 'ld-linux-x86-64.so.2'}
        for name in re.findall(rb'calling init: ([^\n]+)', data):
            path = Path(os.fsdecode(name.strip())).resolve()
            if not any(name in path.name or path.name == name for name in allowed):
                # Resolving libstdc++.so.6 exposes its real versioned basename.
                raise ValueError('unexpected actual runtime provider')
            providers[str(path)] = draco.file_sha(path)
        if len(providers) != 5:
            raise ValueError('incomplete actual runtime provider observation')
        commands = json.loads((build / 'compile_commands.json').read_text())
        if any(str(prefix / 'include') not in c['command'] for c in commands if 'DracoSourceProbe' in c['file']):
            raise ValueError('codec compiler did not consume restored include target')
        for name, entry in manifest['files'].items():
            if draco.file_sha(restored / name) != entry['sha256']:
                raise ValueError('restored payload changed during consumers')
        results.append({'prefix': relative + '/prefix', 'codec_passed': True, 'whole_archive_pic_passed': True,
                        'consumer_sha256': draco.file_sha(build / 'consumer'),
                        'pic_sha256': draco.file_sha(build / 'libpiccheck.so'),
                        'actual_initialized_providers': providers})
    if draco.file_sha(capsule) != original:
        raise ValueError('capsule changed during qualification')
    if recipe != {name: draco.file_sha(draco.HERE / name) for name in recipe}:
        raise ValueError('consumer recipe changed during qualification')
    receipt = {'schema': 'uds-draco-local-relocation-v1', 'consumer_recipe': recipe, 'capsule_sha256': expected, 'input_key': input_key,
               'tools': tools, 'probe_sha256': draco.file_sha(probe), 'fixture_sha256': draco.file_sha(fixture),
               'results': results, 'registry_pull_ran': False, 'publisher_authenticated': False,
               'historical_build_abi_complete': False, 'sdk_accepted': False}
    (output / 'complete.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capsule', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--input-key', required=True)
    p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cmake', default='cmake')
    p.add_argument('--ninja', default='ninja')
    p.add_argument('--cxx', default='g++')
    args = p.parse_args()
    print(json.dumps(qualify(args.capsule, args.sha256, args.input_key, args.fixture,
                            args.output, args.cmake, args.ninja, args.cxx), indent=2))


if __name__ == '__main__':
    main()
