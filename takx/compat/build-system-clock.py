#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in source build of the Linux-only desktop SystemClock JNI library."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def toolchain(java_home=None):
    if platform.system() != 'Linux':
        raise RuntimeError('SystemClock native build requires Linux')
    javac = shutil.which('javac')
    home = Path(java_home or os.environ.get('JAVA_HOME') or
                (Path(javac).resolve().parents[1] if javac else '/missing-jdk')).resolve()
    if not (home / 'include/linux/jni_md.h').is_file() or not (home / 'bin/javac').is_file():
        raise RuntimeError('A Linux JDK with JNI development headers is required')
    return home


def build(output, java_home=None, cc='cc'):
    home = toolchain(java_home)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='uds-clock-build-') as directory:
        work = Path(directory)
        subprocess.run([str(home / 'bin/javac'), '--release', '11', '-proc:none',
                        '-h', str(work), '-d', str(work / 'classes'),
                        str(HERE / 'src/main/java/android/os/SystemClock.java')], check=True, timeout=30)
        library = work / 'libuds_desktop_clock.so'
        subprocess.run([cc, '-std=c11', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(work), '-I' + str(home / 'include'), '-I' + str(home / 'include/linux'),
                        '-Wl,-z,defs,-z,relro,-z,now', str(HERE / 'src/main/native/system-clock.c'),
                        '-o', str(library)], check=True, timeout=30)
        # Copy only our named artifact. Never remove an output directory or user files.
        shutil.copyfile(library, output / library.name)
    return home


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    args = parser.parse_args()
    build(args.output, args.java_home, args.cc)
    print('Built libuds_desktop_clock.so from local source')


if __name__ == '__main__':
    main()
