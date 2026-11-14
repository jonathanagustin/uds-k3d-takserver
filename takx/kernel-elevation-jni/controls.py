#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in consumer of the frozen Native07 composition; never a native SDK builder."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
NATIVE_RECEIPT = '54630be999ac532f4724e0c62a5197e42f16f3244e1063022d6121e09cd8990e'
JAVA_RECEIPT = 'cc1098f808b9db9af92393f45552f698d67cca15ec5c7f23adcccef64d84d4c0'
RUNTIME_MANIFEST = 'bc80457f02e5fb41c4e406f2d62b405b21071ad89ed0cbd8fed20c135f711404'
PROBES = {'ElevationListenerProbe': 112, 'ElevationChunkProbe': 231}
JNI_HEADERS = {'include/jni.h': '1266aea5b9f5d5db1cb6f8e5c6c43cfa7f80bc4f72d7fe42c6131bb939dc70f4', 'include/linux/jni_md.h': '88cb5c33e306900dd35a78d5a439087123b8e91b0986bb5acb42cc9bd2fcc42e'}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify_inputs(native, java, jdk):
    inputs = {}

    def pin(path, expected):
        path = Path(path).absolute()
        require(path.is_file() and sha(path) == expected, 'reviewed input bytes differ')
        inputs[str(path)] = expected

    pin(native / 'experiment-complete.json', NATIVE_RECEIPT)
    pin(java / 'receipt.json', JAVA_RECEIPT)
    n = json.loads((native / 'experiment-complete.json').read_text())
    j = json.loads((java / 'receipt.json').read_text())
    require(n['fresh_full_graph_compilation_passed'] is True and j['completed'] is True,
            'complete reviewed producers required')
    for name, record in n['source_manifest'].items():
        pin(native / 'layout' / name, record['sha256'])
    for name, digest in j['source_manifest'].items():
        pin(java / 'stage' / name, digest)
    for directory, records in (('classes', j['classes']), ('jni-headers', j['jni_headers'])):
        actual = {str(path.relative_to(java / directory)) for path in (java / directory).rglob('*') if path.is_file()}
        require(actual == set(records), 'closed Java output membership differs')
        for name, digest in records.items():
            pin(java / directory / name, digest)
    for name in ('bin/java', 'bin/javac', 'lib/modules', 'release'):
        path = jdk / name
        require(str(path) in j['inputs'], 'reviewed JDK path required')
        pin(path, j['inputs'][str(path)])
    for name, digest in JNI_HEADERS.items():
        pin(jdk / name, digest)
    compiler = Path('/usr/bin/g++')
    pin(compiler, j['inputs'][str(compiler)])
    for name in j['classpath']:
        pin(name, j['inputs'][name])
    manifest = native / 'runtime-native.sha256'
    pin(manifest, RUNTIME_MANIFEST)
    for line in manifest.read_text().splitlines():
        digest, name = line.split(' ', 1)
        pin(name, digest)
    for phase in n['runtime']['phases'].values():
        for name, digest in phase['mapped_elfs'].items():
            pin(name, digest)
    profile = module('elevation_prepare_controls', HERE / 'prepare.py')
    lock, _patch = profile.contract()
    pin(HERE / 'prepare.py', sha(HERE / 'prepare.py'))
    pin(HERE / 'inputs.lock.json', sha(HERE / 'inputs.lock.json'))
    pin(HERE / 'elevation-jni-boundaries.patch', lock['patch_sha256'])
    for name, digest in lock['owned_controls'].items():
        pin(HERE / name, digest)
    return inputs, j['classpath'], compiler


def fresh_output(output, roots):
    require(not any(path.is_symlink() for path in (output, *output.parents)), 'symlink output refused')
    require(output.parent.is_dir() and not output.exists(), 'fresh output required')
    for root in roots:
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output), 'output overlaps input root')


def run(native, java, jdk, output):
    native, java, jdk, output = [Path(path).absolute() for path in (native, java, jdk, output)]
    for root in (native, java, jdk):
        require(not any(path.is_symlink() for path in (root, *root.parents)), 'symlink input root refused')
    fresh_output(output, (native, java, jdk, HERE.parents[1]))
    inputs, jars, compiler = verify_inputs(native, java, jdk)
    inputs[str(Path(__file__).resolve())] = sha(__file__)
    diagnostics_path = HERE.parent / 'jni_diagnostics.py'
    inputs[str(diagnostics_path)] = sha(diagnostics_path)
    diagnostics = module('elevation_control_diagnostics', diagnostics_path)
    runner_path = HERE.parent / 'native-commoncommo/runner.py'
    inputs[str(runner_path)] = sha(runner_path)
    runner = module('elevation_bounded_executor', runner_path)

    artifacts = {}

    def unchanged():
        require(all(sha(name) == digest for name, digest in inputs.items()), 'consumer inputs changed')
        require(all(sha(output / name) == digest for name, digest in artifacts.items()), 'consumer outputs changed')
        actual = {str(path.relative_to(output)) for path in output.rglob('*') if path.is_file() and path.suffix in ('.class', '.so')}
        require(actual == set(artifacts), 'closed consumer output membership differs')

    output.mkdir(mode=0o700)
    record = {'schema': 1, 'type': 'frozen-native07-elevation-controls', 'inputs': inputs,
              'commands': [], 'outputs': artifacts, 'completed': False, 'native_builder_integration': False,
              'strict_elevation_accepted': False, 'full_sdk_accepted': False, 'full_client_accepted': False}

    def write():
        (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')

    env = {key: value for key, value in os.environ.items() if key not in ('CLASSPATH', 'BASH_ENV', 'ENV') and
           not key.startswith(('LD_', 'DYLD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['LC_ALL'] = 'C'
    try:
        for probe, checks in PROBES.items():
            folder = output / probe
            folder.mkdir()
            (folder / 'classes').mkdir()
            cpp, jni = native / 'build/kernel-cpp', native / 'build/kernel-jni'
            classpath = ':'.join([str(java / 'classes'), *jars])
            library = folder / 'probe.so'
            commands = [('compile-java', [jdk / 'bin/javac', '--release', '17', '-proc:none', '-cp', classpath,
                         '-d', folder / 'classes', HERE / 'tests' / (probe + '.java')]),
                        ('compile-probe', [compiler, '-std=c++17', '-fPIC', '-shared', '-O1',
                         '-I' + str(native / 'layout/takkernel/engine/src/main/cpp'),
                         '-I' + str(native / 'layout/takkernel/engine/src/main/jni'),
                         '-I' + str(jdk / 'include'), '-I' + str(jdk / 'include/linux'),
                         HERE / 'tests' / (probe + '.cpp'), '-L' + str(jni), '-ltakenginejni',
                         '-L' + str(cpp), '-ltakengine', '-Wl,-rpath,' + str(jni) + ':' + str(cpp),
                         '-Wl,-z,defs', '-o', library]),
                        ('runtime', [jdk / 'bin/java', '-Xcheck:jni', '-Xmx256m', '-Djava.awt.headless=true',
                         '-cp', str(folder / 'classes') + ':' + classpath, probe,
                         native / 'runtime-native.sha256', library])]
            for label, argv in commands:
                unchanged()
                log = folder / (label + '.log')
                item = {'probe': probe, 'phase': label, 'argv': list(map(str, argv))}
                record['commands'].append(item)
                write()
                try:
                    runner.execute(item['argv'], folder, label, 40, env, capture=False,
                                   disk_limit=8 * 1024 * 1024, log_limit=2 * 1024 * 1024)
                    item['exit'] = 0
                finally:
                    if log.is_file():
                        item['log_sha256'] = sha(log)
                    write()
                if label in ('compile-java', 'compile-probe'):
                    products = list((folder / 'classes').rglob('*.class')) if label == 'compile-java' else [library]
                    require(0 < len(products) <= 32, 'bounded compiler outputs required')
                    for product in products:
                        artifacts[str(product.relative_to(output))] = sha(product)
                if label == 'runtime':
                    text = log.read_text()
                    marker = 'ELEVATION_' + ('LISTENER' if probe == 'ElevationListenerProbe' else 'CHUNK')
                    require(re.search(marker + r'_CONTROLS_PASS checks=' + str(checks) + r'\b', text) and
                            not diagnostics.strict_jni_failures(text), 'strict scoped controls failed')
                unchanged()
        record.update(completed=True, functional_checks=sum(PROBES.values()), strict_jni_diagnostics=0)
        write()
    except BaseException as error:
        record.update(failed=True, failure_type=type(error).__name__)
        write()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'run'), default='verify')
    for name in ('native', 'java', 'jdk', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args(argv)
    if args.phase == 'verify':
        require(all(getattr(args, name) is None for name in ('native', 'java', 'jdk', 'output')), 'run arguments require explicit opt-in')
        module('elevation_prepare_verify', HERE / 'prepare.py').contract()
        return
    require(all(getattr(args, name) is not None for name in ('native', 'java', 'jdk', 'output')), 'complete run arguments required')
    run(args.native, args.java, args.jdk, args.output)


if __name__ == '__main__':
    main()
