#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in host Linux SQLite JDBC build; only locked sources and one public API JAR."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import signal
import stat
import subprocess
import tempfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
PATCH = HERE / 'patches/gcc14-extension-prototype.patch'
ORIGINAL_MAKE = '8586d14c772a965bfb6cb602451c7866555acb0d1896ecc73854b314d9a95a66'
PATCHED_MAKE = '73330300da1dc8182e38b4f2cf8616322989f9a6abee20d35b31ed6b6fad03ec'
PATCH_SHA = '17153567cd170e6f7e1fca78e2954754f0c731428f7edf9934709d0d70d3c784'
ARTIFACTS = ('sqlite-jdbc-host-source.jar', 'native/libsqlitejdbc.so', 'slf4j-api.jar')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in name:
        raise ValueError(f'Unsafe input path: {name}')
    return path


def checked(data, entry):
    if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError(f'Input checksum mismatch: {entry["path"]}')
    if 'gitBlob' in entry:
        blob = b'blob ' + str(len(data)).encode() + b'\0' + data
        if hashlib.sha1(blob).hexdigest() != entry['gitBlob']:
            raise ValueError('Git blob identity mismatch')
    for kind, expected in entry.get('upstreamDigest', {}).items():
        if hashlib.new(kind, data).hexdigest() != expected:
            raise ValueError('Upstream digest mismatch')


def check_archive(path):
    with zipfile.ZipFile(path) as archive:
        total = 0
        for entry in archive.infolist():
            name = relative(entry.filename)
            if name.parts[0] != 'sqlite-src-3540100' or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unexpected SQLite archive member')
            total += entry.file_size
        if total > 120 * 1024 * 1024:
            raise ValueError('SQLite archive expansion exceeds bound')


def run(args, cwd=None, env=None, timeout=120):
    with subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, start_new_session=True) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args, output=output)
        return output


def toolchain(java_home):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Only native Linux x86_64 is validated by this recipe')
    tools = {}
    for name in ('java', 'javac', 'jar'):
        path = java_home / 'bin' / name
        tools[name] = {'path': str(path.resolve()), 'sha256': digest(path),
                       'version': run([str(path), '--version']).strip()}
    if not tools['javac']['version'].startswith('javac 17.'):
        raise ValueError('JDK 17 required')
    for name, args in [('gcc', ['--version']), ('make', ['--version']), ('tclsh', []),
                       ('perl', ['-v']), ('unzip', ['-v']), ('zip', ['-v']), ('patch', ['--version'])]:
        path = shutil.which(name)
        if not path:
            raise ValueError(f'Missing build tool: {name}')
        version = run([path, *args]) if args else subprocess.check_output(
            [path], input='puts [info patchlevel]\n', text=True, timeout=10)
        tools[name] = {'path': str(Path(path).resolve()), 'sha256': digest(path), 'version': version.strip()}
    return tools


def build_key(tools):
    files = [HERE / 'inputs.lock.json', PATCH, HERE / 'build.py', HERE / 'SQLiteSourceSmoke.java', HERE / 'SLF4J-LICENSE.txt']
    identity = {'schema': 1, 'target': 'Linux-x86_64', 'tools': tools,
                'recipe': {str(p.relative_to(HERE)): digest(p) for p in files}}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(), identity


def runtime_closure(native):
    libraries = {}
    for line in run(['ldd', str(native)]).splitlines():
        for word in line.split():
            if word.startswith('/') and Path(word).is_file():
                libraries[str(Path(word).resolve())] = digest(word)
    if not libraries:
        raise ValueError('Could not establish native runtime library closure')
    return libraries


def validate_output(output, key):
    metadata = output / 'complete.json'
    if not metadata.is_file() or metadata.is_symlink():
        raise ValueError('Existing output has no completed recipe metadata; refusing reuse')
    record = json.loads(metadata.read_text())
    if record.get('key') != key or set(record.get('artifacts', {})) != set(ARTIFACTS):
        raise ValueError('Existing output belongs to different/unknown recipe')
    for name, expected in record['artifacts'].items():
        path = output / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise ValueError(f'Corrupt cached artifact: {name}')
    if runtime_closure(output / 'native/libsqlitejdbc.so') != record.get('runtime_closure'):
        raise ValueError('Native runtime library closure changed')
    return record


def smoke(output, java_home):
    with tempfile.TemporaryDirectory(prefix='sqlite-smoke-') as temporary:
        classpath = os.pathsep.join(str(output / name) for name in (ARTIFACTS[0], ARTIFACTS[2]))
        log = run([str(java_home / 'bin/javac'), '--release', '17', '-cp', classpath,
                   '-d', temporary, str(HERE / 'SQLiteSourceSmoke.java')])
        log += run([str(java_home / 'bin/java'), '-XX:ActiveProcessorCount=2',
                    f'-Dorg.sqlite.lib.path={output / "native"}', '-Dorg.sqlite.lib.name=libsqlitejdbc.so',
                    '-cp', classpath + os.pathsep + temporary, 'SQLiteSourceSmoke',
                    str(output / 'native/libsqlitejdbc.so')])
        return log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True, help='SHA256-named verified input cache')
    parser.add_argument('--java-home', type=Path, default=Path(os.environ.get('JAVA_HOME', '/missing')))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    output, cache, java_home = args.output.resolve(), args.cache.resolve(), args.java_home.resolve()
    tools = toolchain(java_home)
    key, identity = build_key(tools)
    if digest(PATCH) != PATCH_SHA:
        raise ValueError('Unreviewed source repair patch')
    if output.exists():
        validate_output(output, key)
        print(smoke(output, java_home))
        print(f'Verified existing recipe {key}; no rebuild')
        return
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    if len(lock['inputs']) != 74 or sum(e['bytes'] for e in lock['inputs']) != 15814646:
        raise ValueError('Unexpected input inventory')
    output.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sqlite-source-', dir=output) as temporary:
        source = Path(temporary)
        for entry in lock['inputs']:
            name = relative(entry['path'])
            cached = cache / entry['sha256']
            if cached.is_symlink():
                raise ValueError('Symlink input cache rejected')
            if cached.exists():
                data = cached.read_bytes()
            elif args.offline:
                raise ValueError(f'Missing offline input: {name}')
            else:
                request = urllib.request.Request(entry['url'], headers={'User-Agent': 'uds-takserver-source-build'})
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read(entry['bytes'] + 1)
                checked(data, entry)
                cached.write_bytes(data)
            checked(data, entry)
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (source / 'amalgamation_version.sh').chmod(0o755)
        check_archive(source / 'target/sqlite-3.54.1-src.zip')
        if digest(source / 'Makefile') != ORIGINAL_MAKE:
            raise ValueError('Unexpected original Makefile')
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=source)
        if digest(source / 'Makefile') != PATCHED_MAKE:
            raise ValueError('Source repair result mismatch')
        offline_bin = source / 'offline-bin'
        offline_bin.mkdir()
        for name in ('curl', 'wget', 'docker', 'mvn'):
            shim = offline_bin / name
            shim.write_text('#!/bin/sh\necho "Unplanned build command refused" >&2\nexit 97\n')
            shim.chmod(0o755)
        env = dict(os.environ, JAVA_HOME=str(java_home),
                   PATH=str(offline_bin) + os.pathsep + str(java_home / 'bin') + os.pathsep + os.environ['PATH'])
        log = run(['make', '-j2', 'native', 'OS_NAME=Linux', 'OS_ARCH=x86_64',
                   'JAVA_CLASSPATH=target/classpath/slf4j-api.jar'], cwd=source, env=env, timeout=240)
        (output / 'native-build.log').write_text(log)
        java_sources = sorted((source / 'src/main/java').rglob('*.java'))
        if len(java_sources) != 59:
            raise ValueError('Unexpected ordinary Java source inventory')
        classes = source / 'host-classes'
        classes.mkdir()
        log = run([str(java_home / 'bin/javac'), '-J-Xmx256m', '-J-XX:ActiveProcessorCount=2',
                   '--release', '8', '-encoding', 'UTF-8', '-proc:none', '-cp',
                   str(source / 'target/classpath/slf4j-api.jar'), '-d', str(classes), *map(str, java_sources)])
        (output / 'java-build.log').write_text(log)
        service = classes / 'META-INF/services/java.sql.Driver'
        service.parent.mkdir(parents=True)
        shutil.copy2(source / 'src/main/resources/java.sql.Driver', service)
        properties = classes / 'META-INF/maven/org.xerial/sqlite-jdbc/pom.properties'
        properties.parent.mkdir(parents=True)
        properties.write_text('version=3.54.1.0\ngroupId=org.xerial\nartifactId=sqlite-jdbc\n')
        licenses = classes / 'META-INF/licenses'
        licenses.mkdir()
        for name in ('LICENSE', 'NOTICE', 'LICENSE.zentus'):
            shutil.copy2(source / name, licenses / name)
        run([str(java_home / 'bin/jar'), '--create', '--file', str(output / ARTIFACTS[0]), '-C', str(classes), '.'])
        with zipfile.ZipFile(output / ARTIFACTS[0]) as jar:
            if any(name.endswith(('.so', '.dll', '.dylib')) for name in jar.namelist()):
                raise ValueError('Unexpected bundled native binary')
        (output / 'native').mkdir()
        shutil.copy2(source / 'target/sqlite-3.54.1-Linux-x86_64/libsqlitejdbc.so', output / ARTIFACTS[1])
        shutil.copy2(source / 'target/classpath/slf4j-api.jar', output / ARTIFACTS[2])
        shutil.copy2(source / 'target/tmp-src.3.54.1/sqlite-src-3540100/manifest.uuid', output / 'sqlite-manifest.uuid')
    shutil.copy2(HERE / 'SLF4J-LICENSE.txt', output / 'SLF4J-LICENSE.txt')
    log = smoke(output, java_home)
    (output / 'smoke.log').write_text(log)
    record = {'key': key, 'identity': identity, 'runtime_closure': runtime_closure(output / ARTIFACTS[1]), 'artifacts': {name: digest(output / name) for name in ARTIFACTS},
              'scope': 'own Linux x86_64 JNI and Java source build; no ARM/Android facade/engine acceptance'}
    (output / 'complete.json').write_text(json.dumps(record, indent=2) + '\n')
    print(log)
    print(f'Completed own source build {key}')


if __name__ == '__main__':
    main()
