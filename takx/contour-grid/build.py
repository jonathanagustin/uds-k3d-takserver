#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Verify owned contour sources or explicitly run bounded pure-Java controls."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCES = ('java/gov/tak/project/contour/ContourGrid.java', 'java/gov/tak/project/contour/ContourClip.java',
           'tests/ContourGridControls.java', 'tests/ContourClipControls.java')
CONTROLS = {'ContourGridControls': ('controls', 'contour-grid-controls', 865),
            'ContourClipControls': ('clip-controls', 'contour-clip-controls', 380)}
FLAGS = ('contour_api_implemented', 'elevation_source_integrated', 'layer_runtime_accepted', 'full_client_accepted')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink input refused')
    require(stat.S_ISREG(path.stat().st_mode), 'regular input required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def contract():
    path = HERE / 'inputs.lock.json'
    sha(path)
    require(path.stat().st_size <= 65536, 'contract size bound')
    lock = json.loads(path.read_text())
    require(lock['schema'] == 1 and lock['profile'] == 'bounded-contour-grid-v1' and
            set(lock['owned']) == set(SOURCES), 'source profile differs')
    require(all(lock[key] is False for key in FLAGS), 'grid controls cannot grant client acceptance')
    require(lock['checks'] == 1245 and lock['control_inventory'] == {key: value[2] for key, value in CONTROLS.items()}, 'analytic control inventory differs')
    for name, pin in lock['owned'].items():
        require(sha(HERE / name) == pin, 'owned source bytes differ')
    return lock


def controls(args):
    lock = contract()
    java = args.java_home.absolute()
    output = args.output.absolute()
    for root in (REPO, java):
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output), 'output overlaps inputs')
    require(not any(p.is_symlink() for p in (output, *output.parents)), 'symlink output refused')
    require(not output.exists() and output.parent.is_dir(), 'fresh output required')
    compiler_lock = REPO / 'takx/client-compiler/inputs.lock.json'
    require(compiler_lock.stat().st_size <= 2 * 1024**2, 'compiler contract size bound')
    compiler = json.loads(compiler_lock.read_text())
    inputs = {str(compiler_lock): sha(compiler_lock)}
    for name in ('bin/java', 'bin/javac', 'release', 'lib/modules'):
        pins = [pin for reference, pin in compiler['files'].items()
                if reference.startswith('tools:') and reference.endswith('/' + name)]
        require(len(pins) == 1 and sha(java / name) == pins[0], 'qualified JDK compiler/module identity differs')
        inputs[str(java / name)] = pins[0]
    for name in (*SOURCES, 'inputs.lock.json', 'build.py'):
        inputs[str(HERE / name)] = sha(HERE / name)
    for name in ('takx/native-commoncommo/runner.py', 'takx/jni_diagnostics.py'):
        inputs[str(REPO / name)] = sha(REPO / name)
    def module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    runner = module('contour_bounded_runner', REPO / 'takx/native-commoncommo/runner.py')
    diagnostics = module('contour_jni_diagnostics', REPO / 'takx/jni_diagnostics.py')
    env = {k: v for k, v in os.environ.items() if k not in ('CLASSPATH', 'BASH_ENV', 'ENV')
           and not k.startswith(('LD_', 'DYLD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['LC_ALL'] = 'C'
    output.mkdir(mode=0o700)
    classes = output / 'classes'
    classes.mkdir()
    record = {'schema': 1, 'type': 'public-contour-grid-controls', 'scope': lock['scope'],
              'inputs': inputs, 'commands': [], 'completed': False, **{key: False for key in FLAGS}}
    def write():
        (output / 'receipt.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    write()
    try:
        commands = [
            ('compile', [java / 'bin/javac', '--release', '17', '-proc:none', '-classpath', classes,
                         '-d', classes, *(HERE / name for name in SOURCES)]),
            *[(label, [java / 'bin/java', '-Xcheck:jni', '-Xmx256m', '-Djava.awt.headless=true',
                       '-cp', classes, name]) for name, (label, _marker, _checks) in CONTROLS.items()]]
        for label, command in commands:
            row = {'label': label, 'argv': list(map(str, command))}
            record['commands'].append(row)
            write()
            runner.execute(row['argv'], output, label, 30, env, capture=True,
                           disk_limit=8 * 1024**2, log_limit=2 * 1024**2)
            row.update(passed=True, log_sha256=sha(output / (label + '.log')))
        for label, marker, checks in CONTROLS.values():
            text = (output / (label + '.log')).read_text()
            require(text.strip() == marker + ' passed checks=' + str(checks) and not diagnostics.strict_jni_failures(text),
                    'contour controls did not pass cleanly')
        for name, pin in inputs.items():
            require(sha(name) == pin, 'consumed input changed')
        require(contract() == lock, 'source contract changed')
        record.update(completed=True, checks=1245, control_inventory=lock['control_inventory'], strict_jni_diagnostics=0,
                      outputs={str(p.relative_to(classes)): sha(p) for p in classes.rglob('*.class')})
        write()
    except BaseException:
        record['failed'] = True
        write()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'controls'), default='verify')
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.phase == 'verify':
        require(args.java_home is None and args.output is None, 'paths require controls phase')
        contract()
    else:
        require(args.java_home is not None and args.output is not None, 'explicit JDK and fresh output required')
        controls(args)


if __name__ == '__main__':
    main()
