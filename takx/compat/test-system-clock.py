#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded real Linux JNI timing and explicit routing/error fixture tests."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('clock_build', HERE / 'build-system-clock.py')
clock_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock_build)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', type=Path)
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='takx-clock-test-') as directory:
        work = Path(directory)
        real, fixture, missing = (work / name for name in ('real', 'fixture', 'missing'))
        compiler = clock_build.sanitizer_compiler(args.cc)
        home = clock_build.build(real, args.java_home, compiler, sanitize=True)
        fixture.mkdir(); missing.mkdir()
        classes = work / 'classes'
        subprocess.run([str(home / 'bin/javac'), '--release', '11', '-proc:none', '-h', str(work), '-d', str(classes),
                        str(HERE / 'src/main/java/android/os/SystemClock.java'),
                        str(HERE / 'src/test/java/clock/SystemClockCompatibilityTest.java')], check=True, timeout=30)
        includes = ['-I' + str(work), '-I' + str(home / 'include'), '-I' + str(home / 'include/linux')]
        flags = [*clock_build.shared_flags(compiler, sanitize=True), *includes]
        subprocess.run(flags + [str(HERE / 'src/test/native/clock-reference.c'),
                               '-o', str(real / 'libuds_clock_reference.so')], check=True, timeout=30)
        subprocess.run(flags + ['-Wl,--wrap=clock_gettime',
                               str(HERE / 'src/main/native/system-clock.c'),
                               str(HERE / 'src/test/native/clock-routing-fixture.c'),
                               '-o', str(fixture / 'libuds_desktop_clock.so')], check=True, timeout=30)
        runtime = clock_build.sanitizer_env(compiler)
        for mode in ['real', 'routing', 'error', 'overflow', 'missing', 'unsupported']:
            library = real if mode == 'real' else missing if mode == 'missing' else fixture
            command = [str(home / 'bin/java'), '-Djava.library.path=' + str(library)]
            if mode == 'unsupported':
                command.append('-Dos.name=Darwin')
            command += ['-cp', str(classes), 'clock.SystemClockCompatibilityTest', mode]
            subprocess.run(command, env={**os.environ, **runtime, 'UDS_CLOCK_TEST_MODE': mode}, check=True, timeout=15)


if __name__ == '__main__':
    main()
