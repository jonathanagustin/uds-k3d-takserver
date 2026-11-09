#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline concrete Context IO checks with real accepted Uri/Parcel prerequisites."""
import argparse
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--support-root', type=Path, default=HERE,
                        help='Compatibility source root containing accepted android.net.Uri and Parcel')
    args = parser.parse_args()
    support = args.support_root.resolve()
    required = [support / 'src/main/java/android/net/Uri.java',
                support / 'src/main/java/android/os/Parcel.java',
                support / 'src/main/java/android/os/Parcelable.java']
    if not all(path.is_file() for path in required):
        parser.error('Real Uri/Parcel prerequisite sources are required; no stubs are supplied')
    inputs = []
    for package in ['android/content', 'android/content/res', 'android/content/pm', 'android/preference']:
        inputs += sorted((HERE / 'src/main/java' / package).glob('*.java'))
    inputs += sorted((support / 'src/main/java/android/net').glob('*.java'))
    inputs += required[1:]
    inputs += [HERE / 'src/test/java/DesktopContextTest.java', HERE / 'src/test/java/context/ContextIoTest.java']
    with tempfile.TemporaryDirectory(prefix='takx-context-io-') as directory:
        root = Path(directory)
        classes = root / 'classes'
        subprocess.run(['javac', '--release', '11', '-Xlint:all', '-proc:none', '-encoding', 'UTF-8',
                        '-d', str(classes), *map(str, inputs)], check=True, timeout=30)
        subprocess.run(['java', '-ea', '-cp', str(classes), 'DesktopContextTest'], check=True, timeout=30)
        fixtures = root / 'fixtures'
        fixtures.mkdir()
        subprocess.run(['java', '-ea', '-cp', str(classes), 'context.ContextIoTest', str(fixtures)], check=True, timeout=30)


if __name__ == '__main__':
    main()
