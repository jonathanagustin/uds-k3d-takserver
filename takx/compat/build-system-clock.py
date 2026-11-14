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


def shared_flags(cc, sanitize=False):
    """Production builds stay unsanitized. Tests opt into ASan and UBSan."""
    if sanitize:
        return [cc, '-std=c11', '-O1', '-g', '-fno-omit-frame-pointer', '-fsanitize=address,undefined',
                '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror']
    return [cc, '-std=c11', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror']


def sanitizer_compiler(cc):
    """Use cc when it can link the sanitizers, otherwise gcc."""
    tried = []
    last = ''
    for name in (cc, 'gcc'):
        if name in tried:
            continue
        tried.append(name)
        resolved = shutil.which(name)
        if resolved is None:
            continue
        with tempfile.TemporaryDirectory(prefix='uds-clock-cc-') as directory:
            source = Path(directory) / 'probe.c'
            output = Path(directory) / 'probe.so'
            source.write_text('int probe(void){return 0;}\n')
            result = subprocess.run(
                [resolved, '-fsanitize=address,undefined', '-fPIC', '-shared', str(source), '-o', str(output)],
                capture_output=True, timeout=20)
        if result.returncode == 0:
            return resolved
        last = result.stderr.decode(errors='replace').strip()
    raise RuntimeError('No C compiler could link AddressSanitizer and UBSan' + (': ' + last if last else ''))


def sanitizer_env(cc):
    preload = []
    for name in ('libasan.so', 'libubsan.so'):
        found = subprocess.run([cc, '-print-file-name=' + name], check=True, capture_output=True,
                               text=True, timeout=10).stdout.strip()
        if not found or found == name or not Path(found).is_file():
            raise RuntimeError('sanitizer runtime not found: ' + name)
        preload.append(found)
    # The JVM is not instrumented. Leak detection reports its allocator, and the
    # sanitizer runtime is preloaded rather than linked ahead of the executable.
    return {
        'LD_PRELOAD': ':'.join(preload),
        'ASAN_OPTIONS': 'detect_leaks=0:abort_on_error=1:symbolize=1:verify_asan_link_order=0',
        'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
    }


def build(output, java_home=None, cc='cc', sanitize=False):
    home = toolchain(java_home)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='uds-clock-build-') as directory:
        work = Path(directory)
        subprocess.run([str(home / 'bin/javac'), '--release', '11', '-proc:none',
                        '-h', str(work), '-d', str(work / 'classes'),
                        str(HERE / 'src/main/java/android/os/SystemClock.java')], check=True, timeout=30)
        library = work / 'libuds_desktop_clock.so'
        subprocess.run([*shared_flags(cc, sanitize),
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
