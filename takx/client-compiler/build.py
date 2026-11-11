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
import zipfile

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



def load_helper(path, name):
    if not path.is_file():
        raise ValueError('mission admission verifier unavailable; no baseline Platform substitution')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def replace_platform_entry(references, roots, old_reference, new_classes):
    """Replace one provider in-place; never prepend a second class definition."""
    if references.count(old_reference) != 1:
        raise ValueError('one authoritative Platform CP entry required')
    original = resolve(old_reference, roots)
    replacement = Path(new_classes).resolve(strict=True)
    result = [replacement if ref == old_reference else resolve(ref, roots) for ref in references]
    if original in result:
        raise ValueError('old Platform must be removed, not shadowed by an overlay')
    return result

def mission_inputs(lock, roots, projection, platform_proof, receipt_sha):
    supplied = [projection is not None, platform_proof is not None, bool(receipt_sha)]
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError('mission admission requires checked projection and reviewed rebuilt Platform receipt SHA')
    mission = HERE.parent / 'mission-package'
    projector = load_helper(mission / 'project_sources.py', 'mission_source_projection')
    projected = projector.verify(projection)
    producer_path = HERE / 'platform_producer.py'
    producer = load_helper(producer_path, 'genuine_platform_producer')
    profile_file = mission / 'admission-profile.json'
    rebuilt = producer.verify_platform_proof(profile_file, sha(profile_file), platform_proof, receipt_sha)
    platform_name = 'gov/tak/platform/datapackage/PackageReader.class'
    old_platform = [ref for ref, names in lock['class_directories'].items() if platform_name in names]
    if len(old_platform) != 1 or lock['classpath'].count(old_platform[0]) != 1:
        raise ValueError('one authoritative baseline Platform CP entry required')
    classes = Path(rebuilt['classesPath']).resolve(strict=True)
    if any(character in str(classes) for character in '\n\r\0' + os.pathsep):
        raise ValueError('mission Platform path contains unsupported separators')
    classpath = replace_platform_entry(lock['classpath'], roots, old_platform[0], classes)
    profile = projector.profile()
    mission_classes = {path.removeprefix('Platform/src/main/java/').removesuffix('.java') + '.class'
                       for path, item in profile['sources'].items() if item['scope'] == 'Platform'}
    mission_classes.update(profile['platformReceipt']['newClassNames'])
    for path in classpath:
        if path == classes:
            continue
        if path.is_dir():
            if any((path / name).exists() for name in mission_classes):
                raise ValueError('duplicate mission Platform class provider')
        else:
            with zipfile.ZipFile(path) as archive:
                if mission_classes.intersection(archive.namelist()):
                    raise ValueError('duplicate mission Platform JAR provider')
    overrides = {}
    for path, item in profile['sources'].items():
        if item['scope'] != 'Client':
            continue
        matches = [ref for ref in lock['sources'] if ref.split(':', 1)[1] == '5.7/' + path]
        if len(matches) != 1 or lock['sources'][matches[0]] != item['preSha256']:
            raise ValueError('mission Client preimage differs from frozen baseline')
        overrides[matches[0]] = Path(projection) / 'source' / path
    if len(overrides) != 1:
        raise ValueError('one checked remote/import/extraction Client postimage required')
    lineage = {key: value for key, value in rebuilt.items() if key != 'classesPath'}
    lineage.update({'clientSourcePostimages': {path: item['postSha256'] for path, item in profile['sources'].items() if item['scope'] == 'Client'},
                    'projectionReceiptSha256': sha(Path(projection) / 'projection.json'),
                    'producerVerifierSha256': sha(producer_path),
                    'classDirectory': str(classes), 'fullClientOrRuntimeAcceptance': False})
    return {'sourceOverrides': overrides, 'classpath': classpath, 'lineage': lineage}


def allocated_bytes(root):
    root = Path(root)
    total, seen = 0, set()
    for path in [root]:
        stat = path.lstat()
        seen.add((stat.st_dev, stat.st_ino))
        total += stat.st_blocks * 512
    for path in root.rglob('*'):
        stat = path.lstat()
        identity = (stat.st_dev, stat.st_ino)
        if identity not in seen:
            seen.add(identity)
            total += stat.st_blocks * 512
    return total

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', type=Path,
                        help='JSON object mapping every lock root name to an absolute local directory')
    parser.add_argument('--output', type=Path, help='fresh output directory (must not exist)')
    parser.add_argument('--check-inputs', action='store_true', help='verify prerequisites only; no compiler')
    parser.add_argument('--mission-admission-export', type=Path, help='fresh checked source projection only; never compile')
    parser.add_argument('--mission-admission-source', type=Path, help='official 5.7 source for projection-only export')
    parser.add_argument('--mission-admission-projection', type=Path)
    parser.add_argument('--mission-platform-proof', type=Path)
    parser.add_argument('--mission-platform-receipt-sha256')
    args = parser.parse_args()
    if args.mission_admission_export is not None:
        if args.mission_admission_source is None or any((args.bindings, args.output, args.check_inputs,
                args.mission_admission_projection, args.mission_platform_proof, args.mission_platform_receipt_sha256)):
            parser.error('projection export requires only explicit source/output; it is not compiler acceptance')
        projector = load_helper(HERE.parent / 'mission-package/project_sources.py', 'mission_source_projection')
        projector.export(args.mission_admission_source, args.mission_admission_export)
        print('Checked actual mission source projection exported; rebuilt Platform and Client acceptance still required.')
        return
    if args.bindings is None or args.mission_admission_source is not None:
        parser.error('--bindings required for compiler/prerequisite mode; source flag belongs only to projection export')
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
    mission = mission_inputs(lock, roots, args.mission_admission_projection, args.mission_platform_proof, args.mission_platform_receipt_sha256)
    if args.check_inputs:
        print('Verified pinned files, full source tree and exact prerequisite class sets; no compiler run.')
        return
    if args.output is None:
        parser.error('--output is required for compilation')
    out = args.output.absolute().resolve()
    if out.exists():
        raise ValueError('fresh output directory required')
    protected_roots = list(roots.values())
    if mission:
        protected_roots.extend([args.mission_admission_projection.resolve(strict=True), args.mission_platform_proof.resolve(strict=True)])
    if any(out.is_relative_to(root) or root.is_relative_to(out) for root in protected_roots):
        raise ValueError('output and prerequisite roots must not overlap')
    limits = dict(lock['limits'])
    if mission:
        limits['allocated_output_bytes'] = 32 * 1024**2
    if shutil.disk_usage(out.parent).free < limits['minimum_free_bytes'] + limits.get('allocated_output_bytes', 0):
        raise ValueError('2GiB free disk floor')
    out.mkdir()
    for name in ['classes', 'generated', 'empty']:
        (out / name).mkdir()
    overrides = mission['sourceOverrides'] if mission else {}
    sources = [overrides.get(ref, resolve(ref, roots)) for ref in sorted(lock['sources'])]
    classpath = mission['classpath'] if mission else [resolve(ref, roots) for ref in lock['classpath']]
    # javac argument files treat backslash and quote specially. Reject control
    # characters and quote/escape path characters rather than using a shell.
    if any(any(c in str(p) for c in '\n\r\x00') for p in sources):
        raise ValueError('source path contains unsupported control character')
    source_args = out / 'sources.args'
    source_args.write_text(''.join('"' + str(p).replace('\\', '\\\\').replace('"', '\\"') + '"\n' for p in sources))
    command = [str(resolve(lock['javac'], roots)), '-J-Xmx768m',
               '-J-XX:ActiveProcessorCount=2', '--release', '17', '-encoding', 'UTF-8',
               '-implicit:none', '-sourcepath', str(out / 'empty'), '-Xmaxerrs', '2000',
               '-cp', os.pathsep.join(str(path) for path in classpath),
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
        if mission and allocated_bytes(out) > limits['allocated_output_bytes']:
            raise ValueError('mission Client 32MiB allocated output cap')
        if time.monotonic() - started > limits['aggregate_seconds']:
            raise ValueError('aggregate deadline')
        return original_disk_bytes(root)

    runner.disk_bytes = guarded_disk
    env = dict(os.environ)
    for key in ['JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', 'JDK_JAVAC_OPTIONS', '_JAVA_OPTIONS',
                'CLASSPATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'JAVA_HOME', 'JDK_HOME']:
        env.pop(key, None)
    source_arguments_sha256 = sha(source_args)
    result = {'scope': lock['scope'], 'compiler_success': False,
              'native_build_or_execution': False, 'client_runtime_acceptance': False,
              'full_gradle_build_acceptance': False, 'private_sdk_equivalence': False,
              'source_feature_native_runtime_acceptance': False,
              'inputs_lock_sha256': lock_digest, 'builder_sha256': builder_digest,
              'runner_sha256': lock['runner_sha256'], 'source_count': len(sources),
              'source_arguments_sha256': source_arguments_sha256,
              'actual_kernel': lock['actual_kernel'], 'actual_commoncommo': lock['actual_commoncommo'],
              'command': command, 'limits': limits}
    if mission:
        result['scope'] += ' with checked mission-admission-v2 source and rebuilt Platform'
        result['mission_admission_profile'] = mission['lineage']
    try:
        remaining = min(limits['command_seconds'], limits['aggregate_seconds'] - (time.monotonic() - started))
        if remaining <= 0:
            raise ValueError('aggregate deadline')
        runner.execute(command, out, 'client', timeout=remaining, env=env,
                       disk_limit=limits['new_output_bytes'], log_limit=1024 * 1024)
        verify(lock, roots)
        if mission and mission_inputs(lock, roots, args.mission_admission_projection, args.mission_platform_proof, args.mission_platform_receipt_sha256) != mission:
            raise ValueError('mission source/Platform lineage changed during compilation')
        if (sha(LOCK) != lock_digest or sha(Path(__file__)) != builder_digest or
                sha(runner_path) != lock['runner_sha256'] or sha(source_args) != source_arguments_sha256):
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
    if mission and allocated_bytes(out) + ((len(receipt.encode()) + 4095) // 4096) * 4096 > limits['allocated_output_bytes']:
        raise ValueError('mission Client receipt-inclusive allocated output cap')
    (out / 'complete.json').write_text(receipt)
    if not result['compiler_success']:
        raise ValueError('compiler not accepted; inspect bounded output receipt')
    print('Full Client compiler succeeded; runtime, native and full Gradle gates remain open.')


if __name__ == '__main__':
    main()
