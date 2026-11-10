#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Compile the complete pinned NASA Java tree without loading native code.

The explicit project profile adapts NASA custom GDAL APIs to pinned public GDAL.
All inputs are supplied locally; partial compilations are never packaged.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REVISION = '9ccf6b8ed2ae452ef51e7b1739a7ffd4ef78a403'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(lock):
    if (lock.get('schema'), lock.get('revision'), lock.get('java_release'),
            lock.get('java_count')) != (1, REVISION, 17, 1726):
        raise ValueError('unsupported complete-source profile')
    if lock.get('profile') != 'project-standard-gdal-rgb':
        raise ValueError('explicit standard GDAL RGB profile required')
    if set(lock.get('project_inputs', {})) != {'standard-gdal.patch', 'ProjectPaletteColorModel.java'}:
        raise ValueError('complete project adaptations required')
    for name, expected in lock['project_inputs'].items():
        if digest(HERE / name) != expected:
            raise ValueError('project adaptation integrity mismatch: ' + name)
    if set(lock.get('verifiers', {})) != {'takx/kernel-java/build.py', 'takx/gis-java/build.py'}:
        raise ValueError('complete receipt verifiers required')
    for name, expected in lock['verifiers'].items():
        if digest(REPO / name) != expected:
            raise ValueError('receipt verifier integrity mismatch: ' + name)
    license_entry = lock.get('project_license', {})
    if (license_entry.get('path') != 'LICENSE'
            or license_entry.get('combined_variant_spdx') != 'GPL-3.0-only'
            or digest(REPO / 'LICENSE') != license_entry.get('sha256')):
        raise ValueError('combined project variant license integrity mismatch')
    if set(lock['public_jars']) != {'jogl-all-2.5.0.jar', 'gluegen-rt-2.5.0.jar'}:
        raise ValueError('exact JOGL/gluegen pair required')
    for p, sha in lock['files'].items():
        if (Path(p).is_absolute() or '..' in Path(p).parts or len(sha) != 64
                or not (p.startswith('src/') or p in lock['notices'])):
            raise ValueError('invalid source/resource inventory')
    if sum(p.endswith('.java') for p in lock['files']) != 1726:
        raise ValueError('complete examples and core sources required')


def snapshot(source, lock):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], timeout=30)
    if git('rev-parse', 'HEAD').decode().strip() != REVISION:
        raise ValueError('incorrect official source revision')
    tracked = set(git('ls-tree', '-r', '--name-only', REVISION, 'src').decode().splitlines())
    if tracked != {p for p in lock['files'] if p.startswith('src/')}:
        raise ValueError('complete upstream source/resource inventory changed')
    if git('ls-files', '--others', '--exclude-standard', '--', 'src').strip():
        raise ValueError('untracked consumed source/resource files')
    data = {}
    for p, sha in sorted(lock['files'].items()):
        target = source / p
        if target.is_symlink() or not target.is_file() or digest(target) != sha:
            raise ValueError('source/resource integrity mismatch: ' + p)
        data[p] = target.read_bytes()
    return data


def write_jar(path, entries):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as jar:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            jar.writestr(info, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--public-jars', type=Path, required=True)
    parser.add_argument('--gis-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate(lock)
    data = snapshot(args.source.resolve(), lock)
    # Reuse the foundation validator: source receipt, toolchain/input key,
    # complete output hashes and the reviewed compiled GIS class inventory.
    spec = importlib.util.spec_from_file_location('kernel_recipe', REPO / 'takx/kernel-java/build.py')
    kernel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kernel)
    gis, gis_receipt = kernel.verified_gis(args.gis_build.resolve(), lock)
    jars = [p for p, _ in gis if p.name == 'gdal-2.4.4-mod-java.jar']
    for name, expected in sorted(lock['public_jars'].items()):
        p = args.public_jars.resolve() / name
        if not p.is_file() or p.stat().st_size != expected['bytes'] or digest(p) != expected['sha256']:
            raise ValueError('public Java dependency integrity mismatch: ' + name)
        jars.append(p)
    version = subprocess.check_output(['javac', '-version'], stderr=subprocess.STDOUT).decode().strip()
    if not version.startswith('javac 17.'):
        raise ValueError('JDK 17 required')
    out = args.output.resolve()
    if out.exists():
        raise ValueError('output must be a new directory')
    out.mkdir(parents=True)
    src = out / 'source'
    for p, value in data.items():
        target = src / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    subprocess.run(['git', 'apply', '--check', str(HERE / 'standard-gdal.patch')], cwd=src, check=True)
    subprocess.run(['git', 'apply', str(HERE / 'standard-gdal.patch')], cwd=src, check=True)
    helper = src / 'src/gov/nasa/worldwind/util/gdal/ProjectPaletteColorModel.java'
    shutil.copyfile(HERE / helper.name, helper)
    classes = out / 'classes'
    classes.mkdir()
    sources = sorted((src / p).relative_to(out).as_posix() for p in data if p.endswith('.java'))
    sources.append(helper.relative_to(out).as_posix())
    sources.sort()
    # Quoted javac response entries support paths containing spaces.
    (out / 'sources.args').write_text(''.join('"' + p + '"\n' for p in sources))
    command = ['javac', '-J-Xmx768m', '--release', '17', '-encoding', 'UTF-8', '-proc:none',
               '-Xmaxerrs', '100', '-cp', __import__('os').pathsep.join(map(str, jars)),
               '-d', 'classes', '@sources.args']
    inputs = {'lock': lock, 'recipe_sha256': digest(Path(__file__)), 'javac': version,
              'gis_receipt': gis_receipt, 'native_built_or_loaded': False,
              'artifact_identity': 'uds-takserver-worldwind-java',
              'dependency_hashes': {p.name: digest(p) for p in jars}}
    (out / 'build-inputs.json').write_text(json.dumps(inputs, indent=2, sort_keys=True) + '\n')
    result = subprocess.run(command, cwd=out, capture_output=True, timeout=240)
    (out / 'javac.stdout.log').write_bytes(result.stdout)
    (out / 'javac.stderr.log').write_bytes(result.stderr)
    state = {'exit_code': result.returncode, 'java_sources': len(sources),
             'compiled_classes': len(list(classes.rglob('*.class'))),
             'source_scope': {'upstream_total': 1726, 'upstream_unchanged': 1725,
                              'upstream_patched': 1, 'project_helpers': 1},
             'native_built_or_loaded': False,
             'inputs_sha256': digest(out / 'build-inputs.json'),
             'diagnostics_sha256': digest(out / 'javac.stderr.log')}
    if result.returncode == 0:
        entries = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob('*.class')}
        for p, value in data.items():
            if p.startswith('src/') and not p.endswith('.java'):
                entries[p[4:]] = value
            elif p in lock['notices']:
                entries['META-INF/upstream-notices/' + p] = value
        entries['META-INF/project-LICENSE.txt'] = (REPO / 'LICENSE').read_bytes()
        entries['META-INF/uds-takserver-worldwind-profile.json'] = json.dumps({
            'identity': 'uds-takserver-worldwind-java', 'profile': lock['profile'],
            'source_revision': REVISION, 'native_runtime_verified': False,
            'combined_variant_spdx': 'GPL-3.0-only',
            'upstream_licenses': 'META-INF/upstream-notices/',
            'project_inputs': lock['project_inputs']}, sort_keys=True).encode()
        artifact = out / 'uds-takserver-worldwind-java.jar'
        write_jar(artifact, entries)
        state['artifact'] = {'name': artifact.name, 'sha256': digest(artifact), 'entries': len(entries)}
    else:
        # Diagnostics remain inspectable; partial classes never become an artifact.
        shutil.rmtree(classes)
    (out / 'build-state.json').write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
