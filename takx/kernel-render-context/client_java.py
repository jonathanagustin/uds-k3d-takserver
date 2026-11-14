#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Recompile the entire composed Java graph with the canonical client profile."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import stat
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CLIENT = HERE.parent / 'kernel-client-interop'
SPEC = importlib.util.spec_from_file_location('context_prepare', HERE / 'prepare.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink input refused')
    require(stat.S_ISREG(path.stat().st_mode), 'regular file required')
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            value.update(block)
    return value.hexdigest()


def contract():
    context, _ = P.load_contract()
    client = json.loads(P.regular(CLIENT / 'inputs.lock.json'))
    require(client['actual_kernel_version'] == '8.30.5' and len(client['files']) == 9 and
            client['owned_java'] == {'java/PublicViewportFit.java':
                '859974cd29d84c4f2a9d6f7a27b4da9925e51b58e0a5cf6192efe19aebc6a35a'}, 'canonical client source contract differs')
    patch = P.regular(CLIENT / 'client-contracts.patch')
    require(hashlib.sha256(patch).hexdigest() == client['patch_sha256'], 'client patch differs')
    for name, pin in client['owned_java'].items():
        require(sha(CLIENT / name) == pin, 'owned Java source differs')
    return context, client, patch


def relative(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and path.suffix == '.java',
            'unsafe Java source path')
    return path


def syntax_arguments(row, native, headers):
    arguments = row.get('arguments') or shlex.split(row['command'])
    require(Path(arguments[0]).is_absolute(), 'absolute native compiler required')
    result, skip = [], False
    for argument in arguments:
        if skip:
            skip = False
            continue
        if argument in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
            skip = True
            continue
        if argument in ('-c', '-MD', '-MMD', '-MP'):
            continue
        result.append(argument.replace(str(native / 'java/jni-headers'), str(headers)))
    require(not skip, 'native command option is truncated')
    result.append('-fsyntax-only')
    return result


def build(args):
    context, client, patch = contract()
    native = args.native_proof.absolute()
    proof_file = native / 'experiment-complete.json'
    require(sha(proof_file) == args.native_proof_sha256, 'reviewed native proof differs')
    proof = json.loads(proof_file.read_text())
    require(proof.get('fresh_full_graph_compilation_passed') is True and proof.get('cpu_jni_controls_passed') is True and
            proof.get('native_translation_units') == {'core': 483, 'jni': 159, 'cesium': 173}, 'complete composed native producer required')
    require(any(name.endswith('/kernel-render-context/inputs.lock.json') and pin == sha(HERE / 'inputs.lock.json')
                for name, pin in proof['projection_recipe'].items()), 'native source profile differs')
    baseline_file = args.baseline_java_inputs.absolute()
    require(sha(baseline_file) == proof['baseline_java_inputs_sha256'], 'baseline Java inputs differ')
    baseline = json.loads(baseline_file.read_text())
    compdb_file = native / 'build/compile_commands.json'
    require(sha(compdb_file) == args.native_commands_sha256, 'reviewed native compilation database differs')
    compdb = json.loads(compdb_file.read_text())
    java = args.java_home.absolute()
    compiler_lock = json.loads(P.regular(HERE.parent / 'client-compiler/inputs.lock.json', 2 * 1024**2))
    for name in ('bin/java', 'bin/javac', 'release', 'lib/modules'):
        matches = [pin for reference, pin in compiler_lock['files'].items()
                   if reference.startswith('tools:') and reference.endswith('/' + name)]
        require(len(matches) == 1 and sha(java / name) == matches[0], 'qualified JDK compiler/module identity differs')
    output = args.output.absolute()
    roots = [native, baseline_file.parent, args.classpath_root.absolute(), args.renderer_jars.absolute(), java, REPO]
    require(not any(path.is_symlink() for path in (output, *output.parents)), 'symlink output refused')
    for root in roots:
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output), 'output overlaps inputs')
    require(not output.exists() and output.parent.is_dir() and shutil.disk_usage(output.parent).free >= 2 * 1024**3,
            'fresh output and free floor required')
    cp, inputs = [], {}
    require(len({Path(row['path']).name for row in baseline['classpath']}) == len(baseline['classpath']), 'ambiguous classpath basenames')
    for row in baseline['classpath']:
        path = args.classpath_root.absolute() / Path(row['path']).name
        require(sha(path) == row['sha256'], 'baseline public dependency differs')
        cp.append(path)
        inputs[str(path)] = row['sha256']
    for name, meta in client['public_runtime_jars'].items():
        path = args.renderer_jars.absolute() / name
        require(sha(path) == meta['sha256'], 'public renderer dependency differs')
        cp.append(path)
        inputs[str(path)] = meta['sha256']
    for path in [proof_file, baseline_file, compdb_file, Path(__file__), HERE / 'prepare.py', HERE / 'inputs.lock.json',
                 HERE / 'source-scope.json', HERE / 'render-context-control.patch', CLIENT / 'inputs.lock.json',
                 CLIENT / 'client-contracts.patch', HERE.parent / 'client-compiler/inputs.lock.json',
                 HERE.parent / 'native-commoncommo/runner.py', java / 'bin/java', java / 'bin/javac', java / 'release', java / 'lib/modules']:
        inputs[str(path)] = sha(path)
    output.mkdir(mode=0o700)
    stage, classes, headers = output / 'stage', output / 'classes', output / 'jni-headers'
    for path in (stage, classes, headers):
        path.mkdir()
    spec = importlib.util.spec_from_file_location('bounded', HERE.parent / 'native-commoncommo/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    record = {'schema': 1, 'type': 'public-context-client-java', 'actual_kernel_version': '8.30.5',
              'scope': 'whole Java composition and paired JNI header syntax; no native object build or client launch',
              'inputs': inputs, 'classpath': list(map(str, cp)), 'commands': [], 'completed': False, 'full_sdk_accepted': False, 'client_accepted': False}
    deadline = time.monotonic() + 300
    env = {key: value for key, value in os.environ.items() if key not in ('CLASSPATH', 'BASH_ENV', 'ENV')
           and not key.startswith(('LD_', 'DYLD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['LC_ALL'] = 'C'
    def write():
        (output / 'receipt.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    def run(argv, label, timeout):
        row = {'label': label, 'argv': list(map(str, argv))}
        record['commands'].append(row)
        write()
        runner.execute(row['argv'], output, label, min(timeout, deadline - time.monotonic()), env,
                       capture=True, disk_limit=96 * 1024**2, log_limit=4 * 1024**2)
        row['passed'] = True
        write()
    write()
    try:
        require(len(proof['source_manifest']) == 1399, 'complete native source inventory required')
        for name, meta in proof['source_manifest'].items():
            path = PurePosixPath(name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'unsafe native source path')
            source = native / 'layout' / name
            require(sha(source) == meta['sha256'], 'native source/header differs')
            inputs[str(source)] = meta['sha256']
        require(len(proof['java_source_manifest']) == 1238, 'complete Java source inventory required')
        for name, meta in proof['java_source_manifest'].items():
            relative(name)
            source = native / 'java/stage' / name
            require(sha(source) == meta['sha256'], 'composed Java source differs')
            inputs[str(source)] = meta['sha256']
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        changed = []
        for name, images in client['files'].items():
            path = native / 'layout' / name if name.endswith('.cpp') else stage / name
            pin = sha(path)
            if pin == images['after']:
                continue
            require(name.endswith('.java') and pin == images['before'], 'canonical client preimage differs')
            changed.append(name)
        require(len(changed) == 6, 'client Java composition membership differs')
        selected = output / 'client-java.patch'
        selected.write_bytes(P.selected_client_patch(patch, set(changed)))
        run(['/usr/bin/patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p1', '-d', stage, '-i', selected], 'apply-client-java', 20)
        for name, images in client['files'].items():
            require(sha(native / 'layout' / name if name.endswith('.cpp') else stage / name) == images['after'], 'client postimage differs')
        owned = stage / 'project-java/PublicViewportFit.java'
        owned.parent.mkdir(exist_ok=True)
        shutil.copyfile(CLIENT / 'java/PublicViewportFit.java', owned)
        inputs[str(CLIENT / 'java/PublicViewportFit.java')] = sha(owned)
        sources = sorted(stage.rglob('*.java'))
        require(len(sources) == 1239, 'whole composed Java source membership differs')
        record['source_manifest'] = {str(path.relative_to(stage)): sha(path) for path in sources}
        arguments = output / 'sources.args'
        arguments.write_text(''.join(json.dumps(str(path)) + '\n' for path in sources))
        run([java / 'bin/javac', '-J-Xmx768m', '-J-XX:ActiveProcessorCount=2', '--release', '11', '-encoding', 'UTF-8',
             '-proc:none', '-implicit:none', '-sourcepath', '', '-Xmaxerrs', '3000', '-cp', os.pathsep.join(map(str, cp)),
             '-d', classes, '-h', headers, '@' + str(arguments)], 'compile-whole-java', 180)
        targets = {str(native / 'layout' / name) for name in client['files'] if name.endswith('.cpp')}
        matched = set()
        for row in compdb:
            if row['file'] not in targets:
                continue
            command = syntax_arguments(row, native, headers)
            inputs[command[0]] = sha(Path(command[0]).resolve(strict=True))
            run(command, 'header-syntax-' + Path(row['file']).stem, 60)
            matched.add(row['file'])
        require(matched == targets, 'paired JNI compilation database membership differs')
        for name, pin in inputs.items():
            require(sha(Path(name).resolve(strict=True)) == pin, 'consumed producer input changed')
        for name, pin in record['source_manifest'].items():
            require(sha(stage / name) == pin, 'composed source changed')
        require(contract() == (context, client, patch), 'source profile changed')
        record.update(completed=True, source_count=1239, jni_header_syntax_checked=2,
                      classes={str(path.relative_to(classes)): sha(path) for path in classes.rglob('*.class')},
                      jni_headers={path.name: sha(path) for path in headers.glob('*.h')})
        require(len(record['classes']) == 2702 and len(record['jni_headers']) == 119, 'complete output membership differs')
        write()
    except BaseException:
        record['failed'] = True
        write()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'java'), default='verify')
    for name in ('native-proof', 'baseline-java-inputs', 'classpath-root', 'renderer-jars', 'java-home', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--native-proof-sha256')
    parser.add_argument('--native-commands-sha256')
    args = parser.parse_args()
    values = [value for key, value in vars(args).items() if key != 'phase']
    if args.phase == 'verify':
        require(not any(values), 'explicit java phase required for input/output paths')
        contract()
    else:
        require(all(values), 'all explicit reviewed producer inputs are required')
        build(args)


if __name__ == '__main__':
    main()
