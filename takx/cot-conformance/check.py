#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline provenance guard by default; explicit --run uses an existing genuine JNI prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
PIN = '9f6893dd657feacc35ec5de03dad721c2e44170e'
JAR = 'e879c65e32af6e8eda2487b8520b30a57f313b5d292798920480b227e7315a36'
JNI = '14aa3a2f15cd136872b666fcec4903239b0ba571e7132dee9396060062d0aaa9'
RECEIPT = '851cc79d3189f42117579d8b6785a4f2affab7fefa5b2a26ed5bd0f6285c48ce'
CAP = 8 * 1024 * 1024


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify(root=HERE):
    data = json.loads((root / 'provenance.json').read_text())
    assert data['revision'] == PIN
    assert len(data['files']) == 17
    for name, entry in data['files'].items():
        p = root / name
        assert p.resolve().is_relative_to(root.resolve())
        assert digest(p) == entry['sha256'], name
    return data


def allocated(root):
    return sum(p.stat().st_blocks * 512 for p in [root, *root.rglob('*')])


def run(args):
    verify()
    out = args.output.resolve()
    assert not out.exists(), 'fresh output required'
    out.mkdir(mode=0o700)
    deadline = time.monotonic() + 90
    prefix, jdk = args.prefix.resolve(), args.jdk.resolve()
    jar, jni = prefix / 'java/jcommoncommo.jar', prefix / 'lib/libcommoncommojni.so'
    receipt = args.receipt.resolve()
    assert digest(jar) == JAR and digest(jni) == JNI and digest(receipt) == RECEIPT
    producer = json.loads(receipt.read_text())
    assert producer['original_producer']['revision'] == PIN
    assert producer['version'] == '1.17.2'
    for name, entry in verify()['files'].items():
        if entry['source'].startswith('commoncommo/core/impl/protobuf/'):
            relative = entry['source'].removeprefix('commoncommo/')
            assert producer['source_postimages'][relative]['sha256'] == entry['sha256'], relative
    inputs = {str(p): digest(p) for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    inputs.update({str(p): digest(p) for p in (jar, jni, receipt, jdk / 'bin/java', jdk / 'bin/javac')})
    # Host runtime libraries are trusted externally owned inputs, frozen before use.
    providers = dict(producer['runtime_closure'])
    # Explicit externally owned glibc compatibility DSOs used by JDK17 on this host.
    # No project/backend provider is admitted through this host-runtime list.
    for name in ('librt.so.1', 'libdl.so.2', 'libpthread.so.0'):
        p = Path('/usr/lib/x86_64-linux-gnu') / name
        providers[str(p.resolve())] = digest(p)
    providers[str(jni)] = JNI
    providers[str((jdk / 'bin/java').resolve())] = digest(jdk / 'bin/java')
    for p in (jdk / 'lib').rglob('*.so'):
        providers[str(p.resolve())] = digest(p)
    for p, h in providers.items():
        assert digest(p) == h, p
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'JAVA_', '_JAVA_', 'JDK_'))}
    env['HOME'] = str(out)
    commands = []

    def command(vector, name, limit):
        log = out / (name + '.log')
        assert allocated(out) + 1024 * 1024 < CAP
        assert os.statvfs(out).f_bavail * os.statvfs(out).f_frsize >= 2 * 1024**3
        with log.open('wb') as f:
            p = subprocess.Popen([str(x) for x in vector], cwd=out, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
            end = min(deadline, time.monotonic() + limit)
            try:
                while p.poll() is None:
                    assert time.monotonic() < end, 'deadline'
                    assert log.stat().st_size <= 1024 * 1024 and allocated(out) <= CAP, 'output cap'
                    time.sleep(.05)
                assert p.returncode == 0, name + ' failed; preserved log: ' + str(log)
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        commands.append({'argv': [str(x) for x in vector], 'log_sha256': digest(log), 'exit': p.returncode})
        assert log.stat().st_size <= 1024 * 1024 and allocated(out) <= CAP
        return log.read_text()

    classes = out / 'classes'
    classes.mkdir()
    try:
        command([jdk / 'bin/javac', '-cp', jar, '-d', classes, HERE / 'ProtocolConformance.java'], 'compile', 30)
        text = command([jdk / 'bin/java', '-Xcheck:jni', '-Djava.library.path=' + str(prefix / 'lib'), '-cp', str(jar) + os.pathsep + str(classes), 'ProtocolConformance', HERE, jar, out / 'maps.txt'], 'runtime', 45)
        assert 'WARNING' not in text and 'FATAL ERROR' not in text
        assert 'actual shutdown returned' in text
        mapped = {}
        for line in (out / 'maps.txt').read_text().splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) != 6 or 'x' not in fields[1] or not fields[5].startswith('/'):
                continue
            p = Path(fields[5]).resolve()
            if p.read_bytes()[:4] != b'\x7fELF':
                continue
            assert str(p) in providers, 'unexpected ELF provider: ' + str(p)
            assert digest(p) == providers[str(p)]
            mapped[str(p)] = digest(p)
        assert str(jni) in mapped
        for p, h in {**inputs, **providers}.items():
            assert digest(p) == h, p
        result = {'status': 'pass', 'official_revision': PIN, 'commands': commands, 'inputs': inputs, 'mapped_elfs': mapped, 'trusted_host_runtime_inputs': providers, 'classes': {str(p.relative_to(out)): digest(p) for p in classes.rglob('*.class')}, 'strict_jni_warnings': 0, 'loopback_only': True, 'takserver_interoperability': False, 'schema_validation': False, 'full_sdk': False, 'takx_client': False}
        (out / 'complete.json').write_text(json.dumps(result, indent=2) + '\n')
        assert allocated(out) <= CAP
        print('PASS actual codec + loopback negotiation; receipt', out / 'complete.json')
    except BaseException as error:
        (out / 'failure.json').write_text(json.dumps({'error': str(error), 'commands': commands, 'inputs': inputs}, indent=2) + '\n')
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', action='store_true')
    p.add_argument('--prefix', type=Path)
    p.add_argument('--receipt', type=Path)
    p.add_argument('--jdk', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.run:
        if any(x is None for x in (a.prefix, a.receipt, a.jdk, a.output)):
            p.error('--run requires --prefix --receipt --jdk --output')
        run(a)
    else:
        verify()
        print('PASS offline official source provenance; no compiler/JVM/native loading')


if __name__ == '__main__':
    main()
