#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Check final graphics/Unix APIs and optionally the frozen, unchanged Kernel VSI handler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_rdev, stat.st_uid, stat.st_gid]


def kernel_classpath(parser, proof):
    inputs = json.loads((proof / 'inputs.json').read_text())
    result = json.loads((proof / 'result.json').read_text())
    if inputs.get('upstream_revision') != REVISION or result.get('exit_code') != 0:
        parser.error('successful pinned frozen Kernel compilation required')
    adapters = set()
    upstream = set()
    for item in inputs['sources']:
        path = Path(item['path'])
        if digest(path) != item['sha256']:
            parser.error('frozen source changed: ' + str(path))
        relative = path.relative_to(proof / 'stage')
        if relative.parts[0] == 'compat':
            local = HERE / 'src/main/java' / Path(*relative.parts[1:])
            if digest(local) != item['sha256']:
                parser.error('adapter changed since frozen compile: ' + str(local))
            adapters.add(local)
        else:
            upstream.add(path)
    if adapters != set((HERE / 'src/main/java').rglob('*.java')):
        parser.error('frozen adapter inventory differs')
    if not any(str(p).endswith('/com/atakmap/map/gdal/VSIFileFileSystemHandler.java') for p in upstream):
        parser.error('unchanged VSI handler absent from frozen source inventory')
    jars = []
    for item in inputs['classpath']:
        path = Path(item['path'])
        if digest(path) != item['sha256']:
            parser.error('frozen classpath changed: ' + str(path))
        jars.append(str(path))
    return os.pathsep.join([str(proof / 'classes'), *jars])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True, help='external files from final-api-sources.lock.json')
    parser.add_argument('--kernel-proof', type=Path, help='fresh complete frozen compile with inputs/result/classes; no substituted upstream classes')
    args = parser.parse_args()
    lock = json.loads((HERE / 'final-api-sources.lock.json').read_text())
    for name, entry in lock['sources'].items():
        if digest(args.source_dir / name) != entry['sha256']:
            parser.error('source pin mismatch: ' + name)
    if os.name != 'posix':
        parser.error('Unix stat tests require a real Unix filesystem')
    cp = kernel_classpath(parser, args.kernel_proof.resolve()) if args.kernel_proof else None
    with tempfile.TemporaryDirectory(prefix='takx-final-apis-') as directory:
        work = Path(directory)
        fixtures = work / 'fixtures'; fixtures.mkdir()
        file = fixtures / 'file'; file.write_bytes(b'actual Unix metadata')
        (fixtures / 'directory').mkdir()
        (fixtures / 'symlink').symlink_to(file)
        os.link(file, fixtures / 'hardlink')
        (fixtures / 'dangling').symlink_to(fixtures / 'missing')
        (fixtures / 'loop').symlink_to('loop')
        denied = fixtures / 'denied'; denied.mkdir(); (denied / 'child').write_bytes(b'permission check')
        permission_test = os.geteuid() != 0
        if permission_test:
            denied.chmod(0)
        candidates = [file, fixtures / 'directory', fixtures / 'symlink', fixtures / 'hardlink', Path('/dev/null')]
        manifest = work / 'stat.tsv'
        manifest.write_text(''.join(str(p) + '\t' + '\t'.join(map(str, identity(p))) + '\n' for p in candidates))
        tests = [HERE / 'src/test/java/android/graphics/FinalGraphicsApiTest.java', HERE / 'src/test/java/android/system/UnixStatTest.java']
        classes = work / 'classes'
        try:
            subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none', '-sourcepath', str(HERE / 'src/main/java'),
                            '-d', str(classes), *map(str, tests)], check=True, timeout=60)
            subprocess.run(['java', '-Djava.awt.headless=true', '-cp', str(classes), 'android.graphics.FinalGraphicsApiTest'], check=True, timeout=30)
            subprocess.run(['java', '-cp', str(classes), 'android.system.UnixStatTest', str(manifest), str(fixtures), str(permission_test).lower()], check=True, timeout=30)
            if cp:
                test = HERE / 'src/test/java/com/atakmap/map/gdal/VsiFileHandlerTest.java'
                subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none', '-cp', cp, '-d', str(classes), str(test)], check=True, timeout=30)
                mount = work / 'mount'; (mount / 'atak').mkdir(parents=True)
                template = mount / 'atak/.stat'; template.touch()
                (mount / 'template-stat.txt').write_text(' '.join(map(str, identity(template))))
                (mount / 'payload').write_bytes(bytes(i % 256 for i in range(4097)))
                (mount / 'payload-link').symlink_to(mount / 'payload')
                # Frozen classes go first: the integration uses the exact adapter
                # and upstream classes produced by the complete compile proof.
                subprocess.run(['java', '-Djava.awt.headless=true', '-cp', cp + os.pathsep + str(classes),
                                'com.atakmap.map.gdal.VsiFileHandlerTest', str(mount)], check=True, timeout=30)
            else:
                print('Kernel VSI integration: NOT RUN (supply --kernel-proof)')
        finally:
            denied.chmod(0o700)


if __name__ == '__main__':
    main()
