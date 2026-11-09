#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Standalone source-built CommonCommo mTLS proof; no build/cache metadata writes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('commo_inputs', HERE / 'source_inputs.py')
INPUTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INPUTS)


def run(label, args, env=None, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        raise RuntimeError(label + ': launch/timeout failure') from None
    if result.returncode:
        raise RuntimeError(label + ': exit ' + str(result.returncode))
    return result.stdout


def verify_staged(expected, actual):
    records = {}
    for path in sorted(expected.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(expected)
        target = actual / relative
        if target.is_symlink() or not target.is_file() or INPUTS.digest(path) != INPUTS.digest(target):
            raise ValueError('compiled source does not match pinned patched source: ' + str(relative))
        records[str(relative)] = INPUTS.digest(path)
    return records


def credentials(directory, env):
    def openssl(*args):
        run('ephemeral OpenSSL credentials', ['openssl', *map(str, args)], env)
    for name in ('ca', 'wrong-ca'):
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', directory / (name + '.key'),
                '-out', directory / (name + '.crt'), '-days', '2', '-sha256', '-subj', '/CN=Local TLS Smoke ' + name,
                '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        target = 'trust.p12' if name == 'ca' else 'wrong-trust.p12'
        openssl('pkcs12', '-export', '-nokeys', '-in', directory / (name + '.crt'), '-out', directory / target,
                '-passout', 'env:TAKX_TLS_PASSWORD')
    for name, usage in (('server', 'serverAuth'), ('client', 'clientAuth')):
        openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', directory / (name + '.key'),
                '-out', directory / (name + '.csr'), '-subj', '/CN=Local TLS Smoke ' + name)
        extension = directory / (name + '.ext')
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=' + usage + '\nsubjectAltName=IP:127.0.0.1,DNS:localhost\n')
        openssl('x509', '-req', '-in', directory / (name + '.csr'), '-CA', directory / 'ca.crt',
                '-CAkey', directory / 'ca.key', '-CAcreateserial', '-out', directory / (name + '.crt'),
                '-days', '2', '-sha256', '-extfile', extension)
        openssl('pkcs12', '-export', '-inkey', directory / (name + '.key'), '-in', directory / (name + '.crt'),
                '-certfile', directory / 'ca.crt', '-out', directory / (name + '.p12'), '-passout', 'env:TAKX_TLS_PASSWORD')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--compiled-source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('report must be a new file')
    source, prefix, compiled = args.source.resolve(), args.prefix.resolve(), args.compiled_source.resolve()
    if prefix not in compiled.parents:
        parser.error('compiled source must be within the supplied local prefix')
    lock_path = HERE / 'sources.lock.json'
    lock = json.loads(lock_path.read_text())
    INPUTS.verify_source(source, lock)
    INPUTS.verify_patches(lock_path, lock)
    for entry in lock['archives']:
        INPUTS.check_archive(source / entry['path'], entry)
    java_home = Path(os.environ['JAVA_HOME'])
    require_version = run('JDK version', [str(java_home / 'bin/javac'), '-version'])
    if not require_version.startswith('javac 17.'):
        parser.error('trusted JDK17 required')
    env = dict(os.environ, TAKX_TLS_PASSWORD=secrets.token_hex(24),
               LD_LIBRARY_PATH=str(prefix / 'lib') + (':' + os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))
    old_mask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix='commo-mtls-') as temporary:
            work = Path(temporary)
            expected = INPUTS.stage_patches(source, work, lock_path, lock)
            source_records = verify_staged(expected, compiled)
            closure = run('native dependency closure', ['ldd', str(prefix / 'lib/libcommoncommojni.so')], env)
            if 'not found' in closure:
                raise ValueError('native runtime dependency is missing')
            dependency_files = sorted(set(re.findall(r'=> (/\S+)', closure)))
            artifact_files = [prefix / name for name in INPUTS.ARTIFACTS]
            artifact_records = {str(path): INPUTS.digest(path) for path in artifact_files}
            runtime_records = {name: INPUTS.digest(Path(name).resolve()) for name in dependency_files}
            classes = work / 'classes'
            run('compile real transport smokes', [str(java_home / 'bin/javac'), '--release', '17', '-cp', str(prefix / 'java/jcommoncommo.jar'),
                 '-d', str(classes), *[str(HERE / (name + '.java')) for name in ('CommonCommoSmoke', 'CommonCommoRoutingSmoke', 'CommonCommoTlsSmoke')]])
            outcomes = {}
            for name, limit in [('CommonCommoSmoke', 30), ('CommonCommoRoutingSmoke', 60)]:
                outcomes[name] = run(name, [str(java_home / 'bin/java'), '-Djava.library.path=' + str(prefix / 'lib'),
                                           '-cp', str(prefix / 'java/jcommoncommo.jar') + ':' + str(classes), name], env, limit)
                print(outcomes[name], end='')
            credentials(work, env)
            outcomes['CommonCommoTlsSmoke'] = run('real mutual TLS', [str(java_home / 'bin/java'), '-Djava.library.path=' + str(prefix / 'lib'),
                  '-cp', str(prefix / 'java/jcommoncommo.jar') + ':' + str(classes), 'CommonCommoTlsSmoke', str(work)], env, 60)
            print(outcomes['CommonCommoTlsSmoke'], end='')
            # Detect output replacement during this bounded experiment.
            if any(INPUTS.digest(Path(name)) != value for name, value in artifact_records.items()):
                raise ValueError('native artifact changed during the smoke')
            report = {'sourceRevision': lock['atak_source']['revision'], 'sourceLockSHA256': INPUTS.digest(lock_path), 'patches': lock['patches'], 'compiledSourceSHA256': source_records,
                      'smokeSourceSHA256': {name: INPUTS.digest(HERE / (name + '.java')) for name in ('CommonCommoSmoke', 'CommonCommoRoutingSmoke', 'CommonCommoTlsSmoke')}, 'runnerSHA256': INPUTS.digest(Path(__file__)), 'nativeArtifactsSHA256': artifact_records, 'runtimeClosureSHA256': runtime_records, 'java': require_version.strip(),
                      'openssl': run('OpenSSL version', ['openssl', 'version']).strip(), 'outcomes': outcomes,
                      'scope': 'incremental source/runtime proof, not completed-cache attestation; trusted-chain mTLS only',
                      'hostnameVerification': False, 'takServerInteroperability': False, 'fullTakxAcceptance': False}
            with args.report.open('x') as output:
                json.dump(report, output, indent=2)
                output.write('\n')
    finally:
        os.umask(old_mask)


if __name__ == '__main__':
    main()
