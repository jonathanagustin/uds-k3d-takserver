#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Compile every pinned public desktop Kernel Java source; never build/load native code."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
MODULES = {
    'takkernel/annotation/src/main/java': 6,
    'takkernel/port/src/main/java': 57,
    'takkernel/port/src/jre/java': 20,
    'takkernel/engine/src/main/java': 848,
    'takkernel/engine/src/jre/java': 14,
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_lock(lock):
    if (lock.get('schema'), lock.get('revision'), lock.get('java_major'), lock.get('java_release')) != (1, REVISION, 17, 11):
        raise ValueError('unsupported source pin, schema or Java target')
    if lock.get('modules') != MODULES or len(lock.get('public_jars', {})) != 23:
        raise ValueError('complete desktop source/classpath inventory required')
    if set(lock['gis_java']['artifacts']) != {'gdal-2.4.4-mod-java.jar', 'assimp-4.0.1-mod-jassimp-java.jar'}:
        raise ValueError('both reviewed GIS source outputs are required')
    for name, entry in lock['public_jars'].items():
        url = urllib.parse.urlparse(entry['url'])
        if (Path(name).name != name or not name.endswith('.jar') or url.scheme != 'https'
                or url.hostname not in {'repo.maven.apache.org', 'jogamp.org'}
                or url.username or url.password or not url.path.endswith('/' + name)
                or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])
                or type(entry['bytes']) is not int or not 0 < entry['bytes'] <= 32 * 1024 * 1024):
            raise ValueError('unreviewed public dependency: ' + name)


def select_profile(lock, profile):
    selected = copy.deepcopy(lock)
    replacements = lock.get('patched_replacements', {})
    if len(replacements) != 6 or not set(replacements).issubset(lock['public_jars']):
        raise ValueError('six reviewed dependency replacements required')
    if profile == 'patched':
        for old, entry in replacements.items():
            del selected['public_jars'][old]
            selected['public_jars'][entry['name']] = {k: v for k, v in entry.items() if k != 'name'}
    elif profile != 'baseline':
        raise ValueError('unknown compilation profile')
    validate_lock(selected)
    return selected


def verified_jar(path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
        raise ValueError('public dependency integrity failed: ' + str(path))
    return path


def public_jar(cache, name, entry, fetch):
    path = cache / name
    if path.exists() or path.is_symlink():
        return verified_jar(path, entry)
    if not fetch:
        raise ValueError('missing dependency; provide it or use --fetch-dependencies: ' + name)
    cache.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='download-', dir=cache)
    try:
        with os.fdopen(descriptor, 'wb') as output, urllib.request.urlopen(entry['url'], timeout=60) as response:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > entry['bytes']:
                    raise ValueError('dependency download exceeds locked size: ' + name)
                output.write(block)
        verified_jar(Path(temporary), entry)
        try:
            os.link(temporary, path)
        except FileExistsError:
            verified_jar(path, entry)
        return path
    finally:
        Path(temporary).unlink(missing_ok=True)


def class_entries(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate GIS JAR entries')
        entries = {}
        for item in archive.infolist():
            relative = PurePosixPath(item.filename)
            if relative.is_absolute() or '..' in relative.parts or item.file_size > 4 * 1024 * 1024:
                raise ValueError('unsafe or oversized GIS JAR entry')
            if item.is_dir():
                continue
            if item.filename.endswith('.class'):
                entries[item.filename] = hashlib.sha256(archive.read(item)).hexdigest()
            elif item.filename not in {'META-INF/MANIFEST.MF', 'META-INF/LICENSE', 'META-INF/NOTICE'}:
                raise ValueError('unexpected non-class GIS JAR content: ' + item.filename)
        return dict(sorted(entries.items()))


def verified_class_entries(path, expected):
    if class_entries(path) != expected:
        raise ValueError('GIS class inventory or bytecode differs from the original probe: ' + path.name)


def verified_gis(build, lock):
    recipe = REPO / lock['gis_java']['recipe']
    spec = importlib.util.spec_from_file_location('verified_gis_recipe', recipe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = json.loads((build / 'build-inputs.json').read_text())
    state = json.loads((build / 'build-state.json').read_text())
    source_lock = json.loads((REPO / lock['gis_java']['source_lock']).read_text())
    module.validate_lock(source_lock)
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    if (inputs.get('lock') != source_lock or inputs.get('recipe_sha256') != digest(recipe)
            or inputs.get('probe_sha256') != digest(recipe.parent / 'CompileApiProbe.java')
            or state.get('input_key') != key
            or state.get('java_source_counts') != {'gdal': 58, 'assimp': 42}
            or state.get('native_built_or_loaded') is not False or (build / '.building').exists()
            or state.get('outputs') != module.output_files(build)):
        raise ValueError('GIS source recipe receipt/output integrity failed')
    artifacts = []
    for name, entry in lock['gis_java']['artifacts'].items():
        path = build / name
        verified_class_entries(path, entry['class_entries'])
        artifacts.append((path, {
            'role': 'verified GIS source output',
            'baseline_jar_sha256': entry['baseline_jar_sha256'],
            'whole_jar_matches_baseline': digest(path) == entry['baseline_jar_sha256'],
            'class_entries_matching_baseline': len(entry['class_entries']),
            'class_entries_sha256': canonical_hash(entry['class_entries']),
        }))
    return artifacts, {'receipt_sha256': digest(build / 'build-state.json'), 'input_key': key,
                       'source_lock_sha256': digest(REPO / lock['gis_java']['source_lock'])}


def upstream_sources(source, lock):
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], env=env, timeout=30)
    if git('rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('official checkout must be at the pinned revision')
    git('diff', '--exit-code', 'HEAD', '--', *MODULES)
    if any(p.endswith('.java') for p in git('ls-files', '--others', '--exclude-standard', '--', *MODULES).decode().splitlines()):
        raise ValueError('untracked Java files in the consumed upstream source trees')
    data = git('archive', '--format=tar', REVISION, *MODULES)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError('source archive exceeds reviewed bounds')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for item in archive:
            if not item.name.endswith('.java'):
                continue
            relative = PurePosixPath(item.name)
            if (not item.isfile() or relative.is_absolute() or '..' in relative.parts
                    or item.name in files or item.size > 2 * 1024 * 1024
                    or not any(item.name.startswith(m + '/') for m in MODULES)):
                raise ValueError('invalid Java source archive member')
            files[item.name] = archive.extractfile(item).read()
    counts = {m: sum(p.startswith(m + '/') for p in files) for m in MODULES}
    inventory = [{'path': p, 'sha256': hashlib.sha256(data).hexdigest()} for p, data in sorted(files.items())]
    if counts != MODULES or canonical_hash(inventory) != lock['source_inventory_sha256']:
        raise ValueError('pinned complete source inventory differs')
    return files, {entry['path']: entry['sha256'] for entry in inventory}


def adapter_sources(repo):
    """Snapshot only committed, unchanged Java bytes in the consumed adapter tree."""
    root = 'takx/compat/src/main/java'
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], env=env, timeout=30)
    commit = git('rev-parse', 'HEAD').decode().strip()
    changed = git('diff', '--name-only', '-z', commit, '--', root).split(b'\0')
    # Include ignored files: an ignored Java source must not sneak into this boundary.
    untracked = git('ls-files', '--others', '-z', '--', root).split(b'\0')
    if any(name.endswith(b'.java') for name in changed + untracked):
        raise ValueError('modified or untracked consumed adapter Java sources')
    files = {}
    for record in git('ls-tree', '-r', '-z', commit, '--', root).split(b'\0'):
        if not record:
            continue
        metadata, name = record.split(b'\t', 1)
        if not name.endswith(b'.java'):
            continue
        mode, kind, object_id = metadata.decode().split()
        relative = PurePosixPath(name.decode()).relative_to(root)
        source = repo / root / relative
        if (mode not in {'100644', '100755'} or kind != 'blob'
                or any(p.is_symlink() for p in (source, *source.parents) if p != repo and repo in p.parents)
                or not source.is_file()):
            raise ValueError('consumed adapter sources must be regular tracked files')
        original = git('cat-file', 'blob', object_id)
        if source.read_bytes() != original:
            raise ValueError('adapter bytes differ from recorded commit: ' + str(relative))
        files[relative.as_posix()] = original
    if not files:
        raise ValueError('real tracked adapter sources required')
    return commit, dict(sorted(files.items()))


def fresh_output(path):
    if path.is_symlink():
        raise ValueError('output must not be a symlink')
    path = path.resolve()
    if path.exists() or path == REPO or REPO in path.parents or any(c in str(path) for c in ('\n', '\r', os.pathsep)):
        raise ValueError('choose a new external output directory without classpath separators')
    return path


def quoted_argument(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('patched', 'baseline'), default='patched',
                        help='patched dependencies by default; baseline is historical investigation only')
    parser.add_argument('--source', type=Path, required=True, help='clean pinned official atak-civ checkout')
    parser.add_argument('--classpath-dir', type=Path, required=True, help='cache for the 23 exact public JARs')
    parser.add_argument('--gis-build', type=Path, required=True, help='completed output of takx/gis-java/build.py')
    parser.add_argument('--output', type=Path, required=True, help='new external proof directory; existing output is refused')
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'), required=not bool(os.environ.get('JAVA_HOME')))
    parser.add_argument('--fetch-dependencies', action='store_true', help='allow missing public JARs to download from locked URLs')
    args = parser.parse_args()
    lock = select_profile(json.loads((HERE / 'inputs.lock.json').read_text()), args.profile)
    output = fresh_output(args.output)
    java = args.java_home.resolve()
    javac = java / 'bin/javac'
    version = subprocess.check_output([str(javac), '-version'], stderr=subprocess.STDOUT, text=True).strip()
    if not re.fullmatch(r'javac 17\.[^\n]+', version):
        raise ValueError('JDK 17 javac required')
    sources, original_hashes = upstream_sources(args.source.resolve(), lock)
    jars = [(public_jar(args.classpath_dir.resolve(), n, e, args.fetch_dependencies),
             {'role': 'exact public dependency', 'url': e['url']}) for n, e in lock['public_jars'].items()]
    gis, gis_receipt = verified_gis(args.gis_build.resolve(), lock); jars.extend(gis)
    patch = REPO / lock['unused_import_patch']['path']
    if digest(patch) != lock['unused_import_patch']['sha256']:
        raise ValueError('unused-import patch differs from reviewed input')
    adapter_commit, adapters = adapter_sources(REPO)
    output.mkdir(parents=True, exist_ok=False)
    frozen = []
    for name, data in sorted(sources.items()):
        path = output / 'stage' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); frozen.append(path)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=output / 'stage', check=True, timeout=30)
    changed = []
    for path in frozen:
        name = path.relative_to(output / 'stage').as_posix()
        if digest(path) != original_hashes[name]:
            changed.append(name)
    if changed != [lock['unused_import_patch']['target']] or digest(output / 'stage' / changed[0]) != lock['unused_import_patch']['patched_sha256']:
        raise ValueError('unexpected upstream source modification')
    for name, data in adapters.items():
        path = output / 'stage/compat' / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data); frozen.append(path)
    (output / 'classpath').mkdir()
    classpath = []
    for source, metadata in jars:
        expected = digest(source); target = output / 'classpath' / source.name
        if target.exists():
            raise ValueError('duplicate frozen classpath filename')
        shutil.copyfile(source, target)
        if digest(target) != expected:
            raise ValueError('classpath changed during freeze')
        if source.name in lock['public_jars']:
            verified_jar(target, lock['public_jars'][source.name])
        else:
            verified_class_entries(target, lock['gis_java']['artifacts'][source.name]['class_entries'])
        classpath.append({'path': str(target), 'sha256': expected, **metadata})
    inputs = {
        'schema': 1, 'source_commit': adapter_commit,
        'adapter_inventory': [{'path': name, 'sha256': hashlib.sha256(data).hexdigest()} for name, data in adapters.items()],
        'classpath_profile': args.profile, 'upstream_revision': REVISION, 'engine_sources': 862, 'upstream_sources': 945,
        'unchanged_upstream_sources': 944, 'adapter_sources': len(adapters),
        'recipe_sha256': digest(HERE / 'build.py'), 'lock_sha256': digest(HERE / 'inputs.lock.json'),
        'toolchain': {'javac': str(javac), 'version': version, 'sha256': digest(javac)},
        'applied_patch': lock['unused_import_patch'], 'gis_receipt': gis_receipt,
        'sources': [{'path': str(p), 'sha256': digest(p),
                     **({'original_sha256': original_hashes[p.relative_to(output / 'stage').as_posix()]} if p in frozen[:945] else {})} for p in frozen],
        'classpath': classpath,
    }
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    (output / 'sources.args').write_text(''.join(quoted_argument(p) for p in frozen))
    cp = os.pathsep.join(e['path'] for e in classpath)
    (output / 'classpath.txt').write_text(cp + '\n'); (output / 'classes').mkdir()
    command = [str(javac), '-J-Xmx768m', '-J-XX:ActiveProcessorCount=2', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
               '-Xmaxerrs', '3000', '-sourcepath', '', '-cp', cp, '-d', str(output / 'classes'), '@' + str(output / 'sources.args')]
    (output / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (output / 'stdout.log').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
        try:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=180)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    for entry in inputs['sources'] + classpath:
        if digest(Path(entry['path'])) != entry['sha256']:
            raise ValueError('frozen compile input changed')
    diagnostics = (output / 'stderr.log').read_text()
    classes = {p.relative_to(output / 'classes').as_posix(): digest(p) for p in sorted((output / 'classes').rglob('*.class'))}
    (output / 'class-hashes.json').write_text(json.dumps(classes, indent=2) + '\n')
    summary = {'classpath_profile': args.profile, 'baseline_matching_public_jars': 23 if args.profile == 'baseline' else 17,
               'exit_code': code, 'errors': len(re.findall(r'^.*?:\d+: error:', diagnostics, re.M)),
               'warnings': len(re.findall(r'^.*?:\d+: warning:', diagnostics, re.M)), 'engine_sources': 862,
               'upstream_sources': 945, 'unchanged_upstream_sources': 944, 'adapter_sources': len(adapters),
               'all_sources': len(frozen), 'compiled_class_files': len(classes), 'exact_public_jars': 23,
               'source_rebuilt_gis_jars': 2, 'gis_classes_identical_to_original_probe': 107, 'native_or_client_acceptance': False}
    (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary)); raise SystemExit(code)


if __name__ == '__main__':
    main()
