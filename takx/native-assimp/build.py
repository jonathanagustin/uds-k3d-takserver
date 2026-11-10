#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in source-built Assimp and matching ordinary Java/JNI fixture."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil

HERE = Path(__file__).resolve().parent
HELPERS = {'native': HERE.parent / 'native-deps/build.py', 'las': HERE.parent / 'native-las/build.py'}
MODULES = {}
for name, path in HELPERS.items():
    spec = importlib.util.spec_from_file_location('assimp_' + name, path)
    MODULES[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULES[name])
native, las = MODULES['native'], MODULES['las']
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
PATCHES = {'patches/assimp-public-static-core.patch': ('assimp/CMakeLists.txt',
           '10909ba5c6e2403e26df14cd4c545a747ce28bce7d72af880b9faa2479b109e1',
           '6977829e6a31f5d34f9fe7f885fe062deaea26de428c65fe6590008d578dae0f'),
           'patches/jassimp-pending-exceptions.patch': ('assimp/port/jassimp/jassimp-native/src/jassimp.cpp',
           '4779b6cd1d25dbd180a99c44b2d899dede8df1c58815734da7844f70ac90295d',
           '735b3f5485a8427c0aa712b7cb293e3ae3f3bec30778fcd0089ffb4f4025d1a5')}
LICENSES = {'Clipper.txt': {'sha256': '710f22ccbfde6bef1898116376c7e32030c2940c72e1eaa0a89b980c9552a541',
                 'source': 'assimp/contrib/clipper/License.txt'},
 'IrrXML.txt': {'sha256': '323d576b9248b058ef3bfa42bf4f0976ea814420de880bb5157eccb6e2ac924d',
                'source': 'assimp/contrib/irrXML/irrXML.h'},
 'Open3DGC.txt': {'sha256': '9af25d729673dc839d308b131e1d08048baba4cc550331002392bfa1d28a9fd9',
                  'source': 'assimp/contrib/Open3DGC/o3dgcTools.cpp'},
 'OpenDDL.txt': {'sha256': '656597ef86119e4a526fb8621e0112b95051cf9d63a311b09b3a73346da00ead',
                 'source': 'assimp/contrib/openddlparser/LICENSE'},
 'Poly2Tri.txt': {'sha256': 'a4d34b9e99a7f11d095ba330da5a4723ec00b019ae1ba42cba46ad1d89902c4e',
                  'source': 'assimp/contrib/poly2tri/LICENSE'},
 'RapidJSON.txt': {'sha256': 'a140e5d46fe734a1c78f1a3c3ef207871dd75648be71fdda8e309b23ab8b1f32',
                   'source': 'assimp/contrib/rapidjson/license.txt'},
 'assimp': {'sha256': 'a26ccc3dbf2f58ea99c100945a8a126fa0f9f4d7fd2b49aa8bdb8e09355864d8',
            'source': 'assimp/LICENSE'},
 'minizip.txt': {'sha256': 'ddad0b271ab2ee40ffaf9a3496a67fffda00b82c0e93688fb640a2ec3bac4150',
                 'source': 'assimp/contrib/unzip/unzip.h'},
 'zlib': {'sha256': '845efc77857d485d91fb3e0b884aaa929368c717ae8186b66fe1ed2495753243',
          'source': 'zlib-1.3.1/LICENSE'}}
FILES = ('build.py', 'inputs.lock.json', 'AssimpSourceProbe.cpp', 'AssimpCSourceProbe.c',
         'JassimpValidProbe.java', *PATCHES)
NATIVE_METHODS = {name: '()I' for name in ('getVKeysize', 'getQKeysize', 'getV3Dsize',
                  'getfloatsize', 'getintsize', 'getuintsize', 'getdoublesize', 'getlongsize')} | {
                  'getErrorString': '()Ljava/lang/String;',
                  'aiImportFile': '(Ljava/lang/String;JLjassimp/AiIOSystem;)Ljassimp/AiScene;'}


def recipe():
    return {name: native.digest(HERE / name) for name in FILES} | {
        '../' + str(path.relative_to(HERE.parent)): native.digest(path) for path in HELPERS.values()}


def validate_lock(lock):
    if lock.get('schema_version') != 1 or lock.get('revision') != REVISION:
        raise ValueError('unsupported Assimp lock')
    pinned = {'assimp': ('depends/assimp-4.0.1-mod.tar.gz', 45185943,
                        '459eadafbb84251a93f94c70f2fd8922c169911ff89fe526f1529bac6f699ae0', 2149, 1905, 120685648),
              'zlib-1.3.1': ('takthirdparty/distfiles/zlib.tar.gz', 1512791,
                        '9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23', 290, 253, 4390808)}
    if set(lock.get('archives', {})) != set(pinned) or set(lock.get('patches', {})) != set(PATCHES):
        raise ValueError('unreviewed archive or patch selection')
    for name, (path, size, sha, members, files, expanded) in pinned.items():
        item = lock['archives'][name]
        if (item.get('url') != 'https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/' + REVISION + '/' + path or
                (item.get('bytes'), item.get('sha256'), item.get('members'), item.get('regular_files'), item.get('expanded_bytes')) !=
                (size, sha, members, files, expanded)):
            raise ValueError('archive differs from official pin')
    for name, (source, before, after) in PATCHES.items():
        item = lock['patches'][name]
        if (item.get('source'), item.get('before_sha256'), item.get('after_sha256')) != (source, before, after):
            raise ValueError('patch source identity mismatch')
        if native.digest(HERE / name) != item.get('sha256'):
            raise ValueError('patch checksum mismatch')
    if lock.get('tools') != {'gcc': '14.2.0', 'cmake': '3.31.6', 'ninja': '1.11.1.git.kitware.jobserver-1',
                             'jdk_release': '17.0.21+9', 'java_release': 11}:
        raise ValueError('unreviewed toolchain')
    if lock.get('licenses') != LICENSES:
        raise ValueError('license paths/hashes differ from reviewed notices')
    for name, item in lock['licenses'].items():
        if len(native.relative(name).parts) != 1 or native.relative(item['source']).parts[0] not in pinned:
            raise ValueError('unsafe license selection')
        if not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')):
            raise ValueError('license hash missing')


def validate_paths(output, cache, jdk):
    output, cache, jdk = (native.external(path) for path in (output, cache, jdk))
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('output must be new and separate from cache')
    if output == jdk or output in jdk.parents or jdk in output.parents or cache == jdk or cache in jdk.parents or jdk in cache.parents:
        raise ValueError('JDK must be separate from output/source/cache')
    return output, cache, jdk


def environment(cc, cxx):
    env = las.environment({'cc': {'path': cc}, 'cxx': {'path': cxx}})
    for name in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH'):
        env.pop(name, None)
    return env


def freeze_tree(root):
    values = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('source symlink refused')
        if path.is_file():
            values[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return values


def check_sources(root, expected):
    if freeze_tree(root) != expected:
        raise ValueError('source inventory changed')


def sdk_inventory(root):
    values = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            if root.resolve() not in path.resolve().parents:
                raise ValueError('JDK link leaves prefix')
            values[str(path.relative_to(root))] = {'symlink': os.readlink(path)}
        elif path.is_file():
            values[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    if not {'bin/java', 'bin/javac', 'bin/jar', 'bin/javap', 'include/jni.h', 'include/linux/jni_md.h'} <= set(values):
        raise ValueError('complete Linux JDK required')
    return values


def native_signatures(text):
    methods, pending = {}, None
    for line in text.splitlines():
        if ' native ' in line:
            pending = re.search(r'\b(\w+)\(', line).group(1)
        elif pending and 'descriptor:' in line:
            if pending in methods:
                raise ValueError('duplicate native descriptor')
            methods[pending] = line.split('descriptor:', 1)[1].strip()
            pending = None
    if methods != NATIVE_METHODS:
        raise ValueError('Java native signatures differ')
    return methods


def mapped_libraries(text, paths):
    expected = {str(p.resolve()) for p in paths}
    observed = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith('mapped_library=')]
    if len(observed) != 2 or set(observed) != expected:
        raise ValueError('foreign or incomplete native mappings')
    return {name: native.digest(Path(name)) for name in observed}


def audit_core(build, source, zprefix, commands):
    cache = {}
    for line in (build / 'CMakeCache.txt').read_text().splitlines():
        if '=' in line and not line.startswith(('#', '//')):
            key, value = line.split('=', 1)
            cache[key.split(':', 1)[0]] = value
    if (Path(cache['PUBLIC_ZLIB_INCLUDE']).resolve() != (zprefix / 'include').resolve() or
            Path(cache['PUBLIC_ZLIB_LIBRARY']).resolve() != (zprefix / 'lib/libz.a').resolve()):
        raise ValueError('foreign zlib prefix')
    for key in ('ASSIMP_DOUBLE_PRECISION', 'ASSIMP_NO_EXPORT', 'ASSIMP_BUILD_JASSIMP', 'SYSTEM_IRRXML'):
        if cache[key] != 'OFF':
            raise ValueError('core feature profile differs')
    importers = {k: v for k, v in cache.items() if re.fullmatch(r'ASSIMP_BUILD_.*_IMPORTER', k)}
    if len(importers) != 48 or importers.get('ASSIMP_BUILD_NONFREE_C4D_IMPORTER') != 'OFF' or any(
            value != 'ON' for key, value in importers.items() if key != 'ASSIMP_BUILD_NONFREE_C4D_IMPORTER'):
        raise ValueError('default public importer set differs')
    links = []
    for line in commands.splitlines():
        tokens = shlex.split(line)
        if '-shared' not in tokens:
            continue
        if ('-Wl,--no-undefined' not in tokens or str(zprefix / 'lib/libz.a') not in tokens or
                not any(t.endswith('libIrrXML.a') for t in tokens) or
                any(t in ('-lz', '-lminizip', '-lIrrXML') or 'libz.so' in t or Path(t).name.startswith(('libjassimp.', 'jassimp.cpp')) for t in tokens)):
            raise ValueError('core link bypasses source dependency closure')
        links.append(line)
    if len(links) != 1:
        raise ValueError('unexpected core shared link count')
    files = []
    for item in json.loads((build / 'compile_commands.json').read_text()):
        path = Path(item['file']).resolve()
        tokens = shlex.split(item['command'])
        if source.resolve() not in path.parents or '-fPIC' not in tokens or 'jassimp-native' in str(path):
            raise ValueError('unexpected core translation unit')
        for token in tokens:
            if token.startswith('-I') and len(token) > 2:
                inc = Path(token[2:]).resolve()
                if not any(inc == p.resolve() or p.resolve() in inc.parents for p in (source, build, zprefix)) or '/contrib/zlib' in str(inc):
                    raise ValueError('foreign dependency include')
        files.append(str(path))
    if len(files) != 202:
        raise ValueError('core translation-unit count differs')
    for fragment in ('/contrib/unzip/', '/contrib/irrXML/', '/contrib/openddlparser/', '/contrib/Open3DGC/'):
        if not any(fragment in name for name in files):
            raise ValueError('bundled dependency omitted')
    return {'importers': importers, 'translation_units': len(files), 'link_commands': links}


def verify_pic_closure(text, core, expected_sha):
    if ('TEXTREL' in text or 'Shared library: [libassimp.so.4]' not in text or
            re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]', text) != [str(core.resolve().parent)]):
        raise ValueError('PIC probe lacks the exact genuine core dependency')
    if core.is_symlink() or not core.is_file() or native.digest(core) != expected_sha:
        raise ValueError('PIC core dependency integrity mismatch')


def outputs(root):
    names = ('consumer-cpp', 'consumer-c', 'libjassimp.so', 'jassimp.jar', 'dependency-pic-check.so',
             'valid/roundtrip.assbin')
    result = {}
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('missing or nonregular proof output')
        result[name] = {'bytes': path.stat().st_size, 'sha256': native.digest(path)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'cache', 'jdk-home'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name, default in (('cmake', 'cmake'), ('ninja', 'ninja'), ('cc', 'gcc'), ('cxx', 'g++')):
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--fetch-dependencies', action='store_true')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 is validated')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate_lock(lock)
    start_recipe = recipe()
    output, cache, jdk = validate_paths(args.output, args.cache, args.jdk_home)
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    sdk = sdk_inventory(jdk)
    (output / 'jdk-inputs.json').write_text(json.dumps(sdk, sort_keys=True) + '\n')
    cc, cxx = (str(Path(shutil.which(value) or value).resolve()) for value in (args.cc, args.cxx))
    env = environment(cc, cxx)
    commands = []

    def run(command, name, timeout=60, capture=False):
        commands.append({'name': name, 'args': list(map(str, command)), 'timeout': timeout})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        return native.run(list(map(str, command)), output, name, timeout=timeout, env=env, capture=capture)

    tools = {}
    for name, value, flags in [('cc', cc, ['--version']), ('cxx', cxx, ['--version']),
                             ('cmake', args.cmake, ['--version']), ('ninja', args.ninja, ['--version']),
                             ('patch', 'patch', ['--version']), ('nm', 'nm', ['--version']),
                             ('readelf', 'readelf', ['--version']),
                             *[(n, jdk / ('bin/' + n), ['-version']) for n in ('java', 'javac', 'javap')],
                             ('jar', jdk / 'bin/jar', ['--version'])]:
        path = Path(shutil.which(str(value)) or value).resolve()
        version = run([path, *flags], 'tool-' + name, capture=True).decode().strip()
        tools[name] = {'path': str(path), 'sha256': native.digest(path), 'version': version}
    if (any(not tools[n]['version'].splitlines()[0].endswith(' 14.2.0') for n in ('cc', 'cxx')) or
            tools['cmake']['version'].splitlines()[0] != 'cmake version 3.31.6' or
            tools['ninja']['version'] != lock['tools']['ninja'] or tools['javac']['version'] != 'javac 17.0.21' or
            'Temurin-17.0.21+9' not in tools['java']['version']):
        raise ValueError('toolchain differs from reviewed profile')
    source = output / 'source'
    source.mkdir()
    expected = {}
    for name, item in lock['archives'].items():
        archive = native.acquire(cache, item, args.fetch_dependencies)
        expected.update(las.unpack(archive, source, name, item))
        native.verified(archive, item)
    for name, item in lock['patches'].items():
        target = source / item['source']
        if native.digest(target) != item['before_sha256']:
            raise ValueError('patch preimage mismatch')
        directory = source / 'assimp' if name.endswith('assimp-public-static-core.patch') else target.parent
        run([tools['cmake']['path'], '-E', 'chdir', directory, tools['patch']['path'], '--batch', '--binary',
             '--fuzz=0', '-p1', '-i', HERE / name], 'apply-' + Path(name).stem)
        if native.digest(target) != item['after_sha256']:
            raise ValueError('patch postimage mismatch')
        expected[item['source']] = {'bytes': target.stat().st_size, 'sha256': native.digest(target)}
    check_sources(source, expected)
    (output / 'sources.json').write_text(json.dumps(expected, sort_keys=True) + '\n')
    las.disk_usage(output, cache)
    cmake, ninja = tools['cmake']['path'], tools['ninja']['path']
    zsrc, zbuild, zprefix = source / 'zlib-1.3.1', output / 'zlib-build', output / 'zlib-install'
    run([cmake, '-S', zsrc, '-B', zbuild, '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM=' + ninja,
         '-DCMAKE_C_COMPILER=' + cc, '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
         '-DZLIB_BUILD_EXAMPLES=OFF'], 'zlib-configure')
    old = expected.pop('zlib-1.3.1/zconf.h')
    if (zsrc / 'zconf.h').exists() or native.digest(zsrc / 'zconf.h.included') != old['sha256']:
        raise ValueError('zlib source header rename differs')
    expected['zlib-1.3.1/zconf.h.included'] = old
    check_sources(source, expected)
    run([cmake, '--build', zbuild, '--target', 'zlibstatic', '--parallel', '1'], 'zlib-build', 1200)
    (zprefix / 'lib').mkdir(parents=True)
    (zprefix / 'include').mkdir()
    for origin, target in ((zbuild / 'libz.a', zprefix / 'lib/libz.a'), (zsrc / 'zlib.h', zprefix / 'include/zlib.h'),
                           (zbuild / 'zconf.h', zprefix / 'include/zconf.h')):
        shutil.copyfile(origin, target)
    zreceipt = native.inventory(zprefix)
    build, prefix = output / 'core-build', output / 'install'
    run([cmake, '-S', source / 'assimp', '-B', build, '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM=' + ninja,
         '-DCMAKE_C_COMPILER=' + cc, '-DCMAKE_CXX_COMPILER=' + cxx, '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
         '-DCMAKE_SHARED_LINKER_FLAGS=-Wl,--no-undefined', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
         '-DPUBLIC_ZLIB_PREFIX=' + str(zprefix), '-DBUILD_SHARED_LIBS=ON', '-DBUILD_FRAMEWORK=OFF',
         '-DASSIMP_DOUBLE_PRECISION=OFF', '-DASSIMP_NO_EXPORT=OFF', '-DASSIMP_BUILD_ALL_IMPORTERS_BY_DEFAULT=ON',
         '-DASSIMP_BUILD_NONFREE_C4D_IMPORTER=OFF', '-DSYSTEM_IRRXML=OFF', '-DASSIMP_BUILD_JASSIMP=OFF',
         '-DASSIMP_BUILD_ASSIMP_TOOLS=OFF', '-DASSIMP_BUILD_SAMPLES=OFF', '-DASSIMP_BUILD_TESTS=OFF',
         '-DBUILD_DOCS=OFF'], 'core-configure', 180)
    audit = audit_core(build, source, zprefix, run([ninja, '-C', build, '-t', 'commands', 'assimp'], 'link-audit', capture=True).decode())
    if 'jassimp' in run([ninja, '-C', build, '-t', 'targets', 'all'], 'target-audit', capture=True).decode():
        raise ValueError('unexpected core JNI target')
    (output / 'configuration.json').write_text(json.dumps(audit, indent=2) + '\n')
    check_sources(source, expected)
    las.disk_usage(output, cache)
    run([cmake, '--build', build, '--target', 'assimp', '--parallel', '1'], 'core-build', 1200)
    run([cmake, '--install', build], 'core-install')
    las.disk_usage(output, cache)
    corelib = prefix / 'lib/libassimp.so.4.1.0'
    installed = native.inventory(prefix)
    for name in ('AssimpSourceProbe.cpp', 'AssimpCSourceProbe.c', 'JassimpValidProbe.java'):
        shutil.copyfile(HERE / name, output / name)
    common = ['-O1', '-I' + str(prefix / 'include'), '-L' + str(prefix / 'lib'),
              '-Wl,--disable-new-dtags,-rpath,' + str(prefix / 'lib'), '-lassimp']
    run([cxx, '-std=c++11', output / 'AssimpSourceProbe.cpp', *common, '-ldl', '-o', output / 'consumer-cpp'], 'cpp-consumer-compile')
    valid = output / 'valid'
    valid.mkdir()
    text = run([output / 'consumer-cpp', valid], 'valid-cpp-consumer', 30, True).decode()
    lines = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith('loaded_libassimp=')]
    if lines != [str(corelib.resolve())] or 'valid_cpp_c_geometry_material_transform_uv_normal_export_roundtrip=true' not in text:
        raise ValueError('valid core provenance/fixture incomplete')
    run([cc, '-std=c11', output / 'AssimpCSourceProbe.c', *common, '-lm', '-o', output / 'consumer-c'], 'c-consumer-compile')
    run([output / 'consumer-c', valid / 'roundtrip.assbin'], 'valid-c-consumer', 30)
    classes = output / 'classes'
    classes.mkdir()
    java = sorted((source / 'assimp/port/jassimp/jassimp/src/jassimp').glob('*.java'))
    if len(java) != 42:
        raise ValueError('matching Java source count differs')
    run([tools['javac']['path'], '--release', '11', '-encoding', 'UTF-8', '-g:none', '-d', classes, *java], 'java-bindings-compile')
    jar, library = output / 'jassimp.jar', output / 'libjassimp.so'
    run([tools['jar']['path'], '--create', '--file', jar, '-C', classes, '.'], 'java-bindings-jar')
    methods = native_signatures(run([tools['javap']['path'], '-classpath', jar, '-s', '-p', 'jassimp.Jassimp'], 'java-signatures', capture=True).decode())
    run([cxx, '-std=c++11', '-O3', '-DNDEBUG', '-fPIC', '-fvisibility=hidden', '-shared',
         '-I' + str(prefix / 'include'), '-I' + str(jdk / 'include'), '-I' + str(jdk / 'include/linux'),
         source / 'assimp/port/jassimp/jassimp-native/src/jassimp.cpp', corelib, '-Wl,--no-undefined',
         '-Wl,--disable-new-dtags,-rpath,' + str(prefix / 'lib'), '-o', library], 'jni-one-tu-build', 180)
    exports = run([tools['nm']['path'], '-D', '--defined-only', library], 'jni-signatures', capture=True).decode()
    if {line.split()[-1] for line in exports.splitlines() if 'Java_jassimp_Jassimp_' in line} != {'Java_jassimp_Jassimp_' + name for name in methods}:
        raise ValueError('JNI exports differ from Java declarations')
    probe_classes = output / 'probe-classes'
    probe_classes.mkdir()
    run([tools['javac']['path'], '--release', '11', '-classpath', jar, '-d', probe_classes,
         output / 'JassimpValidProbe.java'], 'java-consumer-compile')
    fixture = valid / 'roundtrip.assbin'
    fixture_sha = native.digest(fixture)
    java_text = run([tools['java']['path'], '-ea', '-Xcheck:jni', '-Djava.awt.headless=true', '-cp',
                     str(probe_classes) + ':' + str(jar), 'JassimpValidProbe', library, corelib, fixture, jar],
                    'valid-java-jni-consumer', 30, True).decode()
    if 'WARNING' in java_text or 'FATAL' in java_text or 'valid_java_jni_geometry_material_transform_uv_normal_interop=true' not in java_text:
        raise ValueError('valid Java/JNI control failed or emitted warnings')
    mapped = mapped_libraries(java_text, (library, corelib))
    pic = output / 'dependency-pic-check.so'
    run([cxx, '-shared', '-Wl,--whole-archive', zprefix / 'lib/libz.a', build / 'contrib/irrXML/libIrrXML.a',
         '-Wl,--no-whole-archive', corelib, '-Wl,--no-undefined',
         '-Wl,--disable-new-dtags,-rpath,' + str(corelib.parent), '-o', pic], 'whole-archive-pic-link')
    for name, path in (('dependencies', pic), ('core', corelib), ('jni', library)):
        dynamic = run([tools['readelf']['path'], '-d', path], 'pic-' + name, capture=True).decode()
        if 'TEXTREL' in dynamic:
            raise ValueError('TEXTREL in native output')
        if name == 'dependencies':
            verify_pic_closure(dynamic, corelib, mapped[str(corelib.resolve())])
    closure = run(['ldd', output / 'consumer-cpp'], 'runtime-closure', capture=True).decode()
    if 'not found' in closure:
        raise ValueError('runtime closure missing library')
    runtime = {str(Path(word).resolve()): native.digest(Path(word)) for line in closure.splitlines()
               for word in line.split() if word.startswith('/') and Path(word).is_file()}
    if any('libz.so' in name or 'minizip' in name or 'IrrXML.so' in name for name in runtime):
        raise ValueError('host third-party runtime fallback')
    if installed != native.inventory(prefix) or zreceipt != native.inventory(zprefix):
        raise ValueError('built dependency changed during controls')
    licenses = prefix / 'licenses'
    licenses.mkdir()
    for name, item in lock['licenses'].items():
        origin = source / item['source']
        if native.digest(origin) != item['sha256']:
            raise ValueError('license checksum mismatch')
        shutil.copyfile(origin, licenses / name)
    check_sources(source, expected)
    if sdk_inventory(jdk) != sdk or recipe() != start_recipe or native.digest(fixture) != fixture_sha:
        raise ValueError('SDK/recipe/fixture changed during build')
    for name in ('AssimpSourceProbe.cpp', 'AssimpCSourceProbe.c', 'JassimpValidProbe.java'):
        if native.digest(output / name) != start_recipe[name]:
            raise ValueError('consumer source changed during build')
    for item in tools.values():
        if native.digest(Path(item['path'])) != item['sha256']:
            raise ValueError('build tool changed during execution')
    las.verify_archives(cache, lock)
    used = las.disk_usage(output, cache)
    record = {'schema_version': 1, 'profile': 'public-assimp-native', 'recipe': start_recipe,
              'source_revision': REVISION, 'archive_identity': '4.0.1-mod', 'actual_core_version': '4.1.0',
              'soname': 4, 'zlib_version': '1.3.1', 'tools': tools, 'java_source_files': 42,
              'native_java_signatures': methods, 'native_jni_translation_units': 1,
              'mapped_libraries': mapped, 'runtime_closure': runtime, 'installed': native.inventory(prefix),
              'zlib_installed': zreceipt, 'source_inventory_sha256': native.digest(output / 'sources.json'),
              'source_postimages': expected, 'jdk_inventory_sha256': native.digest(output / 'jdk-inputs.json'),
              'probe_outputs': outputs(output), 'java_probe_classes': native.inventory(probe_classes), 'disk_bytes_output_cache': used, 'build_jobs': 1,
              'valid_cpp_c_java_interop': True, 'xcheck_jni_warning_count': 0, 'strict_pic_links': True,
              'pic_probe_core_dependency': {'path': str(corelib.resolve()), 'sha256': mapped[str(corelib.resolve())],
                                            'soname': 'libassimp.so.4'},
              'fault_parser_or_failure_path_tests_run': False, 'upstream_full_test_suite_ran': False,
              'full_ttp_acceptance': False, 'kernel_sdk_acceptance': False, 'full_engine_jni_acceptance': False,
              'renderer_texturefill_acceptance': False, 'takx_runtime_acceptance': False, 'target_image_abi_acceptance': False}
    (output / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Source-built Assimp and ordinary matching Java/JNI component controls passed')


if __name__ == '__main__':
    main()
