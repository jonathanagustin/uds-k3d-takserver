#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit CPU-only compile/run of the production wrapper and genuine Work."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('context_source', HERE/'prepare.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
SOURCES = ['util/Work.cpp', 'util/Logging2.cpp', 'port/Platform.cpp', 'port/String.cpp',
           'thread/Mutex.cpp', 'thread/Lock.cpp', 'thread/Cond.cpp', 'thread/Monitor.cpp',
           'thread/RWMutex.cpp', 'thread/impl/ThreadImpl_common.cpp',
           'thread/impl/ThreadImpl_libpthread.cpp']
PREFIX = 'takkernel/engine/src/main/cpp/'


def sha(path):
    return hashlib.sha256(P.regular(path, 32*1024**2)).hexdigest()


def wrapper_source(data):
    start = '    class RetirableWorker final : public ControlWorker {'
    end = '    struct ContextWorkers {'
    if data.count(start) != 1 or data.count(end) != 1:
        raise ValueError('production wrapper boundaries differ')
    first, last = data.index(start), data.index(end)
    if first >= last:
        raise ValueError('production wrapper order differs')
    return data[first:last]


def run(args):
    lock, _ = P.load_contract()
    official, prepared, output = (p.resolve() for p in (args.official_source, args.prepared_source, args.output))
    for root in (official, prepared, HERE.parents[1]):
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError('new output must be disjoint from source inputs')
    if output.exists() or not output.parent.is_dir():
        raise ValueError('fresh output under an existing parent required')
    P.verify_stage(prepared, lock['stages']['client_jni'])
    pins = json.loads(P.regular(HERE.parent/'kernel-native/native-sources.lock.json'))
    compiler = Path(shutil.which(args.cxx) or args.cxx).resolve(strict=True)
    compiler_sha = sha(compiler)
    output.mkdir(mode=0o700)
    contracts = [Path(__file__).resolve(), HERE/'prepare.py', HERE/'inputs.lock.json',
                 HERE.parent/'kernel-native/native-sources.lock.json']
    contract_hashes = {str(path): sha(path) for path in contracts}
    records, inputs = [], {}
    deadline = time.monotonic()+120

    def command(argv, seconds=30):
        remaining = min(seconds, deadline-time.monotonic())
        if remaining <= 0:
            raise TimeoutError('CPU control aggregate deadline')
        # Existing bounded runner owns process groups, stream and file limits.
        runner = P.Runner(output)
        runner.deadline = time.monotonic()+remaining
        try:
            return runner.run(argv, limit=65536)
        finally:
            records.extend(runner.records)

    def official_input(path):
        name = str(path.relative_to(official))
        if name not in pins or sha(path) != pins[name]['sha256']:
            raise ValueError('official CPU source/header differs: '+name)
        inputs[name] = pins[name]['sha256']

    try:
        version = command([str(compiler), '--version']).decode()
        source = prepared/(PREFIX+'renderer/GLWorkers.cpp')
        body = wrapper_source(P.regular(source).decode())
        header = output/'RetirableWorkerUnderTest.hpp'
        header.write_text('#include "util/Work.h"\n#include <mutex>\n#include <thread>\n'
                          '#include <algorithm>\nusing namespace TAK::Engine::Util;\n'+body)
        control = HERE/'tests/WorkerRetirementControl.cpp'
        inputs['production_wrapper'] = hashlib.sha256(body.encode()).hexdigest()
        inputs['control'] = sha(control)
        objects = []
        flags = ['-std=c++17', '-pthread', '-O1', '-I'+str(official/PREFIX), '-I'+str(output)]
        for index, unit in enumerate([control, *[official/(PREFIX+name) for name in SOURCES]]):
            if unit != control:
                official_input(unit)
            dependencies = command([str(compiler), *flags, '-MM', str(unit)]).decode()
            for name in shlex.split(dependencies.replace('\\\n', ' '))[1:]:
                dependency = Path(name).resolve(strict=True)
                if dependency not in (control, header):
                    official_input(dependency)
            target = output/(str(index)+'.o')
            command([str(compiler), *flags, '-c', str(unit), '-o', str(target)])
            objects.append(target)
        binary = output/'worker-retirement-control'
        command([str(compiler), '-pthread', '-Wl,-z,defs', *map(str, objects), '-o', str(binary)])
        observed = command([str(binary)], seconds=5).decode()
        expected = 'retirement=0 expected=0 completed=1 canceled=1 foreign_rejected=1 closed=1 error_preserved=1\n'
        if observed != expected:
            raise ValueError('native CPU control output differs')
        for name, expected_sha in inputs.items():
            if name.startswith(PREFIX) and sha(official/name) != expected_sha:
                raise ValueError('official input changed during control')
        P.verify_stage(prepared, lock['stages']['client_jni'])
        if sha(compiler) != compiler_sha or sha(control) != inputs['control']:
            raise ValueError('compiler/control changed during execution')
        if any(sha(Path(path)) != value for path, value in contract_hashes.items()):
            raise ValueError('control producer/source contract changed during execution')
        receipt = {'scope': 'CPU wrapper/Work control only; no renderer, JNI, GL or SDK qualification',
                   'official_revision': lock['official_revision'], 'kernel_version': '8.30.5',
                   'patch_sha256': lock['context_patch_sha256'], 'inputs': inputs,
                   'control_contracts': contract_hashes,
                   'compiler_sha256': compiler_sha, 'compiler_version': version,
                   'commands': records, 'observed': observed,
                   'outputs': {p.name: sha(p) for p in [header, *objects, binary]},
                   'accepted': True, 'gpu_qualified': False, 'full_sdk_accepted': False}
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
        print(observed, end='')
    except BaseException:
        (output/'first-failure.json').write_text(json.dumps({'accepted': False, 'commands': records}, indent=2)+'\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('official-source', 'prepared-source', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--cxx', default='g++')
    run(parser.parse_args())
