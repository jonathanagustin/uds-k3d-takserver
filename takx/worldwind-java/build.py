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


def interop_contract():
    lock = json.loads((HERE / 'interop.lock.json').read_text())
    if (lock.get('schema') != 1 or lock.get('source_revision') != REVISION or
            lock.get('profile') != 'project-standard-gdal-rgb-interop' or
            digest(HERE / 'project-interop.patch') != lock.get('patch_sha256') or
            set(lock.get('files', {})) != {'src/gov/nasa/worldwind/render/PointPlacemark.java',
                'src/gov/nasa/worldwind/render/DrawContextImpl.java',
                'src/gov/nasa/worldwind/layers/GraticuleSupport.java',
                'src/gov/nasa/worldwind/util/tree/BasicTreeLayout.java'}):
        raise ValueError('interop profile integrity mismatch')
    return lock


def apply_interop(source, lock):
    for name, entry in lock['files'].items():
        if digest(source / name) != entry['before_sha256']:
            raise ValueError('interop source preimage mismatch')
    subprocess.run(['git', 'apply', '--check', str(HERE / 'project-interop.patch')], cwd=source,
                   check=True, capture_output=True, timeout=30)
    subprocess.run(['git', 'apply', str(HERE / 'project-interop.patch')], cwd=source,
                   check=True, capture_output=True, timeout=30)
    for name, entry in lock['files'].items():
        if digest(source / name) != entry['after_sha256']:
            raise ValueError('interop source postimage mismatch')


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


def compile_checked(command, out, dependency_hashes, state):
    """Retain bounded compiler failures and reject inputs changed during compilation."""
    try:
        result = subprocess.run(command, cwd=out, capture_output=True, timeout=240)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
        failure = None if code == 0 else 'javac failed'
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr = 124, error.stdout or b'', error.stderr or b''
        failure = 'javac timed out after 240 seconds'
    for path, expected in dependency_hashes.items():
        if not path.is_file() or digest(path) != expected:
            code, failure = 1, 'dependency changed during compilation: ' + path.name
            break
    (out / 'javac.stdout.log').write_bytes(stdout)
    (out / 'javac.stderr.log').write_bytes(stderr)
    state.update(exit_code=code, failure=failure,
                 compiled_classes=len(list((out / 'classes').rglob('*.class'))),
                 diagnostics_sha256=digest(out / 'javac.stderr.log'),
                 dependencies_rechecked=True)
    if code != 0:
        shutil.rmtree(out / 'classes', ignore_errors=True)
        (out / 'uds-takserver-worldwind-java.jar').unlink(missing_ok=True)
    (out / 'build-state.json').write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--public-jars', type=Path, required=True)
    parser.add_argument('--gis-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interop', action='store_true', help='Explicit project rendering/picking hooks; not the private TAKX artifact')
    args = parser.parse_args()
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    validate(lock)
    interop = interop_contract() if args.interop else None
    if interop:
        lock['profile'] = interop['profile']
        lock['project_inputs']['project-interop.patch'] = interop['patch_sha256']
        lock['interop'] = interop
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
    javac = Path(shutil.which('javac') or '').resolve()
    version = subprocess.check_output([str(javac), '-version'], stderr=subprocess.STDOUT).decode().strip()
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
    if interop:
        apply_interop(src, interop)
    helper = src / 'src/gov/nasa/worldwind/util/gdal/ProjectPaletteColorModel.java'
    shutil.copyfile(HERE / helper.name, helper)
    classes = out / 'classes'
    classes.mkdir()
    sources = sorted((src / p).relative_to(out).as_posix() for p in data if p.endswith('.java'))
    sources.append(helper.relative_to(out).as_posix())
    sources.sort()
    # Quoted javac response entries support paths containing spaces.
    (out / 'sources.args').write_text(''.join('"' + p + '"\n' for p in sources))
    command = [str(javac), '-J-Xmx768m', '--release', '17', '-encoding', 'UTF-8', '-proc:none',
               '-Xmaxerrs', '100', '-cp', __import__('os').pathsep.join(map(str, jars)),
               '-d', 'classes', '@sources.args']
    identity = 'uds-takserver-worldwind-java-interop' if interop else 'uds-takserver-worldwind-java'
    inputs = {'lock': lock, 'recipe_sha256': digest(Path(__file__)), 'javac': version,
              'javac_binary': {'path': str(javac), 'sha256': digest(javac)},
              'command': command,
              'gis_receipt': gis_receipt, 'native_built_or_loaded': False,
              'artifact_identity': identity,
              'dependency_hashes': {p.name: digest(p) for p in jars}}
    (out / 'build-inputs.json').write_text(json.dumps(inputs, indent=2, sort_keys=True) + '\n')
    state = {'java_sources': len(sources),
             'source_scope': {'upstream_total': 1726, 'upstream_unchanged': 1721 if interop else 1725,
                              'upstream_patched': 5 if interop else 1, 'project_helpers': 1},
             'native_built_or_loaded': False,
             'inputs_sha256': digest(out / 'build-inputs.json')}
    code = compile_checked(command, out, {p: inputs['dependency_hashes'][p.name] for p in jars}, state)
    if code == 0:
        entries = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob('*.class')}
        for p, value in data.items():
            if p.startswith('src/') and not p.endswith('.java'):
                entries[p[4:]] = value
            elif p in lock['notices']:
                entries['META-INF/upstream-notices/' + p] = value
        entries['META-INF/project-LICENSE.txt'] = (REPO / 'LICENSE').read_bytes()
        entries['META-INF/uds-takserver-worldwind-profile.json'] = json.dumps({
            'identity': identity, 'profile': lock['profile'],
            'source_revision': REVISION, 'native_runtime_verified': False,
            'combined_variant_spdx': 'GPL-3.0-only',
            'upstream_licenses': 'META-INF/upstream-notices/',
            'project_inputs': lock['project_inputs']}, sort_keys=True).encode()
        artifact = out / (identity + '.jar')
        write_jar(artifact, entries)
        state['artifact'] = {'name': artifact.name, 'sha256': digest(artifact), 'entries': len(entries)}
    (out / 'build-state.json').write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
