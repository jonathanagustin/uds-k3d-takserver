#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline finite affine Matrix vectors, independent math and real Java2D pixels."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory(prefix='takx-matrix-') as temporary:
        inputs = [HERE / 'src/main/java/android/graphics' / (name + '.java')
                  for name in ['Matrix', 'RectF']]
        inputs.append(HERE / 'src/test/java/matrix/MatrixCompatibilityTest.java')
        subprocess.run(['javac', '--release', '11', '-proc:none', '-encoding', 'UTF-8',
                        '-d', temporary, *map(str, inputs)], check=True, timeout=30)
        subprocess.run(['java', '-Djava.awt.headless=true', '-cp', temporary,
                        'android.graphics.MatrixCompatibilityTest'], check=True, timeout=30)


if __name__ == '__main__':
    main()
