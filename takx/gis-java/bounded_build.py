#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in bounded offline supervisor for genuine patched GIS SWIG/Java generation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-cache', 'java-home', 'swig', 'swig-lib', 'toolchain-receipt', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--toolchain-receipt-sha256', required=True)
    parser.add_argument('--patch-sha256', required=True)
    args = parser.parse_args()
    budget = module('gis_profile_budget', HERE.parent / 'native-gdal-jni/kml_profile.py')
    build = module('gis_profile_builder', HERE / 'build.py')
    out, cap, reserve = args.output.absolute(), 48 * 1024**2, 2 * 1024**2
    inputs = [HERE, args.source_cache.resolve(), args.java_home.resolve(), args.swig.resolve(), args.swig_lib.resolve(), args.toolchain_receipt.resolve()]
    budget.require(not out.exists() and not out.is_symlink(), 'fresh supervisor output required')
    for source in inputs:
        budget.require(not out.is_relative_to(source) and not source.is_relative_to(out), 'GIS supervisor input/output overlap')
    budget.require(shutil.disk_usage(out.parent).free >= budget.FREE_FLOOR + cap, 'full48MiB reservation above2GiBfloor required')
    baseline_file = budget.checked(args.toolchain_receipt, args.toolchain_receipt_sha256)
    baseline = json.loads(baseline_file.read_text())['tools']
    budget.require(set(baseline) == {'java', 'javac', 'jar', 'swig', 'swig_library'}, 'qualified GIS toolchain receipt required')
    budget.require(Path(baseline['java']['path']).parent.parent == args.java_home.resolve()
                   and Path(baseline['swig']['path']) == args.swig.resolve()
                   and Path(baseline['swig_library']['path']) == args.swig_lib.resolve(), 'explicit toolchain paths differ')
    for name, item in baseline.items():
        if name == 'swig_library':
            budget.verify_inventory(Path(item['path']), item['files'])
        else:
            budget.checked(item['path'], item['sha256'])
    budget.checked('/usr/bin/patch', args.patch_sha256)
    frozen = {str(path): budget.digest(path) for path in (Path(__file__), HERE / 'build.py',
        HERE / 'CompileApiProbe.java', HERE / 'GdalExceptionControls.java', HERE / 'sources.lock.json',
        HERE / 'jni-exceptions-profile-v2.json', HERE / 'patches/gdal-java-pending-exceptions-v2.patch',
        HERE.parent / 'native-gdal-jni/kml_profile.py', baseline_file, Path(sys.executable).resolve())}
    out.mkdir(mode=0o700)
    (out / 'tmp').mkdir()
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(('LD_', 'JAVA_', 'JDK_', 'GIS_JAVA_', 'SWIG_'))
           and name not in ('_JAVA_OPTIONS', 'CLASSPATH', 'BASH_ENV', 'ENV', 'PYTHONPATH')}
    env.update(PATH=str(args.java_home / 'bin') + ':/usr/bin:/bin', GIS_JAVA_OFFLINE='true',
               GIS_JAVA_CACHE_DIR=str(args.source_cache.resolve()), GIS_JAVA_BUILD_DIR=str(out / 'build'),
               GIS_JAVA_SWIG=str(args.swig.resolve()), SWIG_LIB=str(args.swig_lib.resolve()),
               TMPDIR=str(out / 'tmp'), LC_ALL='C.UTF-8')
    argv = [sys.executable, '-B', str(HERE / 'build.py')]
    failure = None
    try:
        budget.run_bounded(argv, out, 'gis-source-build', 240, env, cap=cap, reserve=reserve)
        metadata = json.loads((out / 'build/build-inputs.json').read_text())
        budget.require({name: metadata['tools'][name] for name in baseline} == baseline, 'generated toolchain differs from qualified inputs')
        budget.require(metadata['tools']['patch']['sha256'] == args.patch_sha256, 'patch tool differs')
        for name, item in metadata['tools'].items():
            if name == 'swig_library':
                budget.verify_inventory(Path(item['path']), item['files'])
            else:
                budget.checked(item['path'], item['sha256'])
        key, expected = build.fingerprint(metadata['lock'], metadata['tools'])
        budget.require(metadata == expected and build.completed(out / 'build', key), 'complete real GIS source proof required')
        for path, expected_sha in frozen.items():
            budget.require(budget.digest(path) == expected_sha, 'GIS supervisor bound source changed')
    except BaseException as error:
        failure = repr(error)
    result = {'schema': 1, 'status': 'PASS source/Java build' if failure is None else 'FAILED first attempt',
              'failure': failure, 'command': argv, 'boundSources': frozen, 'outputCapBytes': cap,
              'nativeApplicationOrSdkAcceptance': False}
    if (out / 'build/build-state.json').exists():
        result['gisReceiptSha256'] = budget.digest(out / 'build/build-state.json')
    data = (json.dumps(result, indent=2) + '\n').encode()
    budget.require(len(data) < reserve, 'GIS supervisor receipt reserve exceeded')
    budget.gate(out, len(data), cap=cap, reserve=reserve)
    (out / 'complete.json').write_bytes(data)
    for item in out.rglob('*'):
        if item.is_file():item.chmod(0o444)
    print(result['status'], failure)
    if failure is not None:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
