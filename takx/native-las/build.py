#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in public-source LAS dependency build and bounded local fixture proof."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import tarfile
import time

HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / 'native-deps/build.py'
spec = importlib.util.spec_from_file_location('draco_native_helpers', HELPER)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
MAX_DISK = 12 * 1024 ** 3
COMPONENTS = ('program_options', 'thread', 'system', 'iostreams', 'filesystem',
              'chrono', 'date_time', 'atomic')
GENERATED = {'libLAS/find_package/boost/b2', 'libLAS/find_package/boost/project-config.jam',
             'libLAS/find_package/boost/tools/build/src/engine/b2',
             'libLAS/find_package/boost/tools/build/src/engine/bjam', 'libLAS/README.txt'}
RECIPE_FILES = ('build.py', 'inputs.lock.json', 'LibLASSourceProbe.cpp', 'TruncatedLAZ.hex',
                'patches/liblas-public-prefix-explicit-boost.patch',
                'patches/laszip-init-failure-upstream-backport.patch',
                'patches/liblas-zip-cursor-state-project.patch',
                'patches/liblas-c-api-seek-error-project.patch')


def recipe():
    return {name: native.digest(HERE / name) for name in RECIPE_FILES} | {
        '../native-deps/build.py': native.digest(HELPER)}


def validate_lock(lock):
    if (lock.get('schema_version') != 1 or lock.get('revision') != REVISION or
            set(lock.get('archives', {})) != {'libLAS', 'LASzip'} or
            lock.get('tools') != {'gcc': '14.2.0', 'cmake': '3.31.6',
                                 'ninja': '1.11.1.git.kitware.jobserver-1'}):
        raise ValueError('unsupported LAS source lock')
    pinned = {'libLAS': ('libLAS-1.8.2-mod.tar.gz', 141083708,
                         '8decbf40c5e7690a98a48d53c729f7c7670ff472290c2f46a26c7413ed53e641'),
              'LASzip': ('LASzip-3.4.3-mod.tar.gz', 236749,
                         '66336908e17bb92739803c80fe627461860cacb017dcff55e476e131981e7b6d')}
    for name, (filename, size, sha) in pinned.items():
        entry = lock['archives'][name]
        expected = ('https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/' +
                    REVISION + '/depends/' + filename)
        if entry.get('url') != expected or entry.get('bytes') != size or entry.get('sha256') != sha:
            raise ValueError('unreviewed LAS archive')
        for key in ('expanded_bytes', 'regular_files', 'members'):
            if type(entry.get(key)) is not int or entry[key] <= 0:
                raise ValueError('invalid archive bounds')
        if entry['expanded_bytes'] > 800 * 1024 ** 2 or entry['members'] > 80000:
            raise ValueError('archive bounds exceed profile')
    expected_patches = set(RECIPE_FILES[4:])
    if set(lock.get('patches', {})) != expected_patches:
        raise ValueError('unexpected patch selection')
    for name, item in lock['patches'].items():
        native.relative(name)
        root = native.relative(item['root'])
        source = native.relative(item['source'])
        if str(root) not in ('LASzip', 'libLAS') or source.parts[0] != str(root):
            raise ValueError('patch source outside reviewed root')
        if native.digest(HERE / name) != item['sha256']:
            raise ValueError('patch checksum mismatch')

    if set(lock.get('licenses', {})) != {'libLAS', 'LASzip', 'Boost'}:
        raise ValueError('unexpected license selection')
    for name, item in lock['licenses'].items():
        if len(native.relative(name).parts) != 1:
            raise ValueError('license destination must be a basename')
        path = native.relative(item['source'])
        if path.parts[0] not in ('LASzip', 'libLAS'):
            raise ValueError('license outside reviewed root')


def verify_archives(cache, lock):
    for entry in lock['archives'].values():
        native.verified(cache / entry['sha256'], entry)


def loaded_libraries(text, prefix):
    values = {}
    for line in text.splitlines():
        if not line.startswith('loaded_'):
            continue
        name, raw = line.split('=', 1)
        path = Path(raw).resolve()
        if name in values or name not in ('loaded_liblas', 'loaded_liblas_c') or (prefix / 'lib').resolve() not in path.parents:
            raise ValueError('consumer loaded foreign or duplicate libLAS')
        values[name] = {'path': str(path), 'sha256': native.digest(path)}
    if set(values) != {'loaded_liblas', 'loaded_liblas_c'}:
        raise ValueError('consumer library provenance incomplete')
    return values


def verify_runtime(closure):
    if not closure:
        raise ValueError('runtime closure missing')
    for name, sha in closure.items():
        path = Path(name)
        if not path.is_absolute() or not path.is_file() or native.digest(path) != sha:
            raise ValueError('runtime library integrity mismatch')


def unpack(archive, destination, name, entry):
    """Extract regular, bounded, unique members; never follow archive links."""
    seen, records = set(), {}
    total = count = 0
    deadline = time.monotonic() + 180
    with tarfile.open(archive) as source:
        for member in source:
            if time.monotonic() > deadline:
                raise ValueError('archive extraction timed out')
            path = native.relative(member.name)
            key = str(path)
            if path.parts[0] != name or key in seen or not (member.isfile() or member.isdir()):
                raise ValueError('duplicate, nonregular or foreign archive member')
            seen.add(key)
            count += 1
            if count > entry['members']:
                raise ValueError('archive member count exceeds lock')
            target = destination / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.size > 32 * 1024 ** 2:
                raise ValueError('archive file exceeds bound')
            total += member.size
            if total > entry['expanded_bytes'] or len(records) >= entry['regular_files']:
                raise ValueError('archive expansion exceeds lock')
            data = source.extractfile(member).read(member.size + 1)
            if len(data) != member.size:
                raise ValueError('archive payload truncated')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(data)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            records[key] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    if (count, total, len(records)) != (entry['members'], entry['expanded_bytes'], entry['regular_files']):
        raise ValueError('archive inventory differs from lock')
    return records


def check_sources(source, expected, generated=None):
    generated = generated or {}
    if not set(generated).issubset(GENERATED) or set(generated) & set(expected):
        raise ValueError('unreviewed generated source path')
    found = {}
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('source symlink refused')
        if path.is_file():
            key = str(path.relative_to(source))
            if key not in expected and key not in generated:
                raise ValueError('unexpected generated source file')
            found[key] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    if found != expected | generated:
        raise ValueError('source changed during build')


def environment(tools):
    env = native.build_environment(tools)
    for key in list(env):
        if key.startswith(('BOOST_', 'B2_', 'BJAM_', 'CONAN_', 'PKG_CONFIG')) or key in ('BASH_ENV', 'ENV'):
            env.pop(key)
    env['CMAKE_BUILD_PARALLEL_LEVEL'] = '1'
    return env


def disk_usage(*roots):
    total = 0
    for root in roots:
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
                if total > MAX_DISK:
                    raise ValueError('native profile exceeds 12 GiB disk bound')
    return total


def audit_configuration(build, laszip, boost, stage, commands):
    cache = {}
    for line in (build / 'CMakeCache.txt').read_text().splitlines():
        if '=' in line and not line.startswith(('#', '//')):
            key, value = line.split('=', 1)
            cache[key.split(':', 1)[0]] = value
    if (Path(cache['LASZIP_LIBRARY']).resolve() != (laszip / 'lib/liblaszip.a').resolve() or
            Path(cache['LASZIP_INCLUDE_DIR']).resolve() != (laszip / 'include').resolve() or
            Path(cache['Boost_INCLUDE_DIR']).resolve() != boost.resolve()):
        raise ValueError('dependency prefix mismatch')
    resolved = {}
    for name, value in cache.items():
        if re.fullmatch(r'Boost_[A-Z0-9_]+_LIBRARY_(RELEASE|DEBUG)', name) and not value.endswith('-NOTFOUND'):
            path = Path(value).resolve()
            if stage.resolve() not in path.parents or path.suffix != '.a' or not path.is_file():
                raise ValueError('unverified Boost library')
            resolved[name] = str(path)
    if len(resolved) < 14:
        raise ValueError('missing transitive Boost metadata')
    links = []
    for line in commands.splitlines():
        tokens = shlex.split(line)
        if '-shared' not in tokens:
            continue
        if '-Wl,--no-undefined' not in tokens or any(t.startswith(('-lboost', '-llaszip')) for t in tokens):
            raise ValueError('shared link bypasses explicit dependencies')
        observed = set()
        for token in tokens:
            if 'libboost_' in token:
                path = Path(token).resolve()
                if stage.resolve() not in path.parents or path.suffix != '.a':
                    raise ValueError('shared link uses foreign Boost')
                observed.add(path.name)
            if 'liblaszip.' in token and Path(token).resolve() != (laszip / 'lib/liblaszip.a').resolve():
                raise ValueError('shared link uses foreign LASzip')
        required = {f'libboost_{name}.a' for name in COMPONENTS if name != 'date_time'}
        if observed != required or str(laszip / 'lib/liblaszip.a') not in tokens:
            raise ValueError('shared link dependency closure differs')
        links.append(line)
    if len(links) != 2:
        raise ValueError('unexpected shared link count')
    return {'boost': resolved, 'laszip': cache['LASZIP_LIBRARY'], 'link_commands': links}


def probe_outputs(output):
    names = ('consumer', 'consumer-asan', 'liblas-dependencies-pic-check.so', 'original-truncated.laz')
    result = {}
    for name in names:
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('nonregular probe output')
        result[name] = {'sha256': native.digest(path), 'bytes': path.stat().st_size}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    for name, default in [('cmake', 'cmake'), ('ninja', 'ninja'), ('cc', 'gcc'), ('cxx', 'g++')]:
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--fetch-dependencies', action='store_true')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 is validated')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    start_recipe = recipe()
    output, cache = native.external(args.output), native.external(args.cache)
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('output must be new and separate from cache')
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output).free < 2 * 1024 ** 3:
        raise ValueError('at least 2 GiB free disk required')
    tools = {name: native.tool(getattr(args, name), ['--version'], output, name)
             for name in ('cmake', 'ninja', 'cc', 'cxx')}
    if (tools['cmake']['version'].splitlines()[0] != 'cmake version ' + lock['tools']['cmake'] or
            tools['ninja']['version'] != lock['tools']['ninja'] or
            any(not tools[name]['version'].splitlines()[0].endswith(' ' + lock['tools']['gcc'])
                for name in ('cc', 'cxx'))):
        raise ValueError('toolchain differs from validated profile')
    tools['patch'] = native.tool('patch', ['--version'], output, 'patch')
    tools['readelf'] = native.tool('readelf', ['--version'], output, 'readelf')
    env = environment(tools)
    calls = []

    def run(args, name, timeout=60, capture=False, override=None):
        calls.append({'name': name, 'args': list(map(str, args)), 'timeout': timeout})
        (output / 'commands.json').write_text(json.dumps(calls, indent=2) + '\n')
        return native.run(list(map(str, args)), output, name, timeout=timeout,
                          env=override or env, capture=capture)

    source = output / 'source'
    source.mkdir()
    expected = {}
    for name, entry in lock['archives'].items():
        archive = native.acquire(cache, entry, args.fetch_dependencies)
        expected.update(unpack(archive, source, name, entry))
        native.verified(archive, entry)
    for name, item in lock['patches'].items():
        target = source / item['source']
        if native.digest(target) != item['before_sha256']:
            raise ValueError('patch source preimage mismatch')
        run([tools['cmake']['path'], '-E', 'chdir', source / item['root'], tools['patch']['path'],
             '--batch', '--binary', '--fuzz=0', '-p1', '-i', HERE / name], 'patch-' + Path(name).stem)
        if native.digest(target) != item['after_sha256']:
            raise ValueError('patch postimage mismatch')
        expected[item['source']] = {'bytes': target.stat().st_size, 'sha256': native.digest(target)}
    (output / 'sources.json').write_text(json.dumps(expected, sort_keys=True) + '\n')
    check_sources(source, expected)
    disk_usage(output, cache)
    laszip = output / 'laszip-install'
    lasbuild = output / 'laszip-build'
    cmake, ninja, cc, cxx = (tools[x]['path'] for x in ('cmake', 'ninja', 'cc', 'cxx'))

    def configure(src, build, prefix, extra):
        return [cmake, '-S', src, '-B', build, '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM=' + ninja,
                '-DCMAKE_C_COMPILER=' + cc, '-DCMAKE_CXX_COMPILER=' + cxx,
                '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
                '-DCMAKE_INSTALL_PREFIX=' + str(prefix), *extra]

    run(configure(source / 'LASzip', lasbuild, laszip, ['-DLASZIP_BUILD_STATIC=ON']), 'laszip-configure')
    run([cmake, '--build', lasbuild, '--parallel', '1'], 'laszip-build', 1200)
    run([cmake, '--install', lasbuild], 'laszip-install')
    library = laszip / 'lib/liblaszip.a'
    if not library.is_file() or list((laszip / 'lib').glob('*.so*')):
        raise ValueError('LASzip static-only postcondition failed')
    headers = laszip / 'include/laszip'
    headers.mkdir(exist_ok=True)
    for header in (source / 'LASzip/src').glob('*.hpp'):
        shutil.copyfile(header, headers / header.name)
    dependency = {'laszip': native.inventory(laszip)}
    boost = source / 'libLAS/find_package/boost'
    stage = output / 'boost-stage'
    config = output / 'boost-user-config.jam'
    config.write_text('using gcc : 14.2 : ' + cxx + ' ;\n')
    run([cmake, '-E', 'chdir', boost, './bootstrap.sh', '--with-toolset=gcc',
         '--with-libraries=' + ','.join(COMPONENTS)], 'boost-bootstrap', 120)
    generated = {name: {'bytes': (source / name).stat().st_size, 'sha256': native.digest(source / name)}
                 for name in GENERATED if (source / name).is_file()}
    if set(generated) != GENERATED - {'libLAS/README.txt'}:
        raise ValueError('Boost bootstrap output set differs')
    check_sources(source, expected, generated)
    run([cmake, '-E', 'chdir', boost, boost / 'b2', '--ignore-site-config', '--user-config=' + str(config),
         'toolset=gcc-14.2', '-j1', 'variant=release', 'link=static', 'threading=multi', 'cxxstd=11',
         'cxxflags=-fPIC', '--layout=system', '--build-dir=' + str(output / 'boost-build'),
         '--stagedir=' + str(stage), '-sNO_ZLIB=1', '-sNO_BZIP2=1', '-sNO_LZMA=1', '-sNO_ZSTD=1',
         *['--with-' + name for name in COMPONENTS], 'stage'], 'boost-build', 1200)
    dependency['boost'] = native.inventory(stage)
    if {p.name for p in (stage / 'lib').glob('*.a')} != {'libboost_' + c + '.a' for c in COMPONENTS}:
        raise ValueError('Boost static component inventory mismatch')
    check_sources(source, expected, generated)
    disk_usage(output, cache)
    build, prefix = output / 'liblas-build', output / 'install'
    flags = ['-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_SHARED_LINKER_FLAGS=-Wl,--no-undefined',
             '-DCMAKE_POLICY_DEFAULT_CMP0167=OLD', '-DPUBLIC_LASZIP_PREFIX=' + str(laszip),
             '-DBOOST_ROOT=' + str(boost), '-DBOOST_LIBRARYDIR=' + str(stage / 'lib'),
             '-DBoost_INCLUDE_DIR=' + str(boost), '-DBoost_LIBRARY_DIR_RELEASE=' + str(stage / 'lib'),
             '-DBoost_LIBRARY_DIR_DEBUG=' + str(stage / 'lib'), '-DBoost_NO_SYSTEM_PATHS=ON',
             '-DBoost_NO_BOOST_CMAKE=ON', '-DBoost_USE_STATIC_LIBS=ON', '-DBoost_USE_MULTITHREADED=ON',
             '-DBoost_USE_STATIC_RUNTIME=OFF', '-DWITH_UTILITIES=OFF', '-DWITH_TESTS=OFF',
             '-DWITH_GDAL=OFF', '-DWITH_GEOTIFF=OFF', '-DWITH_LASZIP=ON']
    run(configure(source / 'libLAS', build, prefix, flags), 'liblas-configure', 180)
    readme = 'libLAS/README.txt'
    if (source / readme).is_file() and readme not in expected:
        if (source / readme).read_bytes() != (source / 'libLAS/doc/index.txt').read_bytes().replace(b'\r\n', b'\n'):
            raise ValueError('unexpected generated README')
        generated[readme] = {'bytes': (source / readme).stat().st_size, 'sha256': native.digest(source / readme)}
    check_sources(source, expected, generated)
    audit = audit_configuration(build, laszip, boost, stage / 'lib',
                                run([ninja, '-C', build, '-t', 'commands'], 'link-audit', capture=True).decode())
    (output / 'configuration.json').write_text(json.dumps(audit, indent=2) + '\n')
    run([cmake, '--build', build, '--parallel', '1'], 'liblas-build', 1200)
    run([cmake, '--install', build], 'liblas-install')
    if dependency != {'laszip': native.inventory(laszip), 'boost': native.inventory(stage)}:
        raise ValueError('dependency changed during core build')
    probe = output / 'LibLASSourceProbe.cpp'
    shutil.copyfile(HERE / probe.name, probe)
    bad = output / 'original-truncated.laz'
    bad.write_bytes(bytes.fromhex((HERE / 'TruncatedLAZ.hex').read_text()))
    if native.digest(bad) != lock['malformed_fixture_sha256']:
        raise ValueError('immutable crash fixture mismatch')
    base = [cxx, '-std=c++11', '-O1', '-I' + str(prefix / 'include'), '-I' + str(boost), str(probe),
            '-L' + str(prefix / 'lib'), '-Wl,--disable-new-dtags,-rpath,' + str(prefix / 'lib'),
            '-llas_c', '-llas', '-pthread', '-ldl']
    run([*base, '-o', output / 'consumer'], 'consumer-compile')
    plain = output / 'plain'
    plain.mkdir()
    text = run([output / 'consumer', plain, bad], 'consumer', 20, True).decode()
    loaded = loaded_libraries(text, prefix)
    if 'immutable_original_truncated_laz_rejected_by_cpp_and_c=true' not in text:
        raise ValueError('incomplete actual consumer proof')
    partial = [line.split('=', 1)[1] for line in text.splitlines()
               if line.startswith('existing_truncated_las_partial_points=')]
    if len(partial) != 1 or not partial[0].isdigit() or not 0 <= int(partial[0]) < 3:
        raise ValueError('missing truncated LAS characterization')
    run([*base, '-g', '-fno-omit-frame-pointer', '-fsanitize=address,undefined',
         '-o', output / 'consumer-asan'], 'consumer-asan-compile')
    asan = output / 'asan'
    asan.mkdir()
    run([output / 'consumer-asan', asan, bad], 'consumer-asan', 30,
        override=dict(env, ASAN_OPTIONS='detect_leaks=0:abort_on_error=1:symbolize=1',
                      UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    libs = [library, *sorted((stage / 'lib').glob('*.a'))]
    pic = output / 'liblas-dependencies-pic-check.so'
    run([cxx, '-shared', '-Wl,--whole-archive', *libs, '-Wl,--no-whole-archive',
         '-Wl,--no-undefined', '-pthread', '-ldl', '-lrt', '-o', pic], 'pic-link')
    if b'TEXTREL' in run([tools['readelf']['path'], '-d', pic], 'pic-inspect', capture=True):
        raise ValueError('PIC link contains TEXTREL')
    closure = run(['ldd', output / 'consumer'], 'runtime-closure', capture=True).decode()
    if 'not found' in closure:
        raise ValueError('runtime library missing')
    runtime = {str(Path(word).resolve()): native.digest(Path(word)) for line in closure.splitlines()
               for word in line.split() if word.startswith('/') and Path(word).is_file()}
    licenses = prefix / 'licenses'
    licenses.mkdir()
    for name, item in lock['licenses'].items():
        path = source / item['source']
        if native.digest(path) != item['sha256']:
            raise ValueError('license checksum mismatch')
        shutil.copyfile(path, licenses / name)
    check_sources(source, expected, generated)
    if start_recipe != recipe() or native.digest(probe) != start_recipe[probe.name]:
        raise ValueError('recipe or probe changed during build')
    if dependency != {'laszip': native.inventory(laszip), 'boost': native.inventory(stage)}:
        raise ValueError('dependency changed during probe')
    verify_archives(cache, lock)
    for item in tools.values():
        if native.digest(Path(item['path'])) != item['sha256']:
            raise ValueError('build tool changed during execution')
    used = disk_usage(output, cache)
    complete = {'schema_version': 1, 'profile': 'public-las-native', 'revision': REVISION,
                'recipe': start_recipe, 'tools': tools, 'source_inventory_sha256': native.digest(output / 'sources.json'),
                'generated_source_files': generated, 'installed': native.inventory(prefix),
                'dependency': dependency, 'loaded_libraries': loaded, 'runtime_closure': runtime,
                'probe_outputs': probe_outputs(output), 'disk_bytes_output_and_cache': used,
                'build_jobs': 1, 'las_laz_semantics': True, 'seek_reset_error_probes': True,
                'malformed_laz_zero_points_and_explicit_errors': True, 'consumer_asan_ubsan': True,
                'vendor_sanitizer_instrumentation': False, 'whole_archive_pic': True,
                'known_truncated_uncompressed_las_partial_points': int(partial[0]), 'general_malformed_input_safety': False,
                'kernel_sdk_acceptance': False, 'jni_or_renderer_acceptance': False,
                'texture_fill_acceptance': False, 'takx_acceptance': False, 'target_image_abi_acceptance': False}
    (output / 'complete.json').write_text(json.dumps(complete, indent=2) + '\n')
    print('Public libLAS/LASzip source fixture, decoder guards and PIC proof passed')


if __name__ == '__main__':
    main()
