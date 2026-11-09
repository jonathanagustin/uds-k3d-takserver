#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline Base64 contracts against the exact public AOSP source oracle."""
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
                        help='Decoded Base64.java from the locked official AOSP URL')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'base64-source.lock.json').read_text())
    original = args.aosp_source.read_bytes()
    if hashlib.sha256(original).hexdigest() != lock['sha256']:
        parser.error('AOSP source SHA256 mismatch; the exact reviewed source is required')
    adapted = original.decode().replace('import android.compat.annotation.UnsupportedAppUsage;\n', '')
    adapted = adapted.replace('    @UnsupportedAppUsage\n', '')
    oracle_source = adapted
    adapted = adapted.replace('str.getBytes()', 'str.getBytes(java.nio.charset.StandardCharsets.UTF_8)')
    implementation = ROOT / 'src/main/java/android/util/Base64.java'
    local = implementation.read_text()
    marker = '/*\n * Copyright (C) 2010 The Android Open Source Project'
    if marker not in local or local[local.index(marker):] != adapted:
        parser.error('Base64 differs from the reviewed desktop AOSP adaptation')
    test = ROOT / 'src/test/java/base64/Base64CompatibilityTest.java'
    with tempfile.TemporaryDirectory(prefix='takx-base64-') as temporary:
        build = Path(temporary)
        oracle = build / 'oracle/android/util/Base64.java'
        oracle.parent.mkdir(parents=True)
        oracle.write_text(oracle_source.replace('package android.util;', 'package oracle.android.util;', 1))
        oracle_test = build / 'oraclebase64/Base64CompatibilityTest.java'
        oracle_test.parent.mkdir(parents=True)
        oracle_test.write_text(test.read_text().replace('package base64;', 'package oraclebase64;', 1)
                               .replace('import android.util.Base64;', 'import oracle.android.util.Base64;', 1))
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
                        '-d', str(build / 'classes'), str(implementation), str(test),
                        str(oracle), str(oracle_test)], check=True, timeout=30)
        outputs = []
        for main_class in ['base64.Base64CompatibilityTest', 'oraclebase64.Base64CompatibilityTest']:
            result = subprocess.run(['java', '-Dfile.encoding=ISO-2022-JP' if main_class.startswith('base64.') else '-Dfile.encoding=UTF-8', '-cp', str(build / 'classes'), main_class], check=True, timeout=30, capture_output=True, text=True)
            outputs.append(result.stdout)
            print(result.stdout, end='')
        if outputs[0] != outputs[1]:
            raise AssertionError('Android source oracle differs on flags/range outcomes')


if __name__ == '__main__':
    main()
