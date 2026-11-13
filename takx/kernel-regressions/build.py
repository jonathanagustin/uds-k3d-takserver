#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Consume a reviewed real SDK proof; never acquire sources, build native code or run by default."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'
FLOOR = 2 * 1024**3
CAP = 256 * 1024**2
RECEIPT = 256 * 1024

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()

def safe(name):
    require(type(name) is str, 'unsafe SDK inventory path')
    path = PurePosixPath(name)
    require(str(path) == name and not path.is_absolute() and
            '..' not in path.parts and '\\' not in name, 'unsafe SDK inventory path')
    return name

def allocated(root):
    seen = set()
    total = 0
    if not root.exists():
        return 0
    for path in [root, *root.rglob('*')]:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue  # Observing an already-retired compiler temporary, not admitting an input.
        identity = info.st_dev, info.st_ino
        if identity not in seen:
            seen.add(identity)
            total += info.st_blocks * 512
    return total

def reserve_output(parent, cap):
    # Reserve the actual output filesystem; a separate executable tmpfs must
    # not consume or waive the retained workspace's physical free floor.
    require(shutil.disk_usage('/workspace').free >= FLOOR + RECEIPT, 'physical free floor')
    shared = parent.stat().st_dev == Path('/workspace').stat().st_dev
    require(shutil.disk_usage(parent).free >= cap + (FLOOR if shared else 0), 'full phase reservation required')

def inspect(proof, expected):
    require(re.fullmatch(r'[0-9a-f]{64}', expected) and sha(proof / 'complete.json') == expected,
            'reviewed SDK proof hash required')
    receipt = json.loads((proof / 'complete.json').read_text())
    require(receipt.get('component_runtime_acceptance') is True and
            receipt.get('stock_resource_loader_controls_passed') is True and
            receipt.get('runtime_resource_consumers_passed') is True,
            'resource-complete genuine SDK runtime qualification required')
    manifest = receipt['manifest']
    require(manifest['official_revision'] == REVISION and manifest['version'] == '8.30.5',
            'different upstream SDK revision/version')
    package = proof / 'package'
    inventory = receipt['package_inventory']
    for name, entry in inventory.items():
        path = package / safe(name)
        require(path.is_file() and not path.is_symlink() and
                path.resolve().is_relative_to(package.resolve()), 'SDK input must be regular and owned')
        require(path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], 'SDK inventory drift')
    artifact = package / 'kernel-8.30.5-linux-amd64-public-cpu.jar'
    require(artifact.relative_to(package).as_posix() in inventory, 'missing reviewed component')
    dependencies = []
    for dependency in manifest['dependencies']:
        path = package / safe(dependency['path'])
        require(sha(path) == dependency['sha256'], 'dependency differs')
        dependencies.append(path)
    for entry in receipt['jdk_tools'].values():
        require(sha(entry['path']) == entry['sha256'], 'qualified JDK differs')
    hosts = {}
    for phase in receipt['runtime'].values():
        for path, digest in phase['mapped_elfs'].items():
            if path.startswith('/usr/lib/') or path.startswith(str(Path(receipt['jdk_tools']['java']['path']).parent.parent / 'lib') + '/'):
                require(path not in hosts or hosts[path] == digest, 'conflicting host identity')
                hosts[path] = digest
    return receipt, artifact, dependencies, hosts

def verify_maps(text, library_path, native, hosts):
    actual = {}
    for line in text.splitlines():
        if not line.startswith('ELF '):
            continue
        fields = line.split(' ', 2)
        require(len(fields) == 3 and re.fullmatch(r'[0-9a-f]{64}', fields[1]), 'invalid map record')
        path = Path(fields[2])
        require(path.is_file() and not path.is_symlink() and path.resolve() == path, 'noncanonical mapped ELF')
        require(str(path) not in actual and sha(path) == fields[1], 'mapped ELF changed/duplicated')
        require(not path.name.startswith(('libcrypto.so', 'libssl.so', 'libsqlite3.so')), 'shared backend rejected')
        if path.parent == library_path:
            require(native.get(path.name) == fields[1], 'unapproved packaged provider')
        else:
            require(hosts.get(str(path)) == fields[1], 'unapproved host or original provider')
        actual[str(path)] = fields[1]
    require(actual, 'missing real ELF maps')
    for name, digest in native.items():
        require(actual.get(str(library_path / name)) == digest, 'packaged provider absent')
    return actual

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-proof', type=Path, required=True)
    parser.add_argument('--sdk-proof-sha256', required=True)
    parser.add_argument('--phase', choices=('inspect', 'compile', 'qualify'), default='inspect')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    proof = args.sdk_proof.resolve()
    receipt, artifact, dependencies, hosts = inspect(proof, args.sdk_proof_sha256)
    if args.phase == 'inspect':
        print('Reviewed resource-complete SDK inputs verified; no compiler or JVM launched')
        return
    require(args.output is not None, 'explicit fresh output required')
    out = args.output.absolute()
    require(not out.exists() and not out.is_symlink() and not out.is_relative_to(proof) and
            not proof.is_relative_to(out) and not out.is_relative_to(HERE.parent), 'fresh disjoint output required')
    cap = CAP if args.phase == 'qualify' else 2 * 1024**2
    reserve_output(out.parent, cap)
    controls = HERE.parent / 'kernel-native'
    sources = sorted((HERE / 'java').glob('*.java')) + [controls / name for name in (
        'KernelRuntimeSmoke.java', 'NativeDatabaseCandidate.java', 'KernelThrowingLoggerCandidate.java')]
    inputs = {str(path): sha(path) for path in [Path(__file__).resolve(), HERE / 'upstream.lock.json', *sources]}
    out.mkdir(mode=0o700)
    for name in ('classes', 'tmp', 'home', 'data', 'evidence'):
        (out / name).mkdir()
    commands = []
    failure = None
    maps = None
    categories = {}
    def gate():
        require(allocated(out) + RECEIPT <= cap, 'inclusive output/receipt cap')
        require(shutil.disk_usage('/workspace').free >= FLOOR + RECEIPT, 'physical free floor')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('LD_', 'JAVA_', 'JDK_', 'CCACHE_', 'GDAL_', 'CPL_', 'PROJ_')) and key not in
           ('_JAVA_OPTIONS', 'CLASSPATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY')}
    env.update(TMPDIR=str(out / 'tmp'), LC_ALL='C.UTF-8')
    def run(argv, label, allow_tool_failure=False):
        log = out / 'evidence' / (label + '.log')
        started = time.monotonic()
        def limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (192 * 1024**2, 192 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        content = bytearray()
        truncated = False
        with log.open('xb') as stream:
            child = subprocess.Popen(list(map(str, argv)), cwd=out, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True, preexec_fn=limits)
            selector = selectors.DefaultSelector()
            selector.register(child.stdout, selectors.EVENT_READ)
            try:
                while selector.get_map() or child.poll() is None:
                    gate()
                    require(time.monotonic() - started < 120, 'child deadline')
                    for key, _ in selector.select(.05):
                        block = os.read(key.fileobj.fileno(), 32768)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = 128 * 1024 - len(content)
                        piece = block[:remaining]
                        require(allocated(out) + RECEIPT + len(piece) + 4096 <= cap, 'log allocation reserve')
                        require(shutil.disk_usage('/workspace').free >= FLOOR + RECEIPT + len(piece) + 4096, 'log free-floor reserve')
                        stream.write(piece)
                        stream.flush()
                        content.extend(piece)
                        if len(piece) != len(block):
                            truncated = True
                            raise ValueError('log bound exceeded; bounded prefix preserved')
                child.wait()
            except BaseException:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                raise
            finally:
                selector.close()
                child.stdout.close()
                commands.append({'argv': list(map(str, argv)), 'exit': child.returncode,
                                 'seconds': time.monotonic() - started, 'log_prefix_truncated': truncated})
        require(not truncated, 'complete child stream required')
        require(allow_tool_failure or child.returncode == 0, 'first tool failure: ' + label)
        gate()
        return content.decode('utf-8', errors='strict')
    try:
        cp = os.pathsep.join(map(str, [artifact, *dependencies]))
        run([receipt['jdk_tools']['javac']['path'], '-J-Xmx256m', '--release', '17', '-proc:none', '-implicit:none',
             '-sourcepath', '', '-cp', cp, '-d', out / 'classes', *sources], 'compile')
        for path in (out / 'classes').rglob('*.class'):
            require(re.fullmatch(r'(KernelFormatRegressions|KernelRegressionSmoke|KernelRuntimeSmoke|NativeDatabaseCandidate|KernelThrowingLoggerCandidate)(?:\$[A-Za-z0-9_]+)?\.class', path.relative_to(out / 'classes').as_posix()),
                    'no SDK replacement class permitted')
        if args.phase == 'qualify':
            # Same genuine resource-loader startup path as the reviewed SDK qualification.
            library_path = out / 'tmp/takkernel/engine' / hashlib.md5(artifact.read_bytes()).hexdigest() / 'lib/linux64'
            maps = {}
            for category in ('dted', 'mbtiles', 'geopackage', 'kml', 'elevation', 'obj'):
                text = run([receipt['jdk_tools']['java']['path'], '-Xcheck:jni', '-Xmx256m', '-XX:ActiveProcessorCount=2',
                            '-Djava.awt.headless=true', '-Djava.library.path=' + str(library_path),
                            '-Djava.io.tmpdir=' + str(out / 'tmp'), '-Duser.home=' + str(out / 'home'),
                            '-DTAK_APP_DATA_PATH=' + str(out / 'data'), '-cp', str(out / 'classes') + os.pathsep + cp,
                            'KernelRegressionSmoke', artifact, out / 'fixtures' / category, category],
                           'regressions-' + category, allow_tool_failure=True)
                diagnostics = any(marker in text for marker in ('WARNING in native method', 'WARNING: JNI', 'FATAL ERROR',
                    'UnsatisfiedLinkError', 'NoClassDefFoundError', 'EngineLibrary: Failed to load'))
                passed = (commands[-1]['exit'] == 0 and not diagnostics and
                          'PASS_REAL_FORMAT_CATEGORY name=' + category + ' ' in text and
                          'PASS_REAL_KERNEL_FORMAT_REGRESSIONS_NO_RENDERER_OR_FULL_CLIENT_CLAIM' in text)
                categories[category] = {'exit': commands[-1]['exit'], 'jni_and_startup_diagnostics_free': not diagnostics,
                                        'qualified': False, 'assertions_completed':
                                        'PASS_REAL_FORMAT_CATEGORY name=' + category + ' ' in text}
                if passed:
                    maps[category] = verify_maps(text, library_path, receipt['manifest']['native_resources'], hosts)
                    categories[category]['qualified'] = True
                else:
                    failure = failure or 'format category failed assertions or strict JNI/startup gate: ' + category
                # Recheck identities and budget before the next independent JVM.
                gate()
                inspect(proof, args.sdk_proof_sha256)
    except BaseException as error:
        failure = failure or repr(error)
    finally:
        changed = [path for path, digest in inputs.items() if sha(path) != digest]
        try:
            inspect(proof, args.sdk_proof_sha256)
        except BaseException as error:
            failure = failure or repr(error)
        failure = failure or ('changed bound sources' if changed else None)
        result = {'status': 'PASS ' + args.phase if failure is None else 'FAILED first attempt', 'failure': failure,
                  'sdk_proof_sha256': args.sdk_proof_sha256, 'phase': args.phase, 'output_cap_bytes': cap, 'commands': commands,
                  'inputs': inputs, 'changed_inputs': changed, 'mapped_elfs': maps,
                  'output_inventory': {str(path.relative_to(out)): sha(path) for path in out.rglob('*') if path.is_file()},
                  'category_outcomes': categories,
                  'upstream_regression_scope': ['DTED filename discovery only', 'MBTiles default SPI byte roundtrips', 'GeoPackage float gridded coverage',
                      'KML point style parsing', 'GDAL analytic constant elevation sampling', 'two authored CPU OBJ tetrahedron imports'],
                  'qualified_format_categories': [category for category, outcome in categories.items() if outcome['qualified']],
                  'KML_elevation_sampling_3D_renderer_or_full_client_qualified': False}
        data = (json.dumps(result, indent=2) + '\n').encode()
        require(len(data) + 16384 < RECEIPT, 'receipt reserve')
        (out / 'complete.json').write_bytes(data)
        for path in out.rglob('*'):
            if path.is_file():
                path.chmod(0o444)
        print(result['status'], failure)
    if failure:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
