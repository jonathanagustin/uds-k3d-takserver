#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Verify the project elevation adapter or opt into exact frozen native controls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCES = ('java/gov/tak/project/contour/ElevationContours.java', 'tests/ElevationContourControls.java')
GRID = REPO / 'takx/contour-grid/java/gov/tak/project/contour/ContourGrid.java'
FLAGS = ('contour_api_implemented', 'layer_runtime_accepted', 'full_client_accepted')


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


def contract():
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    require(type(lock['schema']) is int and lock['schema'] == 1 and lock['profile'] == 'public-elevation-contours-v1', 'profile identity differs')
    require(set(lock['owned']) == set(SOURCES) and lock['checks'] == 275, 'closed source/control inventory differs')
    require(all(lock[key] is False for key in FLAGS), 'project adapter cannot grant client contour acceptance')
    for name, digest in lock['owned'].items():
        require(sha(HERE / name) == digest, 'owned adapter bytes differ')
    require(sha(GRID) == lock['grid_sha256'], 'reviewed contour algorithm differs')
    return lock


def controls(args):
    lock = contract()
    native, java, jdk, profile, output = [getattr(args, name).absolute() for name in ('native', 'java', 'jdk', 'elevation_profile', 'output')]
    for root in (native, java, jdk, profile, output):
        require(not any(path.is_symlink() for path in (root, *root.parents)), 'symlink root refused')
    for root in (native, java, jdk, profile, REPO):
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output), 'output overlaps input root')
    require(not output.exists() and output.parent.is_dir(), 'fresh output required')
    for name, digest in lock['elevation_profile'].items():
        path = profile / name
        require(not path.is_symlink() and sha(path) == digest, 'reviewed elevation consumer recipe differs')
    consumer = module('contour_elevation_verified_consumer', profile / 'controls.py')
    inputs, jars, _compiler = consumer.verify_inputs(native, java, jdk)
    for name, digest in lock['elevation_profile'].items():
        inputs[str(profile / name)] = digest
    paths = [*(HERE / name for name in SOURCES), GRID, HERE / 'inputs.lock.json', Path(__file__).resolve(),
             REPO / 'takx/native-commoncommo/runner.py', REPO / 'takx/jni_diagnostics.py']
    for path in paths:
        inputs[str(path)] = sha(path)
    runner = module('contour_elevation_bounded_executor', REPO / 'takx/native-commoncommo/runner.py')
    diagnostics = module('contour_elevation_diagnostics', REPO / 'takx/jni_diagnostics.py')
    output.mkdir(mode=0o700)
    classes = output / 'classes'
    classes.mkdir()
    products = {}
    record = {'schema': 1, 'type': 'public-elevation-contour-controls', 'scope': lock['scope'],
              'inputs': inputs, 'outputs': products, 'commands': [], 'completed': False,
              **{key: False for key in FLAGS}}

    def write():
        (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')

    def unchanged():
        require(all(sha(name) == digest for name, digest in inputs.items()), 'consumed input changed')
        require({str(path.relative_to(classes)) for path in classes.rglob('*') if path.is_file()} == set(products), 'closed class membership differs')
        require(all(sha(classes / name) == digest for name, digest in products.items()), 'compiled controls changed')

    env = {key: value for key, value in os.environ.items() if key not in ('CLASSPATH', 'BASH_ENV', 'ENV') and
           not key.startswith(('LD_', 'DYLD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['LC_ALL'] = 'C'
    classpath = ':'.join([str(java / 'classes'), *jars])
    commands = [('compile', [jdk / 'bin/javac', '--release', '17', '-proc:none', '-cp', classpath,
                 '-d', classes, GRID, *(HERE / name for name in SOURCES)]),
                ('runtime', [jdk / 'bin/java', '-Xcheck:jni', '-Xmx256m', '-Djava.awt.headless=true',
                 '-cp', str(classes) + ':' + classpath, 'ElevationContourControls', native / 'runtime-native.sha256'])]
    write()
    try:
        for label, command in commands:
            unchanged()
            item = {'label': label, 'argv': list(map(str, command))}
            record['commands'].append(item)
            write()
            try:
                runner.execute(item['argv'], output, label, 40, env, disk_limit=8 * 1024**2, log_limit=2 * 1024**2)
                item['exit'] = 0
            finally:
                log = output / (label + '.log')
                if log.is_file():
                    item['log_sha256'] = sha(log)
                write()
            if label == 'compile':
                products.update({str(path.relative_to(classes)): sha(path) for path in classes.rglob('*.class')})
                require(0 < len(products) <= 32, 'compiled product bound differs')
            unchanged()
        text = (output / 'runtime.log').read_text()
        require(re.search(r'ELEVATION_CONTOUR_CONTROLS_PASS checks=275\b', text) and
                not diagnostics.strict_jni_failures(text), 'actual elevation controls failed')
        record.update(completed=True, checks=275, strict_jni_diagnostics=0)
        write()
    except BaseException as error:
        record.update(failed=True, failure_type=type(error).__name__)
        write()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'controls'), default='verify')
    for name in ('native', 'java', 'jdk', 'elevation-profile', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args(argv)
    names = ('native', 'java', 'jdk', 'elevation_profile', 'output')
    if args.phase == 'verify':
        require(all(getattr(args, name) is None for name in names), 'control paths require explicit opt-in')
        contract()
        return
    require(all(getattr(args, name) is not None for name in names), 'complete control paths required')
    controls(args)


if __name__ == '__main__':
    main()
