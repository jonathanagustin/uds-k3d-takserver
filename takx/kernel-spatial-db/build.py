#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in joined legacy Kernel spatial database source profile, not a full SDK."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
HELPERS = {name: HERE.parent / path for name, path in {
    'native': 'native-deps/build.py', 'las': 'native-las/build.py',
    'geos': 'native-geos/build.py', 'proj': 'native-proj/build.py',
    'sqlcipher': 'native-sqlcipher/build.py', 'zlib': 'native-assimp/build.py'}.items()}
MODULES = {}
for name, path in HELPERS.items():
    spec = importlib.util.spec_from_file_location('spatial_db_' + name, path)
    MODULES[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULES[name])
native, las, geos = (MODULES[name] for name in ('native', 'las', 'geos'))
LOCK = json.loads((HERE / 'inputs.lock.json').read_text())
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
KERNEL = 'takkernel/engine/src/main/cpp'
SOURCES = ('db/SpatiaLiteDB.cpp', 'db/Database.cpp', 'db/Cursor.cpp', 'db/Statement.cpp',
           'port/String.cpp', 'port/StringBuilder.cpp', 'port/Platform.cpp',
           'thread/Lock.cpp', 'thread/Mutex.cpp', 'thread/Cond.cpp', 'thread/Monitor.cpp',
           'thread/impl/ThreadImpl_common.cpp', 'thread/impl/ThreadImpl_libpthread.cpp',
           'util/Blob.cpp', 'util/Logging2.cpp')
FILES = ('build.py', 'inputs.lock.json', 'KernelSpatialDatabase.cpp')


def recipe():
    return {name: native.digest(HERE / name) for name in FILES} | {
        '../' + str(path.relative_to(HERE.parent)): native.digest(path) for path in HELPERS.values()} | {
        '../native-geos/run-in.py': native.digest(geos.HERE / 'run-in.py')}


def validate_lock(lock):
    if lock != LOCK or lock['revision'] != REVISION:
        raise ValueError('unreviewed joined dependency selection')


def normalized_patch(data, entry):
    norm = entry['normalization']
    if norm:
        old, new = norm['old_context'].encode(), norm['new_context'].encode()
        if data.count(old) != 1 or not old.startswith(b' ') or not new.startswith(b' '):
            raise ValueError('official patch context is not unique')
        result = data.replace(old, new)
        semantic = lambda b: [line for line in b.splitlines() if line.startswith((b'+', b'-'))]
        if semantic(data) != semantic(result):
            raise ValueError('patch normalization changes semantic diff')
        if len(result) != norm['bytes'] or hashlib.sha256(result).hexdigest() != norm['sha256']:
            raise ValueError('normalized patch bytes differ')
        return result
    return data


def patch_images(src, entry, phase):
    for name, images in entry['files'].items():
        if native.digest(src / name) != images[phase]:
            raise ValueError('official patch source image differs')


def provider_contract(receipt, name):
    """Normative owned producer/source contract; not publisher authentication."""
    producer = MODULES[name]
    producer.validate_lock(json.loads((producer.HERE / 'inputs.lock.json').read_text()))
    if receipt.get('recipe') != producer.recipe():
        raise ValueError('dependency producer recipe differs')
    spec = LOCK['dependencies'][name]
    if spec['producer'] != producer.HERE.name:
        raise ValueError('dependency producer family differs')
    if name in ('proj','geos'):
        if (receipt.get('source_revision') != REVISION or receipt.get('profile') != spec['profile'] or
                receipt.get('version') != spec['version'] or receipt.get('archive') != producer.ARCHIVE or
                receipt.get('license') != producer.LICENSE or receipt.get('strict_pic') is not True):
            raise ValueError('dependency source/archive/version/PIC scope differs')
        if name == 'proj':
            if receipt.get('source_patches') != [] or receipt.get('known_coordinates_forward_inverse') is not True:
                raise ValueError('PROJ positive/source scope differs')
        elif receipt.get('source_patch') != producer.PATCH or receipt.get('geometry_and_error_controls') is not True:
            raise ValueError('GEOS positive/source patch scope differs')
    elif name == 'sqlcipher':
        if (spec['sqlite_version'] != producer.PINNED['provenance']['sqlcipher_sqlite_version'] or
                producer.PINNED['archives']['sqlcipher']['root'] != 'sqlcipher-' + spec['sqlcipher_version'] or
                producer.PINNED['archives']['openssl']['root'] != 'openssl-' + spec['openssl_version']):
            raise ValueError('SQLCipher normative producer versions differ')
        if (receipt.get('archives') != producer.PINNED['archives'] or
                receipt.get('licenses') != producer.PINNED['licenses'] or
                any(receipt.get(k) is not True for k in ('source_posthash_verified','encryption_controls','whole_archive_PIC','fresh_entrypoint'))):
            raise ValueError('SQLCipher source/archive/positive scope differs')
    else:
        if (receipt.get('source_revision') != REVISION or receipt.get('profile') != spec['profile'] or
                receipt.get('actual_core_version') != spec['actual_core_version'] or
                receipt.get('zlib_version') != spec['zlib_version'] or
                receipt.get('valid_cpp_c_java_interop') is not True or receipt.get('strict_pic_links') is not True):
            raise ValueError('Assimp/zlib source/version/positive scope differs')


def dependency(root, name):
    root = native.external(root)
    receipt_path = root / 'complete.json'
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError('dependency receipt unavailable')
    receipt_hash = native.digest(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    provider_contract(receipt, name)
    producer = MODULES[name]
    if name in ('proj','geos'):
        producer.check_sources(root / 'source', receipt['source_inventory'])
    elif name == 'sqlcipher':
        inputs = json.loads((root / 'source-inputs.json').read_text())
        if len(inputs) != receipt['source_files']:
            raise ValueError('SQLCipher source inventory count differs')
        producer.check_sources(root / 'source', inputs)
        producer.verify_probes(root, receipt['probe_outputs'])
    else:
        if (native.digest(root / 'sources.json') != receipt['source_inventory_sha256'] or
                producer.freeze_tree(root / 'source') != receipt['source_postimages']):
            raise ValueError('Assimp/zlib source inventory differs')
    groups = [('zlib-install', receipt['zlib_installed'])] if name == 'zlib' else [('install', receipt['installed'])] if name != 'sqlcipher' else [
        ('sqlcipher-install', receipt['installed']['sqlcipher']),
        ('openssl-install', receipt['installed']['openssl'])]
    for subdir, inventory in groups:
        if native.inventory(root / subdir) != inventory:
            raise ValueError('dependency installed bytes differ')
    las.verify_runtime(receipt['runtime_closure'])
    for tool in receipt['tools'].values():
        if native.digest(Path(tool['path'])) != tool['sha256']:
            raise ValueError('dependency build tool identity differs')
    if native.digest(receipt_path) != receipt_hash:
        raise ValueError('dependency receipt changed during validation')
    return receipt | {'input_receipt_sha256': receipt_hash}


def kernel_inventory(source):
    if native.git(source, 'rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('Kernel source revision differs')
    raw = native.git(source, 'ls-tree', '-r', '-z', REVISION, '--', KERNEL)
    found = {}
    for entry in raw.rstrip(b'\0').split(b'\0'):
        meta, name = entry.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        rel = name.decode(); path = source / native.relative(rel)
        if kind != 'blob' or mode not in ('100644', '100755') or path.is_symlink() or not path.is_file():
            raise ValueError('Kernel source is unavailable or nonregular')
        data = path.read_bytes()
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
            raise ValueError('Kernel source differs from pinned Git bytes')
        found[rel] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    if not found or any(KERNEL + '/' + name not in found for name in SOURCES):
        raise ValueError('Kernel source inventory incomplete')
    return found


def audit_zlib_headers(text, prefix):
    found = [Path(p).resolve() for p in re.findall(r'/[^\s\\]+', text) if Path(p).name in ('zlib.h','zconf.h')]
    if {p.name for p in found} != {'zlib.h','zconf.h'} or any(p.parent != prefix.resolve() for p in found):
        raise ValueError('Spatialite zlib headers leave verified source prefix')
    return {str(p):native.digest(p) for p in found}


def archive_objects(path):
    """Inspect ordinary GNU ar without extracting or rewriting genuine objects."""
    size = path.stat().st_size
    count = 0
    with path.open('rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError('static provider is not an ordinary archive')
        while stream.tell() < size:
            header = stream.read(60)
            if len(header) != 60 or header[58:] != b'`\n':
                raise ValueError('malformed static archive header')
            try: length = int(header[48:58].strip())
            except ValueError: raise ValueError('malformed static member size') from None
            if length < 0 or stream.tell() + length > size:
                raise ValueError('static member exceeds archive boundary')
            name = header[:16].strip()
            special = name in (b'/', b'//', b'/SYM64/')
            if not special:
                prefix = stream.read(min(length, 18))
                if len(prefix) < 18 or prefix[:4] != b'\x7fELF' or prefix[4:6] != b'\x02\x01' or prefix[16:18] != b'\x01\x00':
                    raise ValueError('nested archive or non-ELF relocatable member')
                count += 1
                stream.seek(length - len(prefix), 1)
            else:
                stream.seek(length, 1)
            if length % 2:
                if stream.read(1) != b'\n': raise ValueError('malformed archive member padding')
        if stream.tell() != size or not count:
            raise ValueError('empty or incomplete static archive')
    return count


def paths(output, cache):
    output, cache = native.external(output), native.external(cache)
    if output.exists() or output == cache or output in cache.parents or cache in output.parents:
        raise ValueError('new separate external output required')
    return output, cache


def disk_bound(output, cache):
    total = sum(p.stat().st_size for root in (output, cache) for p in root.rglob('*')
                if p.is_file() and not p.is_symlink())
    if total > 4 * 1024 ** 3:
        raise ValueError('joined profile exceeds 4 GiB output/cache bound')
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'cache', 'source', 'proj-proof', 'geos-proof', 'sqlcipher-proof', 'zlib-proof'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--fetch-dependencies', action='store_true')
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise ValueError('only Linux amd64 component integration selected')
    validate_lock(json.loads((HERE / 'inputs.lock.json').read_text()))
    output, cache = paths(args.output, args.cache)
    output.mkdir(parents=True, mode=0o700); cache.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    initial = recipe()
    source = args.source.resolve()
    kernel = kernel_inventory(source)
    roots = {'proj': args.proj_proof.resolve(), 'geos': args.geos_proof.resolve(),
             'sqlcipher': args.sqlcipher_proof.resolve(), 'zlib': args.zlib_proof.resolve()}
    dependencies = {name: dependency(path, name) for name, path in roots.items()}
    pp, gp = roots['proj'] / 'install', roots['geos'] / 'install'
    zp = roots['zlib'] / 'zlib-install'
    if list((zp / 'lib').glob('libz.so*')):
        raise ValueError('zlib dependency must be source-built static only')
    sp, cp = roots['sqlcipher'] / 'sqlcipher-install', roots['sqlcipher'] / 'openssl-install'
    tools = {}
    for name in ('gcc', 'g++', 'make', 'patch', 'ar', 'ranlib', 'readelf', 'ldd', 'pkg-config'):
        path = Path(shutil.which(name) or name).resolve()
        tools[name] = {'path': str(path), 'sha256': native.digest(path)}
    env = geos.environment(tools['gcc']['path'], tools['g++']['path'])
    for key in list(env):
        if (key.startswith(('ac_cv_', 'CONFIG_', 'OPENSSL_', 'LD_', 'XML_', 'LIBXML_', 'GEOS_', 'PROJ_')) or
                key in ('CPP', 'LIBS', 'CPPFLAGS', 'LDFLAGS', 'CXXFLAGS', 'PKG_CONFIG_PATH', 'PKG_CONFIG_LIBDIR')):
            env.pop(key, None)
    env.update(CC=tools['gcc']['path'], CXX=tools['g++']['path'], AR=tools['ar']['path'],
               RANLIB=tools['ranlib']['path'], CFLAGS='-O2 -fPIC', CXXFLAGS='-O2 -fPIC -std=c++11',
               CONFIG_SITE='/dev/null', LC_ALL='C', OPENSSL_CONF='/dev/null',
               OPENSSL_MODULES=str(output / 'absent-provider-modules'),
               PKG_CONFIG_PATH='', PKG_CONFIG_LIBDIR=str(output / 'absent-pkgconfig'))
    commands = []; deadline = time.monotonic() + 1800

    def run(argv, label, cwd=None, timeout=60, capture=False, extra=None):
        if cwd is not None:
            argv = [sys.executable, geos.HERE / 'run-in.py', cwd, *argv]
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise ValueError('joined profile total deadline exhausted')
        commands.append({'name': label, 'argv': list(map(str, argv)), 'timeout': min(timeout, remaining)})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        data = native.run(list(map(str, argv)), output, label, timeout=min(timeout, remaining),
                          capture=capture, env=env | (extra or {}))
        disk_bound(output, cache)
        return data.decode() if capture else ''

    # Freeze inputs/recipe before the first source compiler invocation.
    freeze = {'recipe': initial, 'kernel': kernel, 'dependency_roots': {k: str(v) for k, v in roots.items()},
              'dependency_contracts': LOCK['dependencies'],
              'input_receipt_sha256': {n:r['input_receipt_sha256'] for n,r in dependencies.items()}, 'tools': tools, 'sources': list(SOURCES)}
    (output / 'frozen-inputs.json').write_text(json.dumps(freeze, indent=2) + '\n')
    for name in tools:
        text = run([tools[name]['path'], '--version'], 'tool-' + name, capture=True)
        tools[name]['version'] = text
    if (not tools['gcc']['version'].splitlines()[0].endswith(' 14.2.0') or
            not tools['g++']['version'].splitlines()[0].endswith(' 14.2.0') or
            tools['make']['version'].splitlines()[0] != 'GNU Make 4.4.1' or
            any(not tools[n]['version'].splitlines()[0].endswith(' 2.44') for n in ('ar','ranlib','readelf'))):
        raise ValueError('joined profile tool versions differ')
    srcs = {}; inventories = {}
    for name, entry in LOCK['archives'].items():
        archive = native.acquire(cache, entry, args.fetch_dependencies)
        target = output / (name + '-source'); target.mkdir()
        inv = las.unpack(archive, target, entry['root'], entry)
        # Restore official archive timestamps; no autoreconf or source regeneration.
        import tarfile
        with tarfile.open(archive) as archive_file:
            for member in archive_file:
                if member.isfile(): os.utime(target / native.relative(member.name), (member.mtime, member.mtime))
        src = target / entry['root']; srcs[name] = src
        if name in LOCK['patches']:
            patch = LOCK['patches'][name]; patch_images(src, patch, 'before')
            original = native.acquire(cache, {k: patch[k] for k in ('url','bytes','sha256')}, args.fetch_dependencies)
            effective = output / (name + '-effective.patch')
            effective.write_bytes(normalized_patch(original.read_bytes(), patch))
            run([tools['patch']['path'], '--fuzz=0', '--no-backup-if-mismatch', '--batch', '-p1', '-i', effective], name + '-patch', src)
            patch_images(src, patch, 'after')
            changed = geos.source_inventory(target)
            wanted = {entry['root'] + '/' + p for p in patch['files']}
            if set(inv) != set(changed) or {p for p in inv if inv[p] != changed[p]} != wanted:
                raise ValueError('unexpected patch source changes')
            inv = changed
        for name_license, digest in LOCK['licenses'].items():
            if name_license.startswith(entry['root'] + '/') and native.digest(target / name_license) != digest:
                raise ValueError('source license bytes differ')
        inventories[name] = inv
    prefixes = {name: output / (name + '-install') for name in srcs}
    builds = {name: output / (name + '-build') for name in srcs}
    for path in builds.values(): path.mkdir()
    ip, xp, lp = (prefixes[name] for name in ('libiconv','libxml2','libspatialite'))
    run([srcs['libiconv'] / 'configure', '--disable-shared', '--enable-static', '--prefix=' + str(ip)], 'iconv-configure', builds['libiconv'], 120)
    run([tools['make']['path'], '-j1'], 'iconv-build', builds['libiconv'], 420)
    run([tools['make']['path'], '-j1', 'install-lib'], 'iconv-install', builds['libiconv'], 60)
    run([srcs['libxml2'] / 'configure', '--disable-shared', '--enable-static', '--without-python', '--without-lzma', '--without-zlib', '--with-iconv=' + str(ip), '--prefix=' + str(xp)], 'xml-configure', builds['libxml2'], 120,
        extra={'CPPFLAGS':'-I' + str(ip / 'include'), 'LDFLAGS':'-L' + str(ip / 'lib')})
    run([tools['make']['path'], '-j1'], 'xml-build', builds['libxml2'], 420)
    run([tools['make']['path'], '-j1', 'install'], 'xml-install', builds['libxml2'], 60)
    generator = srcs['libspatialite'] / 'src/connection_cache/generator'
    run([tools['gcc']['path'], '-O2', '-o', output / 'connection-cache-generator', generator / 'code_generator.c'], 'cache-generator-compile')
    generated = output / 'generated-cache'; generated.mkdir()
    run([output / 'connection-cache-generator', '1024'], 'cache-generator', generated)
    cache_files = list(generated.glob('cache_aux_*.h'))
    if not cache_files: raise ValueError('connection cache generator emitted no headers')
    connection = srcs['libspatialite'] / 'src/connection_cache'
    for path in connection.glob('cache_aux_*.h'): path.unlink()
    for path in cache_files: shutil.copyfile(path, connection / path.name)
    inventories['libspatialite'] = geos.source_inventory(srcs['libspatialite'].parent)
    libs = [lp / 'lib/libspatialite.a', xp / 'lib/libxml2.a', ip / 'lib/libiconv.a', zp / 'lib/libz.a',
            gp / 'lib/libgeos_c.a', gp / 'lib/libgeos.a', pp / 'lib/libproj.a', sp / 'lib/libsqlite3.a', cp / 'lib/libcrypto.a']
    includes = [zp / 'include', sp / 'include', gp / 'include', pp / 'include', ip / 'include', xp / 'include/libxml2', cp / 'include']
    spatial_env = {'CPPFLAGS':' '.join('-I'+str(p) for p in includes),
        'LDFLAGS':' '.join('-L'+str(p / 'lib') for p in (gp,pp,sp,cp,ip,xp,zp)),
        'LIBS':' '.join('-L'+str(p / 'lib') for p in (xp,ip,zp,gp,pp,sp,cp)) + ' -lxml2 -liconv -lz -lgeos_c -lgeos -lproj -lsqlite3 -lcrypto -lstdc++ -ldl -pthread -lm',
        'LIBXML2_CFLAGS':'-I'+str(xp / 'include/libxml2'), 'LIBXML2_LIBS':'-L'+str(xp / 'lib')+' -lxml2 -L'+str(ip / 'lib')+' -liconv',
        'PKG_CONFIG_LIBDIR':str(xp / 'lib/pkgconfig')}
    run([srcs['libspatialite'] / 'configure', '--disable-shared', '--enable-static', '--enable-geos', '--enable-proj', '--enable-iconv', '--enable-libxml2', '--disable-freexl', '--disable-examples', '--with-geosconfig='+str(gp / 'bin/geos-config'), '--prefix='+str(lp)], 'spatialite-configure', builds['libspatialite'], 120, extra=spatial_env)
    run([tools['make']['path'], '-j1'], 'spatialite-build', builds['libspatialite'], 600, extra=spatial_env)
    run([tools['make']['path'], '-j1', 'install'], 'spatialite-install', builds['libspatialite'], 60, extra=spatial_env)
    archive_members = {str(p): archive_objects(p) for p in libs}
    # Demonstrate the actual Spatialite units resolve zlib.h to the bound source prefix.
    zlib_headers = {}
    for unit in ('gaiageo/gg_relations.c', 'gaiageo/gg_xml.c'):
        deps = run([tools['gcc']['path'], '-M', '-I'+str(builds['libspatialite']),
            '-I'+str(srcs['libspatialite'] / 'src/headers'),
            *['-I'+str(p) for p in includes], srcs['libspatialite'] / 'src' / unit],
            'zlib-headers-' + Path(unit).stem, capture=True)
        zlib_headers.update(audit_zlib_headers(deps, zp / 'include'))
    includes += [lp / 'include', source / KERNEL]
    objects = []
    for index, rel in enumerate(SOURCES):
        obj = output / ('kernel-' + str(index) + '.o'); objects.append(obj)
        run([tools['g++']['path'], '-std=c++17', '-O2', '-fPIC', '-DSQLITE_HAS_CODEC', '-DRTTI_ENABLED',
             *['-I'+str(p) for p in includes], '-c', source / KERNEL / rel, '-o', obj], 'kernel-' + str(index), timeout=60)
    consumer = output / 'kernel-spatial-consumer'
    run([tools['g++']['path'], '-std=c++17', '-O2', '-DSQLITE_HAS_CODEC', *['-I'+str(p) for p in includes],
         HERE / 'KernelSpatialDatabase.cpp', *objects, '-Wl,--start-group', *libs, '-Wl,--end-group',
         '-Wl,--no-undefined', '-Wl,-Map='+str(output / 'kernel-link.map'), '-ldl', '-pthread', '-lm', '-o', consumer], 'kernel-consumer-link')
    result = run([consumer, output / 'owned-database.sqlite'], 'kernel-consumer', timeout=30, capture=True)
    if 'real_kernel_spatial_database_geometry_transform_typed_transaction_reopen=PASS\n' not in result:
        raise ValueError('real Kernel controls did not pass')
    run([tools['g++']['path'], '-shared', '-Wl,--whole-archive', *objects, *libs, '-Wl,--no-whole-archive',
         '-Wl,--no-undefined', '-ldl', '-pthread', '-lm', '-o', output / 'kernel-spatial-pic.so'], 'strict-pic-link')
    if 'TEXTREL' in run([tools['readelf']['path'], '-d', output / 'kernel-spatial-pic.so'], 'pic-relocations', capture=True):
        raise ValueError('TEXTREL in joined libraries')
    closure = run([tools['ldd']['path'], consumer], 'runtime-closure', capture=True)
    forbidden = ('spatialite','sqlite','geos','proj','crypto','ssl','xml2','iconv','charset','libz.so')
    if 'not found' in closure or any(word in closure.lower() for word in forbidden):
        raise ValueError('host third-party runtime fallback')
    runtime = {str(Path(word).resolve()):native.digest(Path(word)) for line in closure.splitlines()
               for word in line.split() if word.startswith('/') and Path(word).is_file()}
    if not runtime: raise ValueError('runtime identities unavailable')
    for name, inventory in inventories.items(): geos.check_sources(srcs[name].parent, inventory)
    if kernel_inventory(source) != kernel or recipe() != initial:
        raise ValueError('Kernel or recipe changed during integration')
    for name, path in roots.items():
        if dependency(path, name)['input_receipt_sha256'] != dependencies[name]['input_receipt_sha256']:
            raise ValueError('dependency receipt changed during integration')
    for tool in tools.values():
        if native.digest(Path(tool['path'])) != tool['sha256']:
            raise ValueError('integration build tool changed')
    selected_archives = {str(p):{'sha256':native.digest(p),'bytes':p.stat().st_size} for p in libs}
    record = {'schema_version':1,'profile':'kernel-legacy-spatial-database','recipe':initial,'lock':LOCK,
        'input_receipt_sha256':{n:r['input_receipt_sha256'] for n,r in dependencies.items()},
        'kernel':kernel,'kernel_sources':list(SOURCES),'dependency_roots':{k:str(v) for k,v in roots.items()},
        'tools':tools,'archive_members':archive_members,'selected_archives':selected_archives,'zlib_headers':zlib_headers,'source_inventories':inventories,'installed':{n:native.inventory(p) for n,p in prefixes.items()},
        'outputs':{p.name:{'sha256':native.digest(p),'bytes':p.stat().st_size} for p in (consumer, output / 'kernel-spatial-pic.so')},
        'runtime_closure':runtime,'real_kernel_spatial_database_controls':True,'strict_pic':True,
        'modern_db2_encrypted_api_acceptance':False,'full_sdk_acceptance':False,'jni_acceptance':False,
        'takx_acceptance':False,'target_abi_acceptance':False,'security_acceptance':False,'disk_bytes':disk_bound(output,cache)}
    (output / 'complete.json').write_text(json.dumps(record,indent=2)+'\n')
    print('Real legacy Kernel spatial database integration passed; full SDK/client remain unverified')


if __name__ == '__main__':
    main()
