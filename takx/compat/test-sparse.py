#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline sparse-container contracts with locked AOSP source comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
NOTICE = '// Copyright 2026 uds-takserver authors\n// SPDX-License-Identifier: Apache-2.0\n// Desktop adaptation of pinned AOSP Android 14; see SPARSE-ARRAYS.md.\n'


def normalize(name, text):
    text = '\n'.join(line for line in text.split('\n') if not line.startswith((
        'import android.', 'import com.android.', 'import libcore.'))
        and not line.strip().startswith('@UnsupportedAppUsage'))
    text = text.replace('@Nullable ', '').replace(' && UtilConfig.sThrowExceptionForUpperArrayOutOfBounds', '')
    text = text.replace('EmptyArray.INT', 'new int[0]').replace('EmptyArray.OBJECT', 'new Object[0]').replace('EmptyArray.BOOLEAN', 'new boolean[0]')
    text = text.replace('ArrayUtils.newUnpaddedObjectArray(initialCapacity)', 'new Object[initialCapacity]').replace('ArrayUtils.newUnpaddedIntArray(initialCapacity)', 'new int[initialCapacity]')
    text = text.replace('ContainerHelpers.binarySearch(mKeys, mSize, key)', 'java.util.Arrays.binarySearch(mKeys, 0, mSize, key)')
    text = text.replace('GrowingArrayUtils', 'SparseArrayStorage')
    if name == 'GrowingArrayUtils':
        text = text.replace('package com.android.internal.util;', 'package android.util;').replace('public final class SparseArrayStorage', 'final class SparseArrayStorage')
        for primitive in ['Int', 'Long', 'Boolean', 'Float']:
            text = text.replace(f'ArrayUtils.newUnpadded{primitive}Array(growSize(currentSize))', f'new {primitive.lower()}[growSize(currentSize)]')
        text = text.replace('ArrayUtils.newUnpaddedArray(', 'newArray(')
        text = text.replace('    private SparseArrayStorage() {}', '    @SuppressWarnings("unchecked")\n    private static <T> T[] newArray(Class<T> type, int size) {\n        return (T[]) java.lang.reflect.Array.newInstance(type, size);\n    }\n\n    private SparseArrayStorage() {}')
    return text.replace('re-used', 'reused')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aosp-dir', type=Path, required=True,
                        help='Directory containing the three exact locked official Java sources')
    args = parser.parse_args()
    lock = json.loads((HERE / 'sparse-source.lock.json').read_text())
    with tempfile.TemporaryDirectory(prefix='takx-sparse-') as temporary:
        work = Path(temporary)
        sources = []
        for name, entry in lock['sources'].items():
            original = (args.aosp_dir / (name + '.java')).read_bytes()
            if hashlib.sha256(original).hexdigest() != entry['sha256']:
                parser.error('AOSP source SHA256 mismatch: ' + name)
            adapted = normalize(name, original.decode())
            target = 'SparseArrayStorage' if name == 'GrowingArrayUtils' else name
            local = HERE / 'src/main/java/android/util' / (target + '.java')
            if local.read_text() != NOTICE + adapted:
                parser.error('Sparse adapter differs from reviewed AOSP normalization: ' + target)
            oracle = work / 'oracle/android/util' / (target + '.java')
            oracle.parent.mkdir(parents=True, exist_ok=True)
            oracle.write_text(adapted.replace('package android.util;', 'package oracle.android.util;', 1))
            sources += [str(local), str(oracle)]
        test = HERE / 'src/test/java/sparse/SparseCompatibilityTest.java'
        oracle_test = work / 'oraclesparse/SparseCompatibilityTest.java'
        oracle_test.parent.mkdir()
        oracle_test.write_text(test.read_text().replace('package sparse;', 'package oraclesparse;', 1)
                               .replace('import android.util.', 'import oracle.android.util.'))
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none', '-d', str(work / 'classes'),
                        *sources, str(test), str(oracle_test)], check=True, timeout=30)
        for main_class in ('sparse.SparseCompatibilityTest', 'oraclesparse.SparseCompatibilityTest'):
            subprocess.run(['java', '-ea', '-cp', str(work / 'classes'), main_class], check=True, timeout=30)


if __name__ == '__main__':
    main()
