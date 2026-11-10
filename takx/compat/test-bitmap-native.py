#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run real bitmap formats against pinned, extracted Skia integer math and raw goldens."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PINS = {
    'pipeline': '51b5251dfbff3d70ce85662b2bf805544084027220420afe8e209aa2de513bc6',
    'color_priv': 'a854daa9a74423529c6fe29ff0f4685906d738e2e7bce6408fa58041e0920ed0',
}


def function(source, signature):
    start = source.index(signature)
    end = source.index('}', start) + 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline', type=Path, required=True)
    parser.add_argument('--color-priv', type=Path, required=True)
    args = parser.parse_args()
    sources = {}
    for key, expected in PINS.items():
        data = getattr(args, key).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            parser.error('Skia source hash differs: ' + key)
        sources[key] = data.decode()
    pipeline, private = sources['pipeline'], sources['color_priv']
    macros = []
    for name in ['SK_RGBA_R32_SHIFT', 'SK_RGBA_G32_SHIFT', 'SK_RGBA_B32_SHIFT', 'SK_RGBA_A32_SHIFT']:
        macros.append(re.search(r'^#define\s+' + name + r'\s+[^\n]+', private, re.MULTILINE).group(0))
    oracle = re.match(r'/\*.*?\*/', pipeline, re.DOTALL).group(0) + '\n'
    oracle += re.match(r'/\*.*?\*/', private, re.DOTALL).group(0) + '\n'
    oracle += '#include <cstdint>\n#include <cstddef>\n#include <fstream>\n'
    # Scalar instantiation of the exact low-precision per-lane integer formulas;
    # all intermediates fit uint16_t for the tested 8-bit source values.
    oracle += '#define SI inline\nusing U16=unsigned;\nU16 min(U16 a,U16 b){return a<b?a:b;}\nvoid store(uint16_t* p,size_t tail,U16 x){if(tail)*p=uint16_t(x); }\n'
    oracle += '\n'.join(macros) + '\n'
    oracle += function(pipeline, 'SI void from_565(U16 rgb') + '\n'
    oracle += function(pipeline, 'SI void store_565_(') + '\n'
    oracle += r'''
void u32(std::ofstream& out, uint32_t x) { for(int n=24;n>=0;n-=8) out.put(char(x>>n)); }
int main(int argc,char** argv) {
    if(argc!=2) return 2;
    std::ofstream out(argv[1],std::ios::binary);
    for(unsigned pixel=0;pixel<65536;pixel++) {
        U16 r,g,b;
        from_565(pixel,&r,&g,&b);
        u32(out,0xff000000u|(r<<16)|(g<<8)|b);
    }
    uint32_t seed=0x5a17e;
    for(unsigned i=0;i<5000;i++) {
        seed=seed*1664525u+1013904223u;
        u32(out,seed);
        uint16_t packed=0;
        store_565_(&packed,1,(seed>>16)&255,(seed>>8)&255,seed&255);
        out.put(char(packed>>8));out.put(char(packed));
    }
    // Same unpremultiplied native RGBA byte order used by the real tile-reader probe.
    uint32_t rgba=(0xf2u<<SK_RGBA_R32_SHIFT)|(0xf3u<<SK_RGBA_G32_SHIFT)|
                  (0xf4u<<SK_RGBA_B32_SHIFT)|(0xf1u<<SK_RGBA_A32_SHIFT);
    for(unsigned i=0;i<4;i++) out.put(char(rgba>>(8*i)));
    return out.good()?0:1;
}
'''
    with tempfile.TemporaryDirectory(prefix='takx-native-bitmap-') as temporary:
        build = Path(temporary)
        (build / 'LICENSE').write_bytes((HERE / 'LICENSE-Skia-BSD.txt').read_bytes())
        (build / 'oracle.cpp').write_text(oracle)
        subprocess.run(['c++', '-std=c++17', '-O2', '-o', str(build / 'oracle'), str(build / 'oracle.cpp')], check=True, timeout=30)
        subprocess.run([str(build / 'oracle'), str(build / 'expected.bin')], check=True, timeout=30)
        java = HERE / 'src/main/java'
        test = HERE / 'src/test/java/android/graphics/NativeBitmapStorageTest.java'
        subprocess.run(['javac', '--release', '11', '-sourcepath', str(java), '-d', str(build), str(test)], check=True, timeout=30)
        subprocess.run(['java', '-Djava.awt.headless=true', '-cp', str(build), 'android.graphics.NativeBitmapStorageTest', str(build / 'expected.bin')], check=True, timeout=30)


if __name__ == '__main__':
    main()
