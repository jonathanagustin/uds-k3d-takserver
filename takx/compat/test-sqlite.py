#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run actual SQLite JNI and unchanged pinned public database adapter consumers."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--classpath-dir', type=Path, required=True, help='The locked public port JARs')
    parser.add_argument('--backend', type=Path, required=True, help='Verified opt-in sqlite-jdbc source recipe prefix')
    parser.add_argument('--cache', type=Path, required=True, help='The verified source recipe cache; offline reuse only')
    parser.add_argument('--recipe', type=Path, default=ROOT / 'takx/sqlite-jdbc/build.py')
    args = parser.parse_args()
    source, backend = args.source.resolve(), args.backend.resolve()
    jars = []
    lock = json.loads((ROOT / 'takx/compat/port-classpath.lock.json').read_text())
    for name, entry in lock.items():
        jar = args.classpath_dir.resolve() / name
        if not jar.is_file() or digest(jar) != entry['sha256']:
            parser.error('Missing or mismatched locked classpath input: ' + name)
        jars.append(str(jar))
    receipt = json.loads((backend / 'complete.json').read_text())
    expected = {'sqlite-jdbc-host-source.jar', 'native/libsqlitejdbc.so', 'slf4j-api.jar'}
    if set(receipt['artifacts']) != expected:
        parser.error('unexpected backend artifact inventory')
    for name, checksum in receipt['artifacts'].items():
        path = backend / name
        if path.is_symlink() or digest(path) != checksum:
            parser.error('backend artifact hash mismatch')
    if receipt.get('identity', {}).get('schema') != 1 or receipt['identity'].get('target') != 'Linux-x86_64':
        parser.error('unreviewed backend receipt target/schema')
    for name, checksum in receipt['runtime_closure'].items():
        if digest(Path(name)) != checksum:
            parser.error('native runtime dependency changed')
    java_home = Path(os.environ.get('JAVA_HOME') or Path(shutil.which('javac')).resolve().parent.parent)
    subprocess.run([str(java_home / 'bin/java'), '-version'], check=True)
    subprocess.run(['python3', str(args.recipe), '--output', str(backend), '--cache', str(args.cache.resolve()),
                    '--java-home', str(java_home), '--offline'], check=True, timeout=90)
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        parser.error('pinned official source revision required')
    base = 'takkernel/engine/src/main/java/com/atakmap/database/'
    files = [base + name + '.java' for name in ('RowIterator', 'Bindable', 'CursorIface', 'StatementIface', 'QueryIface', 'DatabaseIface')]
    files += [base + 'android/' + name + '.java' for name in ('AndroidStatementAdapter', 'AndroidQueryStatement', 'AndroidCursorAdapter', 'BindArgument', 'CursorIfaceAdapter')]
    annotations = 'takkernel/annotation/src/main/java'
    subprocess.run(['git', '-C', str(source), 'diff', '--exit-code', 'HEAD', '--', *files, annotations], check=True)
    files += subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-r', '--name-only', REVISION, '--', annotations], text=True).splitlines()
    with tempfile.TemporaryDirectory(prefix='desktop-sqlite-test-') as temporary:
        build = Path(temporary)
        inputs = []
        for name in files:
            target = build / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(['git', '-C', str(source), 'show', REVISION + ':' + name]))
            inputs.append(str(target))
        inputs += [str(p) for p in sorted((ROOT / 'takx/compat/src/main/java').rglob('*.java'))]
        inputs.append(str(ROOT / 'takx/compat/src/test/java/com/atakmap/database/android/DesktopSQLiteTest.java'))
        classes = build / 'classes'
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none', '-cp', os.pathsep.join(jars), '-d', str(classes), *inputs], check=True, timeout=60)
        classpath = os.pathsep.join([str(classes), str(backend / 'sqlite-jdbc-host-source.jar'), str(backend / 'slf4j-api.jar'), *jars])
        subprocess.run(['java', '-Djava.awt.headless=true', '-Dorg.sqlite.lib.path=' + str(backend / 'native'),
                        '-Dorg.sqlite.lib.name=libsqlitejdbc.so', '-Djava.library.path=' + str(backend / 'native'),
                        '-cp', classpath, 'com.atakmap.database.android.DesktopSQLiteTest'], check=True, timeout=60)
    for name, checksum in receipt['artifacts'].items():
        if digest(backend / name) != checksum:
            parser.error('backend changed during the test')


if __name__ == '__main__':
    main()
