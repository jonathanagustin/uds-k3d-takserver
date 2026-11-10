#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Actual ImageIO region pixels plus locked Skia scalar sampling helpers."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def function(text, name):
    start = text.index('static inline int ' + name + '(')
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True,
                        help='External files named as in region-source.lock.json')
    args = parser.parse_args()
    lock = json.loads((HERE / 'region-source.lock.json').read_text())
    for name, item in lock['sources'].items():
        content = (args.source_dir / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            parser.error('locked source mismatch: ' + name)
    if (HERE / 'LICENSE-Skia-BSD.txt').read_bytes() != (args.source_dir / 'Skia-LICENSE').read_bytes():
        parser.error('Skia license differs from source')
    header = (args.source_dir / 'SkCodecPriv.h').read_text()
    with tempfile.TemporaryDirectory(prefix='takx-region-') as directory:
        work = Path(directory)
        (work / 'LICENSE').write_bytes((HERE / 'LICENSE-Skia-BSD.txt').read_bytes())
        cpp = work / 'sampling.cpp'
        cpp.write_text(header[:header.index('#ifndef')] + '#include <iostream>\n' +
                       function(header, 'get_scaled_dimension') + '\n' + function(header, 'get_start_coord') + '''
int main() {
    for (int dimension : {1,2,3,5,7,8,9,15,16,31}) {
        for (int requested : {-3,0,1,2,3,4,8,65}) {
            int sample = requested < 1 ? 1 : requested;
            int size = get_scaled_dimension(dimension, sample);
            int actual = dimension / size;
            std::cout << dimension << " " << requested << " " << size << " " << get_start_coord(actual) << "\\n";
        }
    }
}
''')
        executable = work / 'sampling'
        subprocess.run(['c++', '-std=c++11', str(cpp), '-o', str(executable)], check=True, timeout=30)
        oracle = work / 'sampling.txt'
        with oracle.open('w') as output:
            subprocess.run([str(executable)], stdout=output, check=True, timeout=10)
        sources = [HERE / 'src/main/java/android/graphics' / (name + '.java')
                   for name in ('Bitmap', 'BitmapEncoder', 'BitmapFactory', 'BitmapRegionDecoder', 'Rect')]
        test = HERE / 'src/test/java/region/RegionDecoderCompatibilityTest.java'
        # Sourcepath admits genuine Bitmap dependencies added by companion slices.
        subprocess.run(['javac', '--release', '11', '-encoding', 'UTF-8', '-proc:none',
                        '-sourcepath', str(HERE / 'src/main/java'), '-d', str(work / 'classes'),
                        *map(str, sources), str(test)], check=True, timeout=30)
        subprocess.run(['java', '-ea', '-Djava.awt.headless=true', '-cp', str(work / 'classes'),
                        'android.graphics.RegionDecoderCompatibilityTest', str(oracle)], check=True, timeout=30)


if __name__ == '__main__':
    main()
