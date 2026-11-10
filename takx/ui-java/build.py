#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Build opt-in, project-identified UI Java candidates from locked local inputs."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = HERE / 'inputs.lock.json'
PROFILES = {
    'original': ['docking-core', 'docking-common', 'colorchooser-author-1.5',
                 'toast-1.0.3', 'salamander-tag-v1.1.1'],
    'wizard-reference': ['wizard-reference'],
}


class BuildFailure(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(files):
    return [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())]


def checked_inventory(files, expected, label):
    entries = inventory(files)
    if len(entries) != expected['count'] or canonical_hash(entries) != expected['inventory_sha256']:
        raise BuildFailure(label + ' inventory mismatch')
    return entries


def checked_file(path, expected, label):
    if not path.is_file() or path.is_symlink() or path.stat().st_size != expected['bytes']:
        raise BuildFailure(label + ' size/type mismatch')
    if sha256(path) != expected['sha256']:
        raise BuildFailure(label + ' SHA-256 mismatch')
    return path


def selected_artifacts(lock, profile):
    if lock.get('schema') != 1 or lock.get('java_major') != 17 or lock.get('java_release') != 8:
        raise BuildFailure('unsupported source schema or Java target')
    if profile not in PROFILES or lock.get('profiles') != PROFILES:
        raise BuildFailure('unknown or changed source profile')
    if lock['artifacts']['wizard-reference']['classification'] != 'experimental-source-reference':
        raise BuildFailure('Wizard must remain an experimental source reference')
    if lock['artifacts']['colorchooser-author-1.5']['classification'] != 'original-author-version-candidate':
        raise BuildFailure('colorchooser author version must remain an explicit candidate')
    return {name: lock['artifacts'][name] for name in PROFILES[profile]}


def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in value or str(path) != value:
        raise BuildFailure('unsafe source member path')
    return path


def wanted_member(name, artifact):
    java_prefix = artifact['java_root'] + '/'
    resource_prefix = artifact['resource_root'] + '/'
    return ((name.startswith(java_prefix) and name.endswith('.java'))
            or (name.startswith(resource_prefix) and PurePosixPath(name).suffix not in {'.java', '.class', '.form'})
            or name == artifact.get('generator', {}).get('grammar'))


def extract_source(path, descriptor, wanted, destination):
    checked_file(path, descriptor, 'source archive')
    prefix = descriptor['prefix']
    safe_relative(prefix.rstrip('/'))
    selected = {}
    seen = set()
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            if not member.name.startswith(prefix):
                if member.name != prefix.rstrip('/'):
                    raise BuildFailure('unexpected source archive root')
                continue
            relative = member.name[len(prefix):]
            if not relative:
                continue
            safe_relative(relative)
            if relative in seen:
                raise BuildFailure('duplicate source archive member')
            seen.add(relative)
            if not wanted(relative) or member.isdir():
                continue
            if not member.isfile() or member.size > 8 * 1024 * 1024:
                raise BuildFailure('source member must be a bounded regular file')
            data = archive.extractfile(member).read()
            selected[relative] = data
    if not selected:
        raise BuildFailure('no selected source members')
    for relative, data in selected.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return selected


def within(files, root, suffix=None):
    prefix = root + '/'
    return {path[len(prefix):]: data for path, data in files.items()
            if path.startswith(prefix) and (suffix is None or path.endswith(suffix))}


def resources(files, root):
    return {path: data for path, data in within(files, root).items()
            if PurePosixPath(path).suffix not in {'.java', '.class', '.form'}}


@contextmanager
def workspace(output):
    if output.is_symlink():
        raise BuildFailure('output must be a new external directory')
    output = output.resolve()
    repository = HERE.parents[1]
    if output.exists() or output == repository or repository in output.parents:
        raise BuildFailure('output must be a new external directory')
    if not output.parent.is_dir():
        raise BuildFailure('output parent must already exist')
    with tempfile.TemporaryDirectory(prefix='.ui-java-', dir=output.parent) as temporary:
        stage = Path(temporary)
        product = stage / 'product'
        product.mkdir()
        yield stage, product
        if output.exists() or output.is_symlink():
            raise BuildFailure('output appeared during build; refusing to replace it')
        os.rename(product, output)


def run_tool(command, directory, label, timeout):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (label + '-command.json')).write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
    env = {key: value for key, value in os.environ.items()
           if key not in {'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH'}}
    stdout, stderr = directory / (label + '-stdout.log'), directory / (label + '-stderr.log')
    with stdout.open('wb') as out, stderr.open('wb') as err:
        process = subprocess.Popen([str(x) for x in command], stdout=out, stderr=err,
                                   env=env, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise BuildFailure(label + ' timed out', {'command': [str(x) for x in command]}) from None
    if code:
        raise BuildFailure(label + ' failed', {
            'exit_code': code, 'command': [str(x) for x in command],
            'stdout_tail': stdout.read_bytes()[-65536:].decode('utf-8', errors='replace'),
            'stderr_tail': stderr.read_bytes()[-65536:].decode('utf-8', errors='replace'),
        })
    return stdout.read_text()


def package(path, files):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            safe_relative(name)
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def compile_artifact(name, artifact, lock, source_files, source_paths, jars, built, java, stage, product, timeout):
    original = within(source_files[artifact['source']], artifact['java_root'], '.java')
    source_receipt = checked_inventory(original, artifact['java'], 'Java source')
    data = resources(source_files[artifact['source']], artifact['resource_root'])
    resource_receipt = checked_inventory(data, artifact['resources'], 'resource')
    work, logs = stage / name, product / 'logs' / name
    work.mkdir()
    sources = [source_paths[artifact['source']] / artifact['java_root'] / relative for relative in sorted(original)]
    generated_receipt = []
    if generator := artifact.get('generator'):
        generated = work / 'generated'
        generated.mkdir()
        grammar = source_paths[artifact['source']] / generator['grammar']
        for tool, target, label in [('org.javacc.jjtree.Main', grammar, 'jjtree'),
                                    ('org.javacc.parser.Main', generated / 'AnimTimeParser.jj', 'javacc')]:
            run_tool([java / 'bin/java', '-Xmx256m', '-XX:ActiveProcessorCount=2', '-Djava.awt.headless=true',
                      '-cp', jars[generator['tool']], tool, '-OUTPUT_DIRECTORY=' + str(generated), target],
                     logs, label, timeout)
        generated_files = {path.name: path.read_bytes() for path in generated.glob('*.java')}
        generated_receipt = checked_inventory(generated_files, generator['generated'], 'generated parser')
        sources.extend(sorted(generated.glob('*.java')))
    classpath = [built[entry.removeprefix('artifact:')] if entry.startswith('artifact:') else jars[entry]
                 for entry in artifact['classpath']]
    classes, empty = work / 'classes', work / 'empty'
    classes.mkdir()
    empty.mkdir()
    args = work / 'sources.args'
    args.write_text(''.join('"' + str(path) + '"\n' for path in sources))
    run_tool([java / 'bin/javac', '-J-Xmx768m', '-J-XX:ActiveProcessorCount=2', '-J-Djava.awt.headless=true',
              '--release', str(lock['java_release']), '-proc:none', '-implicit:none', '-encoding', 'UTF-8',
              '-sourcepath', empty, '-classpath', os.pathsep.join(str(path) for path in classpath) or str(empty),
              '-d', classes, '@' + str(args)], logs, 'compile', timeout)
    class_files = {str(path.relative_to(classes)): path.read_bytes() for path in sorted(classes.rglob('*.class'))}
    if not class_files:
        raise BuildFailure('compiler emitted no classes')
    notices = {}
    for notice in artifact['notices']:
        value = ((stage / 'license' / notice['path']).read_bytes() if notice['source'] == 'license'
                 else source_files[notice['source']][notice['path']])
        notices['META-INF/licenses/' + notice['target']] = value
    headers = set()
    for value in original.values():
        text = value.decode('utf-8')
        if match := re.search(r'^\s*package\s+[\w.]+\s*;', text, re.MULTILINE):
            if header := text[:match.start()].strip():
                headers.add(header)
    notices['META-INF/licenses/source-notices.txt'] = ('\n\n'.join(sorted(headers)) + '\n').encode()
    identity = {'project_artifact': 'uds-takserver-ui-' + name,
                'classification': artifact['classification'], **artifact['identity'],
                'original_source_files': len(original), 'generated_source_files': len(generated_receipt),
                'complete_client_or_runtime_acceptance': False}
    metadata = {
        'META-INF/MANIFEST.MF': ('Manifest-Version: 1.0\r\nImplementation-Title: uds-takserver UI Java candidate\r\n'
                               'Implementation-Version: 0.1.0\r\n\r\n').encode(),
        'META-INF/UPSTREAM-SOURCE.json': (json.dumps(identity, indent=2) + '\n').encode(), **notices,
    }
    target = product / ('uds-takserver-ui-' + name + '.jar')
    jar = package(target, {**class_files, **data, **metadata})
    source_output = dict(original)
    if generated_receipt:
        for path in generated.glob('*.java'):
            value = path.read_bytes()
            match = re.search(rb'^\s*package\s+([\w.]+)\s*;', value, re.MULTILINE)
            source_output[match[1].decode().replace('.', '/') + '/' + path.name] = value
    source_jar = package(product / ('uds-takserver-ui-' + name + '-sources.jar'), {**source_output, **data, **metadata})
    built[name] = target
    return {**identity, 'artifact': jar, 'source_archive': source_jar, 'java_sources': source_receipt,
            'generated_sources': generated_receipt, 'resources': resource_receipt,
            'licenses': inventory(notices), 'class_files': inventory(class_files),
            'classpath': [{'file': path.name, 'sha256': sha256(path)} for path in classpath]}


def build(source_dir, classpath_dir, output, java, profile='original', timeout=180):
    lock = json.loads(LOCK.read_text())
    artifacts = selected_artifacts(lock, profile)
    source_names = {artifact['source'] for artifact in artifacts.values()}
    source_names.update(notice['source'] for artifact in artifacts.values() for notice in artifact['notices']
                        if notice['source'] != 'license')
    # Verify every whole input before parsing source archives or launching tools.
    for name in source_names:
        item = lock['archives'][name]
        checked_file(source_dir / item['file'], item, 'source archive')
    required = {entry for artifact in artifacts.values() for entry in artifact['classpath']
                if not entry.startswith('artifact:')}
    required.update(artifact['generator']['tool'] for artifact in artifacts.values() if 'generator' in artifact)
    jars = {name: checked_file(classpath_dir / name, lock['public_jars'][name], 'dependency JAR') for name in required}
    license_required = any(notice['source'] == 'license' for artifact in artifacts.values() for notice in artifact['notices'])
    if license_required:
        checked_file(source_dir / lock['license_text']['file'], lock['license_text'], 'license text')
    java = java.resolve()
    with workspace(output) as (stage, product):
        version = run_tool([java / 'bin/javac', '--version'], product / 'logs', 'toolchain', 10).strip()
        if not re.fullmatch(r'javac 17(?:\.[0-9]+)*(?:[+-][\w.]+)?', version):
            raise BuildFailure('JDK 17 is required')
        source_paths, source_files = {}, {}
        for name in sorted(source_names):
            consumers = [artifact for artifact in artifacts.values() if artifact['source'] == name]
            notice_paths = {notice['path'] for artifact in artifacts.values() for notice in artifact['notices']
                            if notice['source'] == name}
            source_paths[name] = stage / 'sources' / name
            source_files[name] = extract_source(source_dir / lock['archives'][name]['file'], lock['archives'][name],
                lambda path, consumers=consumers, notice_paths=notice_paths:
                    path in notice_paths or any(wanted_member(path, artifact) for artifact in consumers), source_paths[name])
        if license_required:
            target = stage / 'license' / lock['license_text']['file']
            target.parent.mkdir()
            target.write_bytes((source_dir / lock['license_text']['file']).read_bytes())
        built, results = {}, []
        for name, artifact in artifacts.items():
            results.append(compile_artifact(name, artifact, lock, source_files, source_paths, jars,
                                           built, java, stage, product, timeout))
        for name in source_names:
            item = lock['archives'][name]
            checked_file(source_dir / item['file'], item, 'source archive after compilation')
        for name, path in jars.items():
            checked_file(path, lock['public_jars'][name], 'dependency JAR after compilation')
        if license_required:
            checked_file(source_dir / lock['license_text']['file'], lock['license_text'], 'license text after compilation')
        receipt = {'schema': 1, 'profile': profile, 'scope': 'source-built compiler-probe candidates only',
                   'complete_client_or_runtime_acceptance': False,
                   'recipe_sha256': sha256(Path(__file__)), 'lock_sha256': sha256(LOCK),
                   'toolchain': {'version': version, 'javac_sha256': sha256(java / 'bin/javac'),
                                 'java_sha256': sha256(java / 'bin/java'), 'release': lock['java_release']},
                   'sources': {name: lock['archives'][name] for name in sorted(source_names)},
                   'dependencies': {name: lock['public_jars'][name] for name in sorted(required)}, 'artifacts': results}
        (product / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-dir', type=Path, required=True, help='directory of the exact locked local archives')
    parser.add_argument('--classpath-dir', type=Path, required=True, help='directory of locked public Java JARs')
    parser.add_argument('--output', type=Path, required=True, help='new external output directory')
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'), required=not bool(os.environ.get('JAVA_HOME')))
    parser.add_argument('--profile', choices=PROFILES, default='original')
    parser.add_argument('--timeout-seconds', type=int, choices=range(1, 601), default=180, metavar='1..600')
    parser.add_argument('--failure-report', type=Path, help='optional new JSON diagnostic file; never a partial artifact directory')
    args = parser.parse_args()
    if args.failure_report and args.failure_report.exists():
        parser.error('failure report must not already exist')
    try:
        result = build(args.sources_dir, args.classpath_dir, args.output, args.java_home,
                       args.profile, args.timeout_seconds)
    except (BuildFailure, OSError, tarfile.TarError) as error:
        if args.failure_report:
            args.failure_report.write_text(json.dumps({'error': str(error), 'details': getattr(error, 'details', {})}, indent=2) + '\n')
        parser.exit(1, str(error) + '\n')
    print(json.dumps({'profile': result['profile'], 'artifacts': len(result['artifacts']),
                      'complete_client_or_runtime_acceptance': False}))


if __name__ == '__main__':
    main()
