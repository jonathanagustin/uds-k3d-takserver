#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline LruCache contracts against the exact public AOSP source oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aosp-source', type=Path, required=True,
                        help='Decoded LruCache.java from the locked official AOSP URL')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'lru-source.lock.json').read_text())
    original = args.aosp_source.read_bytes()
    if hashlib.sha256(original).hexdigest() != lock['sha256']:
        parser.error('AOSP source SHA256 mismatch; the exact reviewed source is required')
    adapted = original.decode().replace('import android.compat.annotation.UnsupportedAppUsage;\n', '')
    adapted = adapted.replace('    @UnsupportedAppUsage\n', '')
    adapted = adapted.replace('map.eldest()', '(map.isEmpty() ? null : map.entrySet().iterator().next())')
    implementation = ROOT / 'src/main/java/android/util/LruCache.java'
    local = implementation.read_text()
    marker = '/*\n * Copyright (C) 2011 The Android Open Source Project'
    if marker not in local or local[local.index(marker):] != adapted:
        parser.error('LruCache differs from the reviewed reviewed desktop AOSP adaptation')
    test = ROOT / 'src/test/java/cache/LruCacheCompatibilityTest.java'
    with tempfile.TemporaryDirectory(prefix='takx-lru-') as temporary:
        build = Path(temporary)
        oracle = build / 'oracle/android/util/LruCache.java'
        oracle.parent.mkdir(parents=True)
        oracle.write_text(adapted.replace('package android.util;', 'package oracle.android.util;', 1))
        oracle_test = build / 'oraclecache/LruCacheCompatibilityTest.java'
        oracle_test.parent.mkdir(parents=True)
        oracle_test.write_text(test.read_text().replace('package cache;', 'package oraclecache;', 1)
                               .replace('import android.util.LruCache;', 'import oracle.android.util.LruCache;', 1))
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
                        '-d', str(build / 'classes'), str(implementation), str(test),
                        str(oracle), str(oracle_test)], check=True, timeout=30)
        for main_class in ['cache.LruCacheCompatibilityTest', 'oraclecache.LruCacheCompatibilityTest']:
            subprocess.run(['java', '-cp', str(build / 'classes'), main_class], check=True, timeout=30)


if __name__ == '__main__':
    main()
