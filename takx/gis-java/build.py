#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in official modified GIS Java bindings; no native compilation or JNI load."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def external(path):
    if path.is_symlink():
        raise ValueError("cache/build root must not be a symlink")
    path = path.resolve()
    if path == REPO or REPO in path.parents:
        raise ValueError("GIS Java cache/build paths must stay outside the checkout")
    return path


def validate_lock(lock):
    if lock.get('schema') != 1 or lock.get('java_major') != 17 or lock.get('java_release') != 11:
        raise ValueError("unsupported source lock or Java target")
    if lock.get('repository') != 'https://github.com/TAK-Product-Center/atak-civ':
        raise ValueError("GIS sources must come from the reviewed official repository")
    revision = lock.get('revision', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or set(lock.get('archives', {})) != {'gdal', 'assimp'}:
        raise ValueError("source revision or archive selection is invalid")
    names = {'gdal': 'gdal-2.4.4-mod.tar.gz', 'assimp': 'assimp-4.0.1-mod.tar.gz'}
    for kind, entry in lock['archives'].items():
        expected = ('https://media.githubusercontent.com/media/TAK-Product-Center/atak-civ/'
                    + revision + '/depends/' + names[kind])
        if entry.get('url') != expected or not re.fullmatch(r'[0-9a-f]{64}', entry.get('sha256', '')):
            raise ValueError("archive URL/revision/hash does not match the official source pin")
        if type(entry.get('bytes')) is not int or entry['bytes'] <= 0:
            raise ValueError("archive size must be a positive integer")


def verified(path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
        raise ValueError(f"archive integrity failed: {path.name}")
    return path


def archive(cache, entry, offline):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (entry['sha256'] + '.tar.gz')
    if target.exists() or target.is_symlink():
        return verified(target, entry)
    if offline:
        raise ValueError("offline source archive is missing")
    descriptor, temporary = tempfile.mkstemp(prefix='download-', dir=cache)
    try:
        with os.fdopen(descriptor, 'wb') as output, urllib.request.urlopen(entry['url'], timeout=60) as response:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > entry['bytes']:
                    raise ValueError("source download exceeds locked size")
                output.write(chunk)
        verified(Path(temporary), entry)
        # Never replace a concurrent download or adopt an unverified file.
        try:
            os.link(temporary, target)
        except FileExistsError:
            verified(target, entry)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)


def selected(name, kind):
    if kind == 'gdal':
        return name == 'gdal/LICENSE.TXT' or (name.startswith('gdal/') and
            (name.endswith('.h') or ('/swig/' in name and name.endswith(
                ('.i', '.java', '.txt', '.xml', '.base', '.opt', 'GNUmakefile')))))
    return name == 'assimp/LICENSE' or (name.startswith('assimp/port/jassimp/jassimp/src/jassimp/') and name.endswith('.java'))


def extract(path, destination, kind):
    seen = set()
    total = 0
    with tarfile.open(path, 'r:gz') as source:
        for member in source:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError("unsafe archive path")
            name = str(relative)
            if not selected(name, kind):
                continue
            if not member.isfile() or name in seen:
                raise ValueError("selected archive member is a link, non-file or duplicate")
            if member.size > 3_000_000:
                raise ValueError("selected source member exceeds size limit")
            seen.add(name)
            total += member.size
            if total > 40_000_000:
                raise ValueError("selected sources exceed size limit")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())
    return seen


def run(args, log=None, env=None):
    if log:
        with log.open('w') as output:
            subprocess.run(list(map(str, args)), check=True, stdout=output, stderr=subprocess.STDOUT, env=env)
    else:
        subprocess.run(list(map(str, args)), check=True, env=env)


def toolchain(lock):
    tools = {}
    for name in ('java', 'javac', 'jar', 'swig', 'patch'):
        chosen = os.environ.get('GIS_JAVA_SWIG') if name == 'swig' else None
        found = shutil.which(chosen or name)
        if not found:
            raise ValueError(f"required trusted tool missing: {name}")
        path = Path(found).resolve()
        flag = '--version' if name in ('jar', 'patch') else '-version'
        output = subprocess.check_output([str(path), flag], stderr=subprocess.STDOUT, text=True).strip()
        tools[name] = {'path': str(path), 'sha256': digest(path), 'version': output}
    if not re.search(r'\bjavac 17\.', tools['javac']['version']) or not re.search(r'version "17\.', tools['java']['version']):
        raise ValueError("use JDK 17 java/javac/jar on PATH")
    if not tools['jar']['version'].startswith('jar 17.'):
        raise ValueError("use the JDK 17 jar tool")
    if not re.search(r'\bSWIG Version ' + re.escape(lock['swig_version']) + r'(?:\s|$)', tools['swig']['version']):
        raise ValueError("SWIG version differs from the reviewed source-generation tool")
    library = Path(os.environ.get('SWIG_LIB') or subprocess.check_output(
        [tools['swig']['path'], '-swiglib'], text=True).strip()).resolve()
    if not library.is_dir():
        raise ValueError("SWIG library resources are missing; set SWIG_LIB for a staged tool")
    files = {str(p.relative_to(library)): digest(p) for p in sorted(library.rglob('*')) if p.is_file()}
    tools['swig_library'] = {'path': str(library), 'files': files}
    return tools


def jni_profile():
    profile = json.loads((HERE / 'jni-exceptions-profile-v2.json').read_text())
    patch = HERE / 'patches/gdal-java-pending-exceptions-v2.patch'
    if (profile.get('schema') != 1 or profile.get('profileId') != 'gdal244-java-pending-exceptions-v2'
            or set(profile.get('sources', {})) != {'swig/include/java/typemaps_java.i', 'swig/include/java/callback.i'}
            or digest(patch) != profile.get('patchSha256')):
        raise ValueError('unsupported or changed GDAL Java exception profile')
    return profile


def fingerprint(lock, tools):
    body = {'lock': lock, 'tools': tools, 'recipe_sha256': digest(HERE / 'build.py'),
            'probe_sha256': digest(HERE / 'CompileApiProbe.java'),
            'exception_controls_sha256': digest(HERE / 'GdalExceptionControls.java'),
            'gdal_java_exception_profile': jni_profile(),
            'gdal_java_exception_profile_sha256': digest(HERE / 'jni-exceptions-profile-v2.json')}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(), body


def output_files(build):
    result = {}
    for path in sorted(build.rglob('*')):
        if path.is_symlink():
            raise ValueError("build output contains a symlink")
        if path.is_file() and path not in (build / 'build-state.json', build / '.building'):
            result[str(path.relative_to(build))] = digest(path)
    return result


def completed(build, key):
    state = build / 'build-state.json'
    if not build.exists() or not any(build.iterdir()):
        return False
    if not state.is_file() or state.is_symlink() or (build / '.building').exists():
        raise ValueError("unknown or incomplete build prefix; select a new empty GIS_JAVA_BUILD_DIR")
    body = json.loads(state.read_text())
    if body.get('input_key') != key or body.get('outputs') != output_files(build):
        raise ValueError("changed build inputs or corrupt/unknown output; select a new empty GIS_JAVA_BUILD_DIR")
    return True


def probe(build, tools, destination):
    run([tools['javac']['path'], '-J-Xmx256m', '-J-XX:ActiveProcessorCount=2', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
         '-cp', os.pathsep.join(str(build / name) for name in ('gdal-2.4.4-mod-java.jar', 'assimp-4.0.1-mod-jassimp-java.jar')),
         '-d', destination, HERE / 'CompileApiProbe.java', HERE / 'GdalExceptionControls.java'])


def build_java(build, cache, lock, tools, offline):
    source = build / 'source'
    for kind, entry in lock['archives'].items():
        extract(archive(cache, entry, offline), source, kind)
    generated = build / 'generated'
    generated.mkdir()
    gdal = source / 'gdal'
    profile = jni_profile()
    for name, identity in profile['sources'].items():
        if digest(gdal / name) != identity['preSha256']:
            raise ValueError('GDAL Java exception patch preimage differs: ' + name)
    run([tools['patch']['path'], '--batch', '--fuzz=0', '-p1', '-d', gdal,
         '-i', HERE / 'patches/gdal-java-pending-exceptions-v2.patch'], build / 'jni-exception-patch.log')
    for name, identity in profile['sources'].items():
        if digest(gdal / name) != identity['postSha256']:
            raise ValueError('GDAL Java exception patch postimage differs: ' + name)
    env = {**os.environ, 'SWIG_LIB': tools['swig_library']['path']}
    commands = []
    for module in ('gdal', 'gdalconst', 'ogr', 'osr', 'gnm'):
        destination = generated / 'org/gdal' / module
        destination.mkdir(parents=True)
        args = [tools['swig']['path'], '-Wall', *['-I' + str(gdal / path) for path in
            ('swig/include', 'swig/include/java', 'swig/include/java/docs', 'gcore', 'port', 'ogr')]]
        if module != 'gdalconst':
            args.append('-c++')
        args += ['-java', '-outdir', destination, '-package', 'org.gdal.' + module, '-o',
                 generated / (module + '_wrap.' + ('c' if module == 'gdalconst' else 'cpp')),
                 gdal / 'swig/include' / (module + '.i')]
        commands.append(list(map(str, args)))
        run(args, build / (module + '-swig.log'), env)
    (build / 'generation-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    for kind, paths, jar, license_path in (
        ('gdal', sorted(generated.rglob('*.java')), 'gdal-2.4.4-mod-java.jar', gdal / 'LICENSE.TXT'),
        ('assimp', sorted((source / 'assimp/port/jassimp/jassimp/src/jassimp').glob('*.java')),
         'assimp-4.0.1-mod-jassimp-java.jar', source / 'assimp/LICENSE')):
        if len(paths) != lock['archives'][kind]['java_files']:
            raise ValueError("source count differs from the reviewed complete Java binding")
        classes = build / (kind + '-classes')
        classes.mkdir()
        run([tools['javac']['path'], '-J-Xmx256m', '-J-XX:ActiveProcessorCount=2', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
             '-d', classes, *paths], build / (kind + '-javac.log'))
        notices = classes / 'META-INF'
        notices.mkdir(exist_ok=True)
        shutil.copyfile(license_path, notices / 'LICENSE')
        if kind == 'assimp':
            headers = sorted({p.read_text().split('*/', 1)[0] + '*/' for p in paths})
            (notices / 'NOTICE').write_text('\n\n'.join(headers))
        run([tools['jar']['path'], '-J-XX:ActiveProcessorCount=2', '--create', '--file', build / jar, '-C', classes, '.'])
    probe(build, tools, build / 'probe-classes')


def main():
    lock = json.loads((HERE / 'sources.lock.json').read_text())
    validate_lock(lock)
    base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'uds-takserver/gis-java'
    cache = external(Path(os.environ.get('GIS_JAVA_CACHE_DIR', base / 'archives')))
    build = external(Path(os.environ.get('GIS_JAVA_BUILD_DIR', base / 'build')))
    if cache == build or cache in build.parents or build in cache.parents:
        raise ValueError("source cache and build prefix must be separate directories")
    offline = os.environ.get('GIS_JAVA_OFFLINE', 'false')
    if offline not in ('true', 'false'):
        raise ValueError("GIS_JAVA_OFFLINE must be true or false")
    tools = toolchain(lock)
    key, inputs = fingerprint(lock, tools)
    if completed(build, key):
        with tempfile.TemporaryDirectory(prefix='gis-java-probe-') as temporary:
            probe(build, tools, Path(temporary))
        print(f"Verified completed Java-only cache and compile API probe: {build}")
        return
    build.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(build / '.building', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    (build / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    build_java(build, cache, lock, tools, offline == 'true')
    state = {'input_key': key, 'outputs': output_files(build),
             'java_source_counts': {k: v['java_files'] for k, v in lock['archives'].items()},
             'api_probe': 'compile-only pass; never executed', 'native_built_or_loaded': False,
             'full_engine_or_takx_accepted': False}
    (build / 'build-state.json').write_text(json.dumps(state, indent=2) + '\n')
    (build / '.building').unlink()
    print(f"Built official modified Java bindings and compile API probe: {build}")


if __name__ == '__main__':
    main()
