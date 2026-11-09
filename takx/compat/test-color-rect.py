#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run color/rectangle primitives against actual pinned public source oracles, offline."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVISION = '9f6893dd657feacc35ec5de03dad721c2e44170e'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    source = parser.parse_args().source.resolve()
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        parser.error('the reviewed official source revision is required')
    files = [
        'takkernel/port/src/main/java/gov/tak/platform/graphics/Rect.java',
        'takkernel/port/src/main/java/gov/tak/platform/graphics/Color.java',
        'takkernel/port/src/jre/java/gov/tak/platform/graphics/Insets.java',
    ]
    annotations = 'takkernel/annotation/src/main/java'
    disposable = 'takkernel/port/src/main/java/gov/tak/api/util/Disposable.java'
    subprocess.run(['git', '-C', str(source), 'diff', '--exit-code', 'HEAD', '--', *files, annotations, disposable], check=True)
    # Export tracked bytes directly, avoiding unknown/untracked files in the checkout.
    tracked = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-r', '--name-only', REVISION, '--', annotations], text=True).splitlines()
    with tempfile.TemporaryDirectory(prefix='takx-color-rect-') as temporary:
        build = Path(temporary)
        inputs = []
        for name in files + tracked + [disposable]:
            target = build / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(['git', '-C', str(source), 'show', REVISION + ':' + name]))
            inputs.append(str(target))
        graphics = ROOT / 'takx/compat/src/main/java/android/graphics'
        inputs += [str(graphics / (name + '.java')) for name in ['Rect', 'Color']]
        inputs += [str(ROOT / 'takx/compat/src/test/java/geometry/ColorRectCompatibilityTest.java')]
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none', '-d', str(build / 'classes'), *inputs], check=True)
        subprocess.run(['java', '-Djava.awt.headless=true', '-cp', str(build / 'classes'), 'geometry.ColorRectCompatibilityTest'], check=True)


if __name__ == '__main__':
    main()
