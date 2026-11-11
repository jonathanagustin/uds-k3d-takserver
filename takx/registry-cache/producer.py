#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Fresh Draco build in one pinned, network-isolated container; no publication."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request
import uuid
import draco as local
import fresh
import qualify

HERE = Path(__file__).resolve().parent
LOCK = local.load(HERE / 'producer.lock.json')
PATH = '/usr/local/bin:/usr/bin:/bin'
DEADLINE = time.monotonic() + 700
MAX_OUTPUT = 1024**3
RECIPE = ('producer.py', 'fresh.py', 'draco.py', 'qualify.py', 'producer.lock.json', 'DracoCacheProbe.cpp')


def quota(root):
    size = 0
    for p in root.rglob('*'):
        try:
            s = p.lstat()
        except FileNotFoundError:
            continue
        if p.is_file() and not p.is_symlink():
            size += s.st_size
    if size > MAX_OUTPUT:
        raise ValueError('owned output exceeds1GiB')


def run(command, root, name, timeout=60, env=None):
    log = root / (name + '.log')
    deadline = min(DEADLINE, time.monotonic() + timeout)
    child = None
    try:
        with log.open('xb') as stream:
            child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True, env=env)
            while True:
                quota(root)
                if log.stat().st_size > 16 * 1024**2 or time.monotonic() >= deadline:
                    raise ValueError('command exceeded time/log bound; inspect private local log')
                if child.poll() is not None:
                    break
                time.sleep(0.2)
            if child.returncode:
                raise ValueError('command failed; inspect private local log')
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
    return log.read_bytes()


def source(root):
    if root.is_symlink() or not root.is_dir(): raise ValueError('ordinary source root required')
    records, total = [], 0
    def tree(directory):
        nonlocal total
        body = b''
        for p in sorted(directory.iterdir(), key=lambda p: p.name.encode() + (b'/' if p.is_dir() else b'')):
            if p.is_symlink():
                raise ValueError('source symlink refused')
            if p.is_dir():
                mode, h = b'40000', tree(p)
            elif p.is_file():
                if p.stat().st_size > 8 * 1024**2 or total + p.stat().st_size > LOCK['source']['bytes']:
                    raise ValueError('source file exceeds pinned acquisition bound')
                data = p.read_bytes()
                total += len(data)
                if total > LOCK['source']['bytes'] or len(records) >= LOCK['source']['files']:
                    raise ValueError('source exceeds pinned quota')
                mode = b'100755' if p.stat().st_mode & 0o111 else b'100644'
                h = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                records.append({'path': str(p.relative_to(root)), 'mode': mode.decode(), 'git_blob': h,
                                'bytes': len(data), 'sha256': local.sha(data)})
            else:
                raise ValueError('nonregular source input')
            body += mode + b' ' + p.name.encode() + b'\0' + bytes.fromhex(h)
        return hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    if tree(root) != LOCK['source']['tree'] or total != LOCK['source']['bytes'] or len(records) != LOCK['source']['files']:
        raise ValueError('source Git tree differs from official pin')
    return records


def tools(root):
    compiler = shutil.which('gcc-14') or shutil.which('gcc')
    cxx = shutil.which('g++-14') or shutil.which('g++')
    paths = {'gcc': compiler, 'g++': cxx, 'make': 'make', 'cmake': '/tools/bin/cmake',
             'python3': 'python3', 'readelf': 'readelf'}
    for name in ('cc1', 'cc1plus', 'as', 'ld', 'ar', 'ranlib'):
        paths[name] = run([cxx, '-print-prog-name=' + name], root, 'locate-' + name).decode().strip()
    result = {}
    for name, path in paths.items():
        path = Path(shutil.which(path) or path).resolve()
        result[name] = {'path': str(path), 'sha256': local.file_sha(path),
                        'version': run([str(path), '--version'], root, 'tool-' + name).decode().strip()}
    if (not result['g++']['version'].splitlines()[0].endswith(' 14.2.0') or
            result['cmake']['version'].splitlines()[0] != 'cmake version ' + LOCK['cmake']['version']):
        raise ValueError('unsupported compiler')
    return result


def providers(binary, root, name):
    data = run(['ldd', str(binary)], root, name).decode()
    paths = sorted(set(re.findall(r'(/[A-Za-z0-9_./+\-]+)', data)))
    if not paths:
        raise ValueError('runtime closure not observed')
    return {str(Path(p).resolve()): local.file_sha(Path(p).resolve()) for p in paths}


def abi(t, root):
    data = run([t['g++']['path'], '-std=gnu++11', '-dM', '-E', '-x', 'c++',
                '-include', 'bits/c++config.h', '-include', 'features.h', '/dev/null'], root, 'abi-macros').decode()
    macros = dict(re.findall(r'^#define (\w+) (.+)$', data, re.M))
    runtime = {}
    for i, name in enumerate(('gcc', 'g++', 'cc1', 'cc1plus', 'ld', 'ar', 'ranlib', 'make', 'cmake', 'python3')):
        runtime.update(providers(t[name]['path'], root, 'providers-tool-' + str(i)))
    return {'target': run([t['g++']['path'], '-dumpmachine'], root, 'target').decode().strip(),
            'pointer_bytes': macros['__SIZEOF_POINTER__'], 'byte_order': macros['__BYTE_ORDER__'],
            'cxx11_abi': macros['_GLIBCXX_USE_CXX11_ABI'], 'exceptions': macros['__EXCEPTIONS'],
            'rtti': macros['__GXX_RTTI'], 'cxx_standard': macros['__cplusplus'],
            'glibc': macros['__GLIBC__'] + '.' + macros['__GLIBC_MINOR__'], 'providers': runtime}


def archive_objects(path):
    if path.stat().st_size > 32 * 1024**2: raise ValueError('archive exceeds profile')
    data = path.read_bytes()
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('not a real static archive')
    position, names, result = 8, b'', []
    while position < len(data):
        header = data[position:position+60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('invalid ar entry')
        name, size = header[:16].strip().decode(), int(header[48:58])
        if size < 0: raise ValueError('negative ar member size')
        body = data[position+60:position+60+size]
        if len(body) != size:
            raise ValueError('short ar entry')
        position += 60 + size + size % 2
        if name == '//':
            names = body
        elif name not in ('/', '/SYM64/'):
            if name.startswith('/'):
                name = names[int(name[1:]):].split(b'/\n',1)[0].decode()
            else:
                name = name.rstrip('/')
            if not body.startswith(b'\x7fELF'):
                raise ValueError('archive member is not an ELF object')
            result.append({'name': name, 'sha256': local.sha(body), 'bytes': len(body)})
    if not result or len(result) > 300:
        raise ValueError('archive closure exceeds profile')
    return result


def observed(binary, root, name):
    data = run([str(binary)], root, name, env=dict(os.environ, LD_DEBUG='libs,files'))
    paths = sorted(set(Path(os.fsdecode(p.strip())).resolve() for p in re.findall(rb'calling init: ([^\n]+)', data)))
    allowed = ('ld-linux-x86-64.so.2', 'libc.so.6', 'libm.so.6', 'libstdc++.so.6', 'libgcc_s.so.1')
    if len(paths) != 5 or any(not any(p.name.startswith(n) for n in allowed) for p in paths):
        raise ValueError('unexpected actual initialized provider closure')
    return data, {str(p): local.file_sha(p) for p in paths}


def consumer(capsule, sha, input_key, root, t):
    src = root / 'consumer-source'
    src.mkdir()
    shutil.copyfile(HERE / 'DracoCacheProbe.cpp', src / 'DracoSourceProbe.cpp')
    (src / 'CMakeLists.txt').write_text(qualify.CMAKE)
    (src / 'anchor.cpp').write_text('extern "C" int draco_pic_probe_anchor() { return 1; }\n')
    results = []
    for i, name in enumerate(('first', 'unrelated/deeper/second')):
        restored, build = root / name, root / ('consumer-build-' + str(i))
        manifest = fresh.restore(capsule, sha, input_key, restored)
        prefix = restored / 'prefix'
        run([t['cmake']['path'], '-S', str(src), '-B', str(build), '-G', 'Unix Makefiles',
             '-DCMAKE_MAKE_PROGRAM=' + t['make']['path'], '-DCMAKE_CXX_COMPILER=' + t['g++']['path'],
             '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
             '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF', '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF',
             '-DDRACO_PREFIX=' + str(prefix)], root, 'consumer-configure-' + str(i))
        run([t['cmake']['path'], '--build', str(build), '--parallel', '1'], root, 'consumer-build-' + str(i), 120)
        data, runtime = observed(build / 'consumer', root, 'consumer-codec-' + str(i))
        if b'draco_cache_codec=pass;encode=true;' not in data:
            raise ValueError('missing actual codec control')
        dynamic = run([t['readelf']['path'], '-d', str(build / 'libpiccheck.so')], root, 'consumer-pic-' + str(i))
        if b'TEXTREL' in dynamic:
            raise ValueError('PIC link has text relocations')
        for path, value in manifest['files'].items():
            if local.file_sha(restored / path) != value['sha256']:
                raise ValueError('restored payload changed')
        results.append({'codec': True, 'pic': True, 'prefix': name + '/prefix', 'runtime': runtime})
    return results


def recipes():
    values = {name: local.file_sha(HERE / name) for name in RECIPE}
    values['native-helper'] = local.file_sha(local.ROOT / 'takx/native-deps/build.py')
    values['native-fixture-probe'] = local.file_sha(local.ROOT / 'takx/native-deps/DracoSourceProbe.cpp')
    return values


def inside(root, restore_capsule=None):
    if platform.machine() != 'x86_64':
        raise ValueError('only Linux amd64 profile exists')
    root.mkdir(exist_ok=True)
    recipe = recipes()
    t = tools(root)
    actual_abi = abi(t, root)
    if restore_capsule:
        receipt = local.load(Path('/inputs/registry-receipt.json'))
        manifest, _ = fresh.verify(restore_capsule, receipt['capsule_sha256'], receipt['input_key'])
        if actual_abi != manifest['identity']['abi'] or t != manifest['identity']['tools'] or recipe != manifest['identity']['recipes']:
            raise ValueError('consumer tool/ABI differs from actual producer')
        results = consumer(restore_capsule, receipt['capsule_sha256'], receipt['input_key'], root, t)
        (root / 'restored.json').write_bytes(local.canonical({'schema': 'uds-draco-registry-consumer-v2',
            'results': results, 'input_key': receipt['input_key'], 'capsule_sha256': receipt['capsule_sha256'],
            'identity_sha256': local.sha(local.canonical(manifest['identity']))}))
        return
    source_root = Path('/inputs/draco')
    sources = source(source_root)
    build, prefix = root / 'work', root / 'prefix'
    configure = [t['cmake']['path'], '-S', str(source_root), '-B', str(build), '-G', 'Unix Makefiles',
                 '-DCMAKE_C_COMPILER=' + t['gcc']['path'], '-DCMAKE_CXX_COMPILER=' + t['g++']['path'],
                 '-DCMAKE_MAKE_PROGRAM=' + t['make']['path'], '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_INSTALL_PREFIX=' + str(prefix),
                 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_CXX_FLAGS=-march=x86-64 -mtune=generic',
                 '-DDRACO_TESTS=OFF', '-DDRACO_TRANSCODER_SUPPORTED=OFF']
    run(configure, root, 'configure')
    commands = local.load(build / 'compile_commands.json')
    identity = {'schema': 'uds-draco-inputs-v2', 'base_image': LOCK['image'], 'base_image_config': LOCK['image_config'], 'source': LOCK['source'],
                'source_inventory_sha256': local.sha(local.canonical(sources)), 'patches': [], 'dependency_digests': [],
                'recipes': recipe, 'tools': t, 'abi': actual_abi, 'configure_command': configure,
                'compile_commands': commands, 'environment': {'PATH': PATH, 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC',
                                                              'SOURCE_DATE_EPOCH': os.environ['SOURCE_DATE_EPOCH']}}
    fresh.key(identity)
    run([t['cmake']['path'], '--build', str(build), '--parallel', '1'], root, 'compile', 600)
    run([t['cmake']['path'], '--install', str(build)], root, 'install')
    licenses = prefix / 'licenses/draco'
    licenses.mkdir(parents=True)
    shutil.copyfile(source_root / 'LICENSE', licenses / 'LICENSE')
    run([str(prefix / 'bin/draco_encoder'), '-i', str(source_root / 'testdata/cube_att.obj'),
         '-o', str(root / 'cube.drc')], root, 'encode')
    run([str(prefix / 'bin/draco_decoder'), '-i', str(root / 'cube.drc'), '-o', str(root / 'cube.obj')], root, 'decode')
    probe = local.ROOT / 'takx/native-deps/DracoSourceProbe.cpp'
    run([t['g++']['path'], '-std=c++17', '-UNDEBUG', '-I' + str(prefix / 'include'), str(probe),
         str(prefix / 'lib/libdraco.a'), '-o', str(root / 'codec')], root, 'fixture-compile')
    if b'draco_source_codec_consumer=pass;' not in run([str(root / 'codec'), str(root / 'cube.drc')], root, 'fixture-codec'):
        raise ValueError('fixture codec failed')
    objects = archive_objects(prefix / 'lib/libdraco.a')
    built = Counter(local.file_sha(p) for p in build.rglob('*.o'))
    if Counter(o['sha256'] for o in objects) - built:
        raise ValueError('archive objects differ from actual compiled objects')
    run([t['g++']['path'], '-shared', '-Wl,--no-undefined', '-Wl,--whole-archive', str(prefix / 'lib/libdraco.a'),
         '-Wl,--no-whole-archive', '-o', str(root / 'pic.so')], root, 'pic-link')
    if b'TEXTREL' in run([t['readelf']['path'], '-d', str(root / 'pic.so')], root, 'pic-dynamic'):
        raise ValueError('source archive is not PIC')
    q = {'fresh_source_build': True, 'codec': True, 'pic': True, 'object_count': len(objects),
         'archive_object_sha256': local.sha(local.canonical(objects)), 'runtime_providers': providers(root / 'codec', root, 'codec-providers')}
    capsule = root / 'draco.tar.gz'
    fresh.pack(prefix, identity, q, capsule)
    sha, input_key = local.file_sha(capsule), fresh.key(identity)
    results = consumer(capsule, sha, input_key, root, t)
    if any(r['runtime'] != q['runtime_providers'] for r in results):
        raise ValueError('actual initialized runtime differs from source consumer closure')
    if source(source_root) != sources or recipe != recipes():
        raise ValueError('consumed recipe/source changed')
    if any(local.file_sha(Path(value['path'])) != value['sha256'] for value in t.values()):
        raise ValueError('build tool changed')
    for path, h in actual_abi['providers'].items():
        if local.file_sha(Path(path)) != h:
            raise ValueError('tool provider changed')
    (root / 'registry-receipt.json').write_bytes(local.canonical({'schema': 'uds-draco-fresh-result-v2',
        'capsule_sha256': sha, 'input_key': input_key, 'identity': identity, 'qualification': q,
        'relocated_consumers': results, 'registry_pull_ran': False, 'publisher_authenticated': False}))


def docker_env():
    return {k: v for k, v in os.environ.items() if k not in
            {'DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'}}


def docker(root, args, name, timeout=60):
    return run(['docker','--host=unix:///var/run/docker.sock', *args], root, name, timeout, docker_env())


def storage_guard(root, name):
    driver = docker(root, ['info','--format','{{.Driver}}'], name).decode().strip()
    free = shutil.disk_usage(root).free
    if driver == 'vfs' and free < 12 * 1024**3:
        raise ValueError('pinned eight-layer builder needs12GiB free with Docker vfs; no pull attempted')
    if free < 3 * 1024**3:
        raise ValueError('builder requires3GiB free before image acquisition')


def acquire_tools(cache):
    if cache.is_symlink(): raise ValueError('ordinary cache required')
    cache.mkdir(parents=True, exist_ok=True)
    package = cache / 'cmake.tar.gz'
    entry = LOCK['cmake']
    if not package.exists():
        with urllib.request.urlopen(entry['url'], timeout=30) as response, package.open('xb') as stream:
            total, deadline = 0, time.monotonic() + 120
            while block := response.read(65536):
                total += len(block)
                if total > entry['bytes'] or time.monotonic() > deadline:
                    raise ValueError('CMake acquisition exceeded bound')
                stream.write(block)
    if package.stat().st_size != entry['bytes'] or local.file_sha(package) != entry['sha256']:
        raise ValueError('CMake archive differs from official pin')
    cmake = cache / 'cmake'
    if cmake.is_symlink(): raise ValueError('CMake prefix symlink refused')
    existing = cmake.exists()
    if not existing: cmake.mkdir()
    total, entries, seen = 0, 0, set()
    with tarfile.open(package, 'r:gz') as archive:
        for item in archive:
            parts = local.safe(item.name.rstrip('/') if item.isdir() else item.name).split('/')
            if parts[0] != 'cmake-3.31.6-linux-x86_64': raise ValueError('unexpected CMake archive root')
            parts = parts[1:]
            if not parts: continue
            if not item.isfile() and not item.isdir(): raise ValueError('CMake archive link refused')
            name = '/'.join(parts)
            if name in seen: raise ValueError('duplicate CMake archive path')
            seen.add(name)
            target = cmake.joinpath(*parts)
            total, entries = total + item.size, entries + 1
            if total > 512 * 1024**2 or entries > 15000: raise ValueError('CMake expansion exceeds bound')
            if item.isdir():
                if target.is_symlink(): raise ValueError('CMake directory symlink refused')
                target.mkdir(parents=True, exist_ok=True)
            else:
                data = archive.extractfile(item).read(item.size + 1)
                if len(data) != item.size: raise ValueError('short CMake archive file')
                if existing:
                    local.regular(target, cmake)
                    if local.file_sha(target) != local.sha(data) or target.stat().st_mode & 0o777 != item.mode & 0o777:
                        raise ValueError('extracted CMake differs from pinned archive')
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream: stream.write(data)
                    target.chmod(item.mode & 0o777)
    for target in cmake.rglob('*'):
        if target.is_symlink() or str(target.relative_to(cmake)) not in seen:
            raise ValueError('unapproved extracted CMake entry')
    return cmake


def prepare(source_git, output, cache):
    if output.exists() or output.is_symlink() or cache.is_symlink():
        raise ValueError('new output and ordinary cache required')
    output.mkdir(parents=True)
    storage_guard(output, 'docker-driver')
    cmake = acquire_tools(cache)
    native = local.native()
    source_lock = local.load(local.ROOT / 'takx/native-deps/inputs.lock.json')
    native.freeze(source_git, output, source_lock)
    source(output / 'source/draco')
    return cmake


def launch(output, tools, input_root, mode='inside'):
    output.mkdir(parents=True, exist_ok=True)
    storage_guard(output, 'launch-driver')
    name = 'uds-draco-' + uuid.uuid4().hex
    args = ['run','--rm','--name',name,'--network','none','--read-only','--user',f'{os.getuid()}:{os.getgid()}',
            '--tmpfs','/tmp:rw,size=256m,mode=1777','--mount',f'type=bind,src={local.ROOT},dst=/recipe,readonly',
            '--mount',f'type=bind,src={tools.resolve()},dst=/tools,readonly',
            '--mount',f'type=bind,src={input_root.resolve()},dst=/inputs,readonly',
            '--mount',f'type=bind,src={output.resolve()},dst=/build','--entrypoint','/usr/bin/env',LOCK['image'],
            '-i','PATH='+PATH,'LANG=C','LC_ALL=C','TZ=UTC','SOURCE_DATE_EPOCH=1704067200',
            'python3','-B','/recipe/takx/registry-cache/producer.py',mode,'--output','/build']
    try:
        docker(output, args, 'container', 300 if mode == 'consume-inside' else 660)
    finally:
        try: docker(output, ['rm','-f',name], 'container-cleanup',15)
        except ValueError: pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    p = parser.add_subparsers(dest='command', required=True)
    a = p.add_parser('build')
    a.add_argument('--source', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    a.add_argument('--cache', type=Path, required=True)
    for name in ('inside', 'consume-inside'):
        a = p.add_parser(name); a.add_argument('--output', type=Path, required=True)
    a = p.add_parser('tools'); a.add_argument('--cache', type=Path, required=True)
    a = p.add_parser('consume')
    a.add_argument('--input', type=Path, required=True); a.add_argument('--output', type=Path, required=True)
    a.add_argument('--tools', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build':
        cmake = prepare(args.source, args.output, args.cache)
        docker(args.output, ['pull','--quiet',LOCK['image']], 'image-pull',300)
        image = json.loads(docker(args.output, ['image','inspect',LOCK['image']], 'image-inspect'))[0]
        if image['Id'] != LOCK['image_config'] or image['Size'] > 2 * 1024**3:
            raise ValueError('builder image identity/size differs')
        inputs = args.output / 'inputs'; inputs.mkdir()
        shutil.move(str(args.output / 'source/draco'), inputs / 'draco')
        launch(args.output / 'build', cmake, inputs)
    elif args.command == 'tools': print(acquire_tools(args.cache))
    elif args.command == 'inside': inside(args.output)
    elif args.command == 'consume-inside': inside(args.output, Path('/inputs/draco.tar.gz'))
    else:
        if args.output.exists(): raise ValueError('new consumer output required')
        args.output.mkdir(parents=True); launch(args.output, args.tools, args.input, 'consume-inside')


if __name__ == '__main__':
    main()
