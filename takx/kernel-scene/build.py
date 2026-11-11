#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded real KernelScene experiment; reduced GIS profile, not a complete SDK."""
import argparse
import importlib.util
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scene_native', HERE.parent / 'native-deps/build.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
spec = importlib.util.spec_from_file_location('scene_assimp', HERE.parent / 'native-assimp/build.py')
assimp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assimp)
spec = importlib.util.spec_from_file_location('scene_producer', HERE / 'producer.py')
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
CONFIGURE = [
    '--disable-shared', '--enable-static', '--with-threads=yes',
    '--with-libtiff=internal', '--with-geotiff=internal', '--with-jpeg=internal',
    '--with-png=internal', '--with-gif=internal', '--without-jpeg12', '--with-proj5-api=no',
    '--with-liblzma=no', '--with-zstd=no', '--with-pg=no', '--with-grass=no', '--with-libgrass=no',
    '--with-cfitsio=no', '--with-dds=no', '--with-gta=no', '--with-ogdi=no', '--with-fme=no',
    '--with-sosi=no', '--with-mongocxx=no', '--with-hdf4=no', '--with-hdf5=no', '--with-kea=no',
    '--with-netcdf=no', '--with-jasper=no', '--with-openjpeg=no', '--with-fgdb=no', '--with-ecw=no',
    '--with-kakadu=no', '--with-mrsid=no', '--with-jp2mrsid=no', '--with-mrsid_lidar=no', '--with-jp2lura=no',
    '--with-msg=no', '--with-oci=no', '--with-mysql=no', '--with-ingres=no', '--with-xerces=no',
    '--with-expat=no', '--with-libkml=no', '--with-odbc=no', '--with-dods-root=no', '--with-curl=no',
    '--with-xml2=no', '--with-spatialite=no', '--with-sqlite3=no', '--with-rasterlite2=no', '--with-pcre=no',
    '--with-teigha=no', '--with-idb=no', '--with-sde=no', '--with-epsilon=no', '--with-webp=no',
    '--with-geos=no', '--with-sfcgal=no', '--with-opencl=no', '--with-freexl=no',
    '--with-poppler=no', '--with-podofo=no', '--with-pdfium=no', '--with-perl=no', '--with-python=no',
    '--with-java=no', '--with-hdfs=no', '--with-mdb=no', '--with-rasdaman=no', '--with-armadillo=no',
    '--with-cryptopp=no', '--with-crypto=no', '--without-libiconv-prefix',
]
KERNEL_TUS = [
    'model/' + n + '.cpp' for n in ('ASSIMPSceneSpi', 'Scene', 'SceneNode', 'SceneBuilder',
        'SceneGraphBuilder', 'Mesh', 'MeshBuilder', 'Material', 'VertexDataLayout', 'ResourceMapper')
] + ['math/Matrix2.cpp', 'feature/Envelope2.cpp'] + [
    'port/' + n + '.cpp' for n in ('String', 'StringBuilder', 'Platform')
] + ['util/' + n + '.cpp' for n in ('Memory', 'MemBuffer2', 'DataInput2', 'DataOutput2', 'IO', 'IO2',
    'ZipFile', 'ProtocolHandler', 'ConfigOptions', 'Logging', 'Logging2', 'ProcessingCallback')
] + ['thread/' + n + '.cpp' for n in ('Mutex', 'Lock', 'RWMutex', 'impl/ThreadImpl_common', 'impl/ThreadImpl_libpthread')] + ['util/MemBuffer.cpp', 'thread/Monitor.cpp', 'thread/Cond.cpp']


def recipe():
    files = ('build.py', 'producer.py', 'kernel.py', 'resume.py', 'metadata.py', 'normalize_la.py', 'inputs.lock.json', 'KernelSceneProbe.cpp',
             'patches/gdal-disable-pdf.patch', 'patches/libkml-pgsc.patch',
             'patches/minizip-zlib-crc-type.patch', 'patches/gdal-libtool-normalizer.patch', 'MinizipProbe.c')
    return {name: native.digest(HERE / name) for name in files} | {
        '../native-deps/build.py': native.digest(HERE.parent / 'native-deps/build.py'),
        '../native-assimp/build.py': native.digest(HERE.parent / 'native-assimp/build.py'),
        '../native-las/build.py': native.digest(HERE.parent / 'native-las/build.py')}


def inventory(root):
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('source symlink refused')
    return {str(p.relative_to(root)): {'bytes': p.stat().st_size, 'sha256': native.digest(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}


def unpack(archive, root, entry):
    native.verified(archive, entry)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        names = set()
        regular = [m for m in members if m.isfile()]
        if (len(members), len(regular), sum(m.size for m in regular)) != (
                entry['members'], entry['regular_files'], entry['expanded_bytes']):
            raise ValueError('archive inventory differs')
        for m in members:
            name = str(native.relative(m.name))
            if name in names or not (m.isdir() or m.isfile()):
                raise ValueError('duplicate or nonregular archive member')
            names.add(name)
        root.mkdir()
        for m in regular:
            p = root / str(native.relative(m.name))
            p.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as source, p.open('xb') as target:
                shutil.copyfileobj(source, target)
            p.chmod(0o755 if m.mode & 0o111 else 0o644)
    return inventory(root)


def verify_dependency(root, family):
    if root.is_symlink():
        raise ValueError('dependency proof root symlink')
    root = root.resolve()
    receipt = root / 'complete.json'
    data = json.loads(receipt.read_text())
    if data.get('source_revision') != REVISION:
        raise ValueError('dependency source revision differs')
    folder = HERE.parent / ('native-proj' if family == 'proj' else 'native-assimp')
    for name, expected in data['recipe'].items():
        path = folder / name
        if path.is_symlink() or native.digest(path) != expected:
            raise ValueError('dependency recipe differs')
    if native.inventory(root / 'install') != data['installed']:
        raise ValueError('dependency installed inventory differs')
    if family == 'assimp':
        if (data.get('actual_core_version') != '4.1.0' or data.get('zlib_version') != '1.3.1' or
                data.get('valid_cpp_c_java_interop') is not True or data.get('strict_pic_links') is not True or
                native.inventory(root / 'zlib-install') != data['zlib_installed']):
            raise ValueError('Assimp/zlib proof differs')
        if native.digest(root / 'sources.json') != data['source_inventory_sha256']:
            raise ValueError('Assimp source inventory differs')
        if assimp.freeze_tree(root / 'source') != data['source_postimages']:
            raise ValueError('Assimp sources differ')
    else:
        if data.get('version') != '4.9.1' or data.get('known_coordinates_forward_inverse') is not True or data.get('strict_pic') is not True:
            raise ValueError('PROJ positive proof differs')
        if inventory(root / 'source') != data['source_inventory']:
            raise ValueError('PROJ sources differ')
    for tool in data['tools'].values():
        if native.digest(Path(tool['path'])) != tool['sha256']:
            raise ValueError('dependency tool differs')
    return native.digest(receipt)


def validate_output(output, inputs):
    output = native.external(output)
    if output.exists() or any(output == p.resolve() or output in p.resolve().parents or p.resolve() in output.parents for p in inputs):
        raise ValueError('fresh output separate from all inputs required')
    return output


def runtime_providers(text, library, core):
    expected = {library.resolve(), core.resolve()}
    found = {}
    system = re.compile(r'^(?:libc|libm|libpthread|libdl|librt|libstdc\+\+|libgcc_s)\.so(?:\..*)?$|^ld-linux-x86-64\.so\.2$')
    for line in text.splitlines():
        if not line.startswith('provider='):
            continue
        raw = line[len('provider='):]
        if raw == 'linux-vdso.so.1':
            continue
        path = Path(raw)
        if not path.is_absolute() or not path.is_file():
            raise ValueError('runtime provider unavailable')
        path = path.resolve()
        if path in found:
            raise ValueError('duplicate runtime provider')
        if path not in expected and not (path.parent == Path('/usr/lib/x86_64-linux-gnu') and system.fullmatch(path.name)):
            raise ValueError('foreign runtime provider')
        found[path] = native.digest(path)
    if not expected.issubset(found):
        raise ValueError('actual KernelScene/Assimp providers missing')
    return {str(path): sha for path, sha in found.items()}


def validate_kernel_input(relative, data):
    if relative == 'formats/wmm/EGM9615.h':
        if len(data) != 8416818 or hashlib.sha256(data).hexdigest() != 'cdea160e717847703dc17d7d2d7868499aa3aee22dc701537536fbf1f11bc834':
            raise ValueError('official EGM96 data header differs')
    elif len(data) > 2 * 1024**2:
        raise ValueError('Kernel source file exceeds bound')


def kernel_stage(args, output, run, lock, initial, deps, frozen, source_post, mz, zprefix, minizip, prefix, cxx, env, dependency_receipt, dependency_source_root=None):
    dependency_source_root = dependency_source_root or frozen
    def check_dependency_sources():
        for family in ('gdal', 'libkml'):
            expected = {k[len(family)+1:]:v for k,v in source_post.items() if k.startswith(family+'/')}
            if not expected or inventory(dependency_source_root / family) != expected:
                raise ValueError('dependency source postimages changed')
    check_dependency_sources()
    def source_git(*arguments):
        result = subprocess.check_output(['git', '--no-replace-objects', '--no-lazy-fetch', '-C', str(args.source), *arguments],
            env={**env, 'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_NO_LAZY_FETCH': '1'}, timeout=20)
        if len(result) > 16 * 1024**2:
            raise ValueError('Kernel Git evidence exceeds bound')
        return result
    if source_git('rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('Kernel source revision differs')
    tree_path = 'takkernel/engine/src/main/cpp'
    listing = source_git('ls-tree', '-r', '-z', REVISION, tree_path)
    kernel = frozen / 'kernel'
    kernel.mkdir()
    kernel_sources = {}
    for record in listing.rstrip(b'\0').split(b'\0'):
        meta, name = record.split(b'\t', 1)
        mode, kind, blob = meta.split()
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise ValueError('nonregular Kernel input')
        path = name.decode()
        relative = path[len(tree_path)+1:]
        target = kernel / str(native.relative(relative))
        data = source_git('cat-file', 'blob', blob.decode())
        validate_kernel_input(relative, data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        kernel_sources[relative] = {'git_blob': blob.decode(), 'sha256': native.digest(target), 'bytes': len(data)}
    (output / 'kernel-sources.json').write_text(json.dumps(kernel_sources, sort_keys=True) + '\n')
    objects = []
    objdir = output / 'kernel-objects'
    objdir.mkdir()
    includes = ['-I' + str(p) for p in (kernel, prefix / 'include', mz.parent, zprefix / 'include',
                args.assimp_proof.resolve() / 'install/include')]
    for tu in KERNEL_TUS:
        obj = objdir / (tu.replace('/', '_') + '.o')
        run([cxx, '-std=c++17', '-O1', '-fPIC', *includes, '-c', kernel / tu, '-o', obj],
            'kernel-' + tu.replace('/', '_'), 180)
        objects.append(obj)
    library = output / 'libkernel-scene-subset.so'
    core = args.assimp_proof.resolve() / 'install/lib/libassimp.so.4'
    libraries = [core, prefix / 'lib/libgdal.a', minizip, zprefix / 'lib/libz.a',
                 args.proj_proof.resolve() / 'install/lib/libproj.a']
    run([cxx, '-shared', '-Wl,--no-undefined', *objects, *libraries, '-pthread', '-ldl', '-lm',
         '-Wl,-rpath,' + str(core.parent), '-o', library], 'kernel-strict-link', 180)
    probe = output / 'kernel-scene-probe'
    run([cxx, '-std=c++17', '-O1', *includes, HERE / 'KernelSceneProbe.cpp', library,
         '-Wl,-rpath,' + str(output), '-o', probe], 'kernel-probe-link')
    fixture = args.assimp_proof.resolve() / 'valid/roundtrip.assbin'
    receipt = json.loads((args.assimp_proof / 'complete.json').read_text())
    if native.digest(fixture) != receipt['probe_outputs']['valid/roundtrip.assbin']['sha256']:
        raise ValueError('Assimp fixture differs')
    text = run([probe, fixture, output / 'missing.assbin'], 'kernel-positive-scene', 15, True)
    if text.decode().splitlines().count('actual_kernel_assimp_scene_geometry_material_uv_bounds_bad_uri=true') != 1:
        raise ValueError('KernelScene positive proof incomplete')
    providers = runtime_providers(text.decode(), library, core)
    for family, root in [('proj', args.proj_proof), ('assimp', args.assimp_proof)]:
        if verify_dependency(root, family) != deps[family]:
            raise ValueError('dependency changed during integration')
    check_dependency_sources()
    if recipe() != initial:
        raise ValueError('recipe changed')
    (output / 'complete.json').write_text(json.dumps({'profile': lock['profile'], 'recipe': initial,
        'dependencies': deps, 'source_revision': REVISION, 'kernel_source_inventory_sha256': native.digest(output / 'kernel-sources.json'),
        'outputs': native.inventory(output / 'kernel-objects'), 'library_sha256': native.digest(library),
        'runtime_providers': providers, 'dependency_receipt_sha256': native.digest(dependency_receipt),
        'probe_sha256': native.digest(probe), 'fixture_sha256': native.digest(fixture),
        'actual_kernel_scene_positive_control': True, 'full_kernel_sdk_acceptance': False,
        'jni_acceptance': False, 'renderer_acceptance': False, 'takx_acceptance': False}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'source', 'gdal_archive', 'libkml_archive', 'proj_proof', 'assimp_proof'):
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.source, args.gdal_archive, args.libkml_archive, args.proj_proof, args.assimp_proof, HERE]
    output = validate_output(args.output, inputs)
    output.mkdir()
    initial = recipe()
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    if (lock['revision'] != REVISION or lock['gdal']['sha256'] != 'a170207c0548cadec57e3a6e57727f66d4b64bf4a9a3ddd6c6bd0bf2479260e2' or
            lock['libkml']['sha256'] != '39692c0184933424e35ef69e5101f1ff0d664f2b50b972887cfc15fda032d1cb' or
            lock['jobs'] != 1 or lock['stage_seconds'] != 1200 or lock['gdal_stage_seconds'] != 2400 or lock['output_bytes'] != 4 * 1024**3 or
            lock['configure'] != CONFIGURE or lock['kernel_tus'] != KERNEL_TUS):
        raise ValueError('unreviewed profile')
    deps = {family: verify_dependency(root, family) for family, root in (
        ('proj', args.proj_proof), ('assimp', args.assimp_proof))}
    cc, cxx = Path('/usr/bin/gcc').resolve(), Path('/usr/bin/g++').resolve()
    tools = {'cc': {'path': str(cc), 'sha256': native.digest(cc)}, 'cxx': {'path': str(cxx), 'sha256': native.digest(cxx)}}
    env = assimp.environment(str(cc), str(cxx))
    for key in list(env):
        if key.startswith(('PROJ_', 'GDAL_', 'PKG_CONFIG', 'BASH_FUNC_')) or key in (
            'MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS', 'MAKEFILES', 'CONFIG_SITE', 'CONFIG_SHELL',
            'CPATH', 'LIBRARY_PATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH'):
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC', CXXFLAGS='-O2 -fPIC', CONFIG_SITE='/dev/null',
               PKG_CONFIG_LIBDIR=str(output / 'no-pkgconfig'), PKG_CONFIG_PATH='',
               CC=str(cc), CXX=str(cxx))
    stage, deadline, commands = 'prepare', time.monotonic() + 1200, []

    def run(command, name, timeout=60, capture=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('stage deadline exceeded')
        commands.append({'stage': stage, 'name': name, 'command': list(map(str, command))})
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        result = native.run(list(map(str, command)), output, name, min(timeout, remaining), env, capture)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink()) > lock['output_bytes']:
            raise ValueError('4 GiB output bound exceeded')
        return result

    try:
        for name, command, expected in [('cc', cc, '14.2.0'), ('cxx', cxx, '14.2.0'), ('make', '/usr/bin/make', '4.4.1')]:
            text = run([command, '--version'], 'tool-' + name, capture=True).decode().splitlines()[0]
            if expected not in text:
                raise ValueError('unsupported toolchain')
            tools[name] = {'path': str(Path(command).resolve()), 'sha256': native.digest(Path(command).resolve())}
        frozen = output / 'source'
        frozen.mkdir()
        gdal_before = unpack(args.gdal_archive, frozen / 'gdal', lock['gdal'])
        kml_before = unpack(args.libkml_archive, frozen / 'libkml', lock['libkml'])
        src = frozen / 'gdal/gdal'
        if native.digest(src / 'LICENSE.TXT') != lock['licenses']['gdal']:
            raise ValueError('GDAL license differs')
        kml = frozen / 'libkml/libkml-1.3'
        if native.digest(kml / 'COPYING') != lock['licenses']['libkml']:
            raise ValueError('libkml license differs')
        for name, expected in lock['libkml_patch_preimages'].items():
            path = kml / name
            if (None if not path.exists() else {'bytes': path.stat().st_size, 'sha256': native.digest(path)}) != expected:
                raise ValueError('official patch preimage differs')
        # Apply the full official patch and the single explicit profile patch.
        for family, root, patchname, level in [('gdal', src, 'gdal-disable-pdf.patch', '1'), ('libkml', kml, 'libkml-pgsc.patch', '0')]:
            patch = HERE / 'patches' / patchname
            if native.digest(patch) != lock['patches'][patchname]['sha256']:
                raise ValueError('patch differs')
            run(['/usr/bin/patch', '--batch', '--fuzz=0', '-p' + level, '-d', root, '-i', patch], 'patch-' + family)
        source_post = inventory(frozen)
        changed = {name: val for name, val in inventory(kml).items() if
                   kml_before.get('libkml-1.3/' + name) != val}
        if changed != lock['libkml_patch_postimages'] or native.digest(src / 'GDALmake.opt.in') != lock['patches']['gdal-disable-pdf.patch']['after']:
            raise ValueError('patch postimages differ')
        crc_patch = HERE / 'patches/minizip-zlib-crc-type.patch'
        crc_entry = lock['patches'][crc_patch.name]
        mz = kml / 'third_party/zlib-1.2.3/contrib/minizip'
        if native.digest(crc_patch) != crc_entry['sha256']:
            raise ValueError('CRC type patch differs')
        for name, image in crc_entry['images'].items():
            if native.digest(mz / name) != image['before_sha256']:
                raise ValueError('CRC type preimage differs')
        run(['/usr/bin/patch', '--batch', '--fuzz=0', '-p1', '-d', mz, '-i', crc_patch], 'patch-minizip-crc-type')
        for name, image in crc_entry['images'].items():
            if native.digest(mz / name) != image['after_sha256']:
                raise ValueError('CRC type postimage differs')
        normalizer_patch = HERE / 'patches/gdal-libtool-normalizer.patch'
        normalizer_entry = lock['patches'][normalizer_patch.name]
        if (native.digest(src / 'GNUmakefile') != normalizer_entry['before_sha256'] or
                native.digest(normalizer_patch) != normalizer_entry['sha256'] or
                native.digest(HERE / 'normalize_la.py') != lock['normalizer_sha256']):
            raise ValueError('libtool normalizer input differs')
        run(['/usr/bin/patch', '--batch', '--fuzz=0', '-p1', '-d', src, '-i', normalizer_patch], 'patch-gdal-normalizer')
        if native.digest(src / 'GNUmakefile') != normalizer_entry['after_sha256']:
            raise ValueError('libtool normalizer postimage differs')
        env.update(KERNEL_SCENE_PYTHON='/usr/bin/python3', KERNEL_SCENE_NORMALIZER=str(HERE / 'normalize_la.py'))
        source_post = inventory(frozen)
        (output / 'sources.json').write_text(json.dumps(source_post, sort_keys=True) + '\n')
        stage, deadline = 'minizip', time.monotonic() + 1200
        mz = kml / 'third_party/zlib-1.2.3/contrib/minizip'
        zprefix = args.assimp_proof.resolve() / 'zlib-install'
        mzbuild = output / 'minizip'
        mzbuild.mkdir()
        objects = []
        for name in ('unzip', 'ioapi', 'iomem_simple', 'zip'):
            obj = mzbuild / (name + '.o')
            run([cc, '-O2', '-fPIC', '-I' + str(zprefix / 'include'), '-I' + str(mz), '-c', mz / (name + '.c'), '-o', obj], 'minizip-' + name)
            objects.append(obj)
        minizip = mzbuild / 'libminizip.a'
        run(['/usr/bin/ar', 'rcs', minizip, *objects], 'minizip-archive')
        run([cc, '-shared', '-Wl,--no-undefined', '-Wl,--whole-archive', minizip, '-Wl,--no-whole-archive', zprefix / 'lib/libz.a', '-o', mzbuild / 'libminizip-pic.so'], 'minizip-strict-link')
        zip_probe = mzbuild / 'minizip-probe'
        run([cc, '-std=c11', '-O1', '-I' + str(zprefix / 'include'), '-I' + str(mz),
             HERE / 'MinizipProbe.c', minizip, zprefix / 'lib/libz.a', '-o', zip_probe], 'minizip-probe-link')
        text = run([zip_probe, mzbuild], 'minizip-positive-controls', 10, True)
        if text != b'real_minizip_binary_crc_correct_and_wrong_password_controls=true\n':
            raise ValueError('minizip real controls incomplete')
        stage, deadline = 'gdal', time.monotonic() + 2400
        build = output / 'gdal-build'
        shutil.copytree(src, build)
        prefix = output / 'gdal-install'
        config = [str(build / 'configure'), '--prefix=' + str(prefix), '--with-proj=' + str(args.proj_proof.resolve() / 'install'), '--with-libz=' + str(zprefix), *CONFIGURE]
        (output / 'configuration.json').write_text(json.dumps({'args': config, 'kernel_tus': KERNEL_TUS, 'recipe': initial, 'dependencies': deps}, indent=2) + '\n')
        run(['/usr/bin/make', '--version'], 'gdal-make-version')
        # configure generates files relative to its cwd.
        run(['/workspace/takx-native-tools/venv/bin/cmake', '-E', 'chdir', build, *config], 'gdal-configure', 180)
        configure_log = (output / 'gdal-configure.log').read_text()
        if 'unrecognized options' in configure_log:
            raise ValueError('unsupported configure options')
        actual_summary = {}
        for line in configure_log.splitlines():
            match = re.match(r'^  ([^:]+):\s*(.*?)\s*$', line)
            if match and match[1] in lock['configure_summary']:
                actual_summary[match[1]] = match[2]
        if actual_summary != lock['configure_summary']:
            raise ValueError('GDAL external feature summary differs')
        opts = (build / 'GDALmake.opt').read_text()
        if 'GDAL_FORMATS := $(GDAL_FORMATS) pdf' in opts or not re.search(r'^PROJ_STATIC\s*=\s*yes$', opts, re.M) or '-DPROJ_VERSION=4' not in opts:
            raise ValueError('reduced format or static PROJ configuration differs')
        run(['/usr/bin/make', '-C', build, '-j1', 'lib-target'], 'gdal-build', 2400)
        (prefix / 'lib').mkdir(parents=True, exist_ok=True)
        run(['/usr/bin/make', '-C', build, '-j1', 'install-static-lib'], 'gdal-install', 180)
        # Shared normative receipt; no Kernel acceptance follows from dependency build alone.
        producer_tools = {item['path']: item['sha256'] for item in tools.values()}
        for proof in (args.proj_proof, args.assimp_proof):
            producer_tools.update({item['path']:item['sha256'] for item in
                json.loads((proof/'complete.json').read_text())['tools'].values()})
        producer_tools[str(Path('/usr/bin/python3').resolve())] = native.digest(Path('/usr/bin/python3').resolve())
        producer.emit(output, output, initial, source_post, producer_tools, None, True)
        stage, deadline = 'kernel-scene', time.monotonic() + 1200
        kernel_stage(args, output, run, lock, initial, deps, frozen, source_post, mz, zprefix, minizip, prefix, cxx, env, output / 'dependencies-built.json')
    except Exception:
        (output / 'failed.json').write_text(json.dumps({'stage': stage, 'last_command': commands[-1]['name'] if commands else None,
            'kernel_scene_acceptance': False, 'recipe': initial}, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
