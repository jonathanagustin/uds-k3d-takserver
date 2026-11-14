#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Source verification or opt-in vehicle metadata controls; no client launch."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = 'java/gov/tak/api/cot/detail/VehicleModelDetailHandler.java'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink input refused')
    require(stat.S_ISREG(path.stat().st_mode), 'regular input required')
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            value.update(block)
    return value.hexdigest()


def contract():
    require((HERE / 'inputs.lock.json').stat().st_size <= 65536, 'contract size bound')
    sha(HERE / 'inputs.lock.json')
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    require(lock['profile'] == 'public-vehicle-metadata-v1' and set(lock['owned']) ==
            {SOURCE, 'tests/VehicleModelControls.java'}, 'source profile differs')
    require(all(lock[key] is False for key in ('private_sdk_equivalence', 'vehicle_mesh_runtime_accepted',
            'contours_implemented', 'full_client_accepted')), 'source profile cannot grant acceptance')
    for name, pin in lock['owned'].items():
        require(sha(HERE / name) == pin, 'owned source bytes differ')
    return lock


def controls(args):
    lock = contract()
    proof_root = args.java_proof.absolute()
    proof_file = proof_root / 'receipt.json'
    require(proof_file.stat().st_size <= 4 * 1024**2, 'Java proof size bound')
    require(sha(proof_file) == args.java_proof_sha256, 'reviewed Java proof differs')
    proof = json.loads(proof_file.read_text())
    require(proof.get('type') == 'public-context-client-java' and proof.get('completed') is True and
            proof.get('source_count') == 1239 and proof.get('jni_header_syntax_checked') == 2,
            'complete public Java composition producer required')
    class_root = proof_root / 'classes'
    classes = proof['classes']
    require(len(classes) == 2702, 'complete class inventory required')
    for name, pin in classes.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and path.suffix == '.class', 'class path differs')
        require(sha(class_root / name) == pin, 'public class bytes differ')
    require({str(p.relative_to(class_root)) for p in class_root.rglob('*.class')} == set(classes),
            'public class membership differs')
    cp = [class_root]
    inputs = {str(proof_file): args.java_proof_sha256}
    for name in proof['classpath']:
        path = Path(name)
        require(path.is_absolute() and path.suffix == '.jar' and sha(path) == proof['inputs'][name],
                'public dependency differs')
        inputs[name] = proof['inputs'][name]
        cp.append(path)
    java = args.java_home.absolute()
    for name in ('bin/java', 'bin/javac', 'release', 'lib/modules'):
        inputs[str(java / name)] = sha(java / name)
    output = args.output.absolute()
    for root in (proof_root, REPO, java):
        require(output != root and not output.is_relative_to(root) and not root.is_relative_to(output),
                'new output must be disjoint from inputs')
    require(not any(path.is_symlink() for path in (output, *output.parents)), 'symlink output refused')
    require(not output.exists() and output.parent.is_dir(), 'fresh output required')
    output.mkdir(mode=0o700)
    classes_out = output / 'classes'
    classes_out.mkdir()
    for name in [SOURCE, 'tests/VehicleModelControls.java', 'inputs.lock.json', 'build.py']:
        inputs[str(HERE / name)] = sha(HERE / name)
    for name in ('takx/native-commoncommo/runner.py', 'takx/jni_diagnostics.py'):
        inputs[str(REPO / name)] = sha(REPO / name)
    spec = importlib.util.spec_from_file_location('bounded', REPO / 'takx/native-commoncommo/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    spec = importlib.util.spec_from_file_location('jni', REPO / 'takx/jni_diagnostics.py')
    diagnostics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostics)
    env = {key: value for key, value in os.environ.items() if key not in ('CLASSPATH', 'BASH_ENV', 'ENV')
           and not key.startswith(('LD_', 'DYLD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['LC_ALL'] = 'C'
    record = {'profile': lock['profile'], 'scope': lock['scope'], 'inputs': inputs,
              'commands': [], 'completed': False, 'full_client_accepted': False, 'vehicle_mesh_runtime_accepted': False}
    def write():
        (output / 'receipt.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    write()
    try:
        commands = [
            ('compile', [java / 'bin/javac', '--release', '11', '-proc:none', '-cp', os.pathsep.join(map(str, cp)),
                         '-d', classes_out, HERE / SOURCE, HERE / 'tests/VehicleModelControls.java']),
            ('controls', [java / 'bin/java', '-Xcheck:jni', '-Xmx128m', '-Djava.awt.headless=true',
                          '-cp', os.pathsep.join(map(str, [classes_out, *cp])), 'VehicleModelControls'])]
        for label, command in commands:
            row = {'label': label, 'argv': list(map(str, command))}
            record['commands'].append(row)
            write()
            runner.execute(row['argv'], output, label, 30, env, capture=True,
                           disk_limit=8 * 1024**2, log_limit=2 * 1024**2)
            row['passed'] = True
            row['log_sha256'] = sha(output / (label + '.log'))
        text = (output / 'controls.log').read_text()
        require('VEHICLE_MODEL_CONTROLS_PASS checks=34' in text and not diagnostics.strict_jni_failures(text),
                'vehicle metadata controls did not pass cleanly')
        for name, pin in inputs.items():
            require(sha(Path(name)) == pin, 'consumed input changed')
        for name, pin in classes.items():
            require(sha(class_root / name) == pin, 'public class changed')
        require({str(p.relative_to(class_root)) for p in class_root.rglob('*.class')} == set(classes),
                'public class membership changed')
        require(contract() == lock, 'source contract changed')
        record.update(completed=True, checks=34, strict_jni_diagnostics=0,
                      outputs={str(p.relative_to(classes_out)): sha(p) for p in classes_out.rglob('*.class')})
        write()
    except BaseException:
        record['failed'] = True
        write()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('verify', 'controls'), default='verify')
    parser.add_argument('--java-proof', type=Path)
    parser.add_argument('--java-proof-sha256')
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.phase == 'verify':
        require(not any((args.java_proof, args.java_proof_sha256, args.java_home, args.output)), 'paths require controls phase')
        contract()
    else:
        require(all((args.java_proof, args.java_proof_sha256, args.java_home, args.output)), 'explicit reviewed inputs required')
        controls(args)


if __name__ == '__main__':
    main()
