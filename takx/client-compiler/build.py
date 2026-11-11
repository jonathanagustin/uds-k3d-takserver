#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the full pinned Client using explicit, verified prerequisite outputs.

No acquisition, Gradle, JNI loading, client execution or implicit cache discovery.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import time

HERE = Path(__file__).resolve().parent
LOCK = HERE / 'inputs.lock.json'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(root, suffix):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*' + suffix))}


def resolve(ref, roots):
    name, relative = ref.split(':', 1)
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('unsafe relative input: ' + ref)
    result = (roots[name] / path).resolve(strict=True)
    if not result.is_relative_to(roots[name]):
        raise ValueError('input escapes bound root: ' + ref)
    return result


def verify(lock, roots):
    for ref, expected in {**lock['files'], **lock['sources']}.items():
        if sha(resolve(ref, roots)) != expected:
            raise ValueError('input digest differs: ' + ref)
    for ref, expected in lock['class_directories'].items():
        if inventory(resolve(ref, roots), '.class') != expected:
            raise ValueError('exact prerequisite class set differs: ' + ref)
    tree = resolve(lock['official_client_tree'], roots)
    if inventory(tree, '.java') != lock['official_client_sources']:
        raise ValueError('official Client source tree differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', required=True, type=Path,
                        help='JSON object mapping every lock root name to an absolute local directory')
    parser.add_argument('--output', type=Path, help='fresh output directory (must not exist)')
    parser.add_argument('--check-inputs', action='store_true', help='verify prerequisites only; no compiler')
    args = parser.parse_args()
    started = time.monotonic()
    lock_digest = sha(LOCK)
    builder_digest = sha(Path(__file__))
    lock = json.loads(LOCK.read_text())
    bindings = json.loads(args.bindings.read_text())
    if set(bindings) != set(lock['roots']):
        raise ValueError('bindings must name exactly the roots in inputs.lock.json')
    if any(not Path(value).is_absolute() for value in bindings.values()):
        raise ValueError('all root bindings must be absolute')
    roots = {name: Path(value).resolve(strict=True) for name, value in bindings.items()}
    verify(lock, roots)
    if args.check_inputs:
        print('Verified pinned files, full source tree and exact prerequisite class sets; no compiler run.')
        return
    if args.output is None:
        parser.error('--output is required for compilation')
    out = args.output.absolute().resolve()
    if out.exists():
        raise ValueError('fresh output directory required')
    if any(out.is_relative_to(root) or root.is_relative_to(out) for root in roots.values()):
        raise ValueError('output and prerequisite roots must not overlap')
    limits = lock['limits']
    if shutil.disk_usage(out.parent).free < limits['minimum_free_bytes']:
        raise ValueError('2GiB free disk floor')
    out.mkdir()
    for name in ['classes', 'generated', 'empty']:
        (out / name).mkdir()
    sources = [resolve(ref, roots) for ref in sorted(lock['sources'])]
    # javac argument files treat backslash and quote specially. Reject control
    # characters and quote/escape path characters rather than using a shell.
    if any(any(c in str(p) for c in '\n\r\x00') for p in sources):
        raise ValueError('source path contains unsupported control character')
    source_args = out / 'sources.args'
    source_args.write_text(''.join('"' + str(p).replace('\\', '\\\\').replace('"', '\\"') + '"\n' for p in sources))
    command = [str(resolve(lock['javac'], roots)), '-J-Xmx768m',
               '-J-XX:ActiveProcessorCount=2', '--release', '17', '-encoding', 'UTF-8',
               '-implicit:none', '-sourcepath', str(out / 'empty'), '-Xmaxerrs', '2000',
               '-cp', os.pathsep.join(str(resolve(p, roots)) for p in lock['classpath']),
               '-d', str(out / 'classes'), '-processor',
               'org.greenrobot.eventbus.annotationprocessor.EventBusAnnotationProcessor',
               '-processorpath', os.pathsep.join(str(resolve(p, roots)) for p in lock['processorpath']),
               '-AeventBusIndex=gov.takx.core.event.ClientEventIndex',
               '-s', str(out / 'generated'), '@' + str(source_args)]
    runner_path = HERE.parent / 'native-commoncommo/runner.py'
    if sha(runner_path) != lock['runner_sha256']:
        raise ValueError('bounded runner differs from lock')
    spec = importlib.util.spec_from_file_location('bounded_runner', runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original_disk_bytes = runner.disk_bytes

    def guarded_disk(root):
        if shutil.disk_usage(out).free < limits['minimum_free_bytes']:
            raise ValueError('2GiB free disk floor')
        if time.monotonic() - started > limits['aggregate_seconds']:
            raise ValueError('aggregate deadline')
        return original_disk_bytes(root)

    runner.disk_bytes = guarded_disk
    env = dict(os.environ)
    for key in ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', 'JDK_JAVAC_OPTIONS', '_JAVA_OPTIONS',
                'CLASSPATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'JAVA_HOME', 'JDK_HOME']:
        env.pop(key, None)
    result = {'scope': lock['scope'], 'compiler_success': False,
              'native_build_or_execution': False, 'client_runtime_acceptance': False,
              'full_gradle_build_acceptance': False, 'private_sdk_equivalence': False,
              'source_feature_native_runtime_acceptance': False,
              'inputs_lock_sha256': lock_digest, 'builder_sha256': builder_digest,
              'runner_sha256': lock['runner_sha256'], 'source_count': len(sources),
              'actual_kernel': lock['actual_kernel'], 'actual_commoncommo': lock['actual_commoncommo'],
              'command': command, 'limits': limits}
    try:
        remaining = min(limits['command_seconds'], limits['aggregate_seconds'] - (time.monotonic() - started))
        if remaining <= 0:
            raise ValueError('aggregate deadline')
        runner.execute(command, out, 'client', timeout=remaining, env=env,
                       disk_limit=limits['new_output_bytes'], log_limit=1024 * 1024)
        verify(lock, roots)
        if (sha(LOCK) != lock_digest or sha(Path(__file__)) != builder_digest or
                sha(runner_path) != lock['runner_sha256']):
            raise ValueError('lock or recipe changed during compilation')
        result['classes'] = inventory(out / 'classes', '.class')
        result['generated_sources'] = inventory(out / 'generated', '.java')
        result['error_count'] = len(re.findall(r'\.java:\d+: error:', (out / 'client.log').read_text(errors='replace')))
        if (sorted(result['classes']) != lock['expected_class_names'] or
                sorted(result['generated_sources']) != lock['expected_generated_sources'] or result['error_count']):
            raise ValueError('complete compiler/generator postconditions failed')
        result['compiler_success'] = True
    except (ValueError, OSError) as error:
        result['failure'] = str(error)
    result['elapsed_seconds'] = time.monotonic() - started
    if (out / 'client.log').exists():
        result['diagnostics_sha256'] = sha(out / 'client.log')
    receipt = json.dumps(result, indent=2, sort_keys=True) + '\n'
    # Reserve receipt bytes before publishing success, then check inclusive quota.
    if guarded_disk(out) + len(receipt.encode()) > limits['new_output_bytes']:
        raise ValueError('receipt-inclusive 15MiB output cap; no success receipt written')
    (out / 'complete.json').write_text(receipt)
    if not result['compiler_success']:
        raise ValueError('compiler not accepted; inspect bounded output receipt')
    print('Full Client compiler succeeded; runtime, native and full Gradle gates remain open.')


if __name__ == '__main__':
    main()
