#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in age encryption of one private staged failure; never print its bytes."""
import hashlib
import fcntl
import io
import types
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'v1.3.2'
# Official FiloSottile/age release asset digests, independently matched to bytes.
PINS = {
    'x86_64': ('amd64', 19405817, 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10',
               6977014, 'eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c'),
    'aarch64': ('arm64', 17771923, '6b8dc4333c53a5a57c9e5834e3a48f92605d7154014cd07269ff3327db5d37f4',
                6540637, '41b072352f4561018949623c674d16ef704019b9108a9bbdbd21292efebfc94f'),
}
RECIPIENT = re.compile(r'age1[023456789acdefghjklmnpqrstuvwxyz]{58}')
INPUT_LIMIT = 65536
CIPHER_LIMIT = 73728
VALIDATION_INPUT_LIMIT = 128 * 1024
VALIDATION_CIPHER_LIMIT = VALIDATION_INPUT_LIMIT + 8192
OUTPUT_NAME = 'staged-encrypted-diagnostic'
PACKAGE_NAME = 'PRIVATE-package-command-failure.json'
APPLICATION_NAME = 'PRIVATE-application-check-failure.json'
VALIDATION_NAME = 'PRIVATE-retained-source-validation.json'
PACKAGE_JOURNAL_LIMIT = 16 * 1024 * 1024  # Diagnostic authentication only, never acceptance.


def require(value):
    if not value:
        raise ValueError('encrypted diagnostic guard failed')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_descriptor(path, limit):
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def bounded_process(argv, stdin=None, limit=4096, seconds=15):
    # X25519 age needs no network, plugins, credentials or inherited loader flags.
    environment = {'PATH': os.defpath, 'LANG': 'C', 'LC_ALL': 'C'}
    child = subprocess.Popen(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, env=environment)
    streams = {child.stdout: bytearray(), child.stderr: bytearray()}
    deadline = time.monotonic() + seconds
    selector = selectors.DefaultSelector()
    try:
        for pipe in streams:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            require(remaining > 0)
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    streams[key.fileobj].extend(chunk)
                    require(len(streams[key.fileobj]) <= (limit if key.fileobj is child.stdout else 4096))
        child.wait(timeout=max(0.001, deadline - time.monotonic()))
        require(child.returncode == 0)
        return bytes(streams[child.stdout])
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        selector.close()
        child.stdout.close()
        child.stderr.close()


def extract_age(archive, pin, directory):
    arch, size, checksum, binary_size, binary_checksum = pin
    require(len(archive) == size and digest(archive) == checksum)
    seen, binary, expanded, root_seen = set(), None, 0, False
    allowed = {'age/age', 'age/age-keygen', 'age/age-inspect', 'age/LICENSE',
               'age/age-plugin-tag', 'age/age-plugin-batchpass', 'age/age-plugin-pq', 'age/age-plugin-tagpq'}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
        for member in source:
            if member.name == 'age' and member.isdir():
                require(not root_seen and member.size == 0)
                root_seen = True
                continue
            require(member.isfile() and member.name in allowed and member.name not in seen
                    and 0 <= member.size <= 8 * 1024 * 1024)
            seen.add(member.name)
            expanded += member.size
            require(expanded <= 64 * 1024 * 1024)
            if member.name == 'age/age':
                require(member.size == binary_size)
                binary = source.extractfile(member).read(binary_size + 1)
    require(root_seen and seen == allowed and binary is not None and len(binary) == binary_size
            and digest(binary) == binary_checksum)
    path = directory / 'age'
    with path.open('xb') as output:
        output.write(binary)
    path.chmod(0o700)
    return path


def acquire_age(directory):
    require(platform.system() == 'Linux' and platform.machine() in PINS)
    pin = PINS[platform.machine()]
    url = ('https://github.com/FiloSottile/age/releases/download/' + VERSION +
           '/age-' + VERSION + '-linux-' + pin[0] + '.tar.gz')
    archive = bytearray()
    deadline = time.monotonic() + 60
    # Inherited proxy and CA trust apply only to this official HTTPS download.
    with urllib.request.urlopen(url, timeout=15) as response:
        while chunk := response.read(65536):
            archive.extend(chunk)
            require(len(archive) <= pin[1] and time.monotonic() <= deadline)
    return extract_age(bytes(archive), pin, directory), pin


def encrypt_private(binary, pin, descriptor, recipient, input_limit=INPUT_LIMIT):
    require(input_limit in (INPUT_LIMIT, VALIDATION_INPUT_LIMIT))
    cipher_limit = CIPHER_LIMIT if input_limit == INPUT_LIMIT else VALIDATION_CIPHER_LIMIT
    def verified_binary():
        fd = regular_descriptor(binary, pin[3])
        try:
            data = os.read(fd, pin[3] + 1)
            return len(data) == pin[3] and digest(data) == pin[4]
        finally:
            os.close(fd)
    require(RECIPIENT.fullmatch(recipient) and verified_binary())
    require(bounded_process([str(binary), '--version']).strip() == VERSION.encode())
    require(verified_binary())
    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.read(descriptor, input_limit + 1)
    require(len(before) <= input_limit)
    os.lseek(descriptor, 0, os.SEEK_SET)
    ciphertext = bounded_process([str(binary), '--encrypt', '--recipient', recipient],
                                 stdin=descriptor, limit=cipher_limit)
    os.lseek(descriptor, 0, os.SEEK_SET)
    require(os.read(descriptor, input_limit + 1) == before and verified_binary())
    require(ciphertext.startswith(b'age-encryption.org/v1\n') and len(ciphertext) <= cipher_limit)
    return ciphertext


def context():
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and os.environ.get('GITHUB_REF') == 'refs/heads/main'
            and os.environ.get('GITHUB_REPOSITORY') == 'jonathanagustin/uds-takserver'
            and re.fullmatch('[a-f0-9]{40}', os.environ.get('GITHUB_SHA', ''))
            and re.fullmatch('[1-9][0-9]*', os.environ.get('GITHUB_RUN_ID', ''))
            and re.fullmatch('[1-9][0-9]*', os.environ.get('GITHUB_RUN_ATTEMPT', '')))
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, timeout=5,
                          env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'})
    require(head.returncode == 0 and head.stdout.decode().strip() == os.environ['GITHUB_SHA'])


def owner_identity(path):
    descriptor = regular_descriptor(path, 256 * 1024)
    try:
        raw = os.read(descriptor, 256 * 1024 + 1)
        require(len(raw) <= 256 * 1024)
        journal = json.loads(raw)
    finally:
        os.close(descriptor)
    require(journal.get('schema') == 1 and journal.get('accepted') is False
            and any(entry.get('status') == 'failed' for entry in journal.get('steps', [])))
    cluster = journal['cluster']
    require(cluster['sourceSHA'] == os.environ['GITHUB_SHA']
            and cluster['runID'] == os.environ['GITHUB_RUN_ID']
            and cluster['runAttempt'] == os.environ['GITHUB_RUN_ATTEMPT'])


def package_descriptor(path, limit):
    """Walk private parents by descriptor; no intermediate symlink race."""
    require(path.is_absolute() and '..' not in path.parts)
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        require(stat.S_IMODE(os.fstat(directory).st_mode) == 0o700)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= limit)
        except Exception:
            os.close(descriptor)
            raise
        return descriptor
    finally:
        os.close(directory)


def private_json(path, limit):
    descriptor = package_descriptor(path, limit)
    try:
        before = os.fstat(descriptor)
        chunks, size, hasher = [], 0, hashlib.sha256()
        while chunk := os.read(descriptor, min(65536, limit + 1 - size)):
            chunks.append(chunk)
            hasher.update(chunk)
            size += len(chunk)
            require(size <= limit)
        raw = b''.join(chunks)
        after = os.fstat(descriptor)
        require(before.st_size == after.st_size == len(raw) and before.st_mtime_ns == after.st_mtime_ns
                and before.st_ctime_ns == after.st_ctime_ns)
    finally:
        os.close(descriptor)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _value: require(False)), raw, hasher.hexdigest()


def reviewed_source_hash(relative):
    path = ROOT / relative
    descriptor = regular_descriptor(path, 256 * 1024)
    try:
        raw = os.read(descriptor, 256 * 1024 + 1)
        require(len(raw) <= 256 * 1024)
    finally:
        os.close(descriptor)
    reviewed = bounded_process(['env', 'GIT_NO_LAZY_FETCH=1', 'GIT_TERMINAL_PROMPT=0',
                               'git', '-C', str(ROOT), 'show', 'HEAD:' + relative], limit=256 * 1024, seconds=5)
    require(reviewed == raw)
    return digest(raw)


def package_input(temporary, with_limit=False):
    folder = temporary / 'staged-migrations/package-identity'
    journal, _journal_raw, journal_hash = private_json(folder / 'journal.json', PACKAGE_JOURNAL_LIMIT)
    progress, _progress_raw, _progress_hash = private_json(folder / 'journal-progress.json', 256 * 1024)
    expected = {'sourceSHA': os.environ['GITHUB_SHA'], 'runID': os.environ['GITHUB_RUN_ID'],
                'runAttempt': os.environ['GITHUB_RUN_ATTEMPT']}
    require(type(journal.get('schema')) is int and journal['schema'] == 1 and journal.get('accepted') is False
            and journal.get('method') == 'package')
    require(type(progress.get('schema')) is int and progress['schema'] == 1
            and progress.get('guard') == expected and progress.get('journalSHA256') == journal_hash)
    require(all(journal.get('guard', {}).get(key) == value for key, value in expected.items()))
    first=journal.get('firstPrivateFailure')
    if 'firstPrivateFailure' in journal:
        require(isinstance(first,dict) and set(first)=={'schema','kind','reference'} and
                type(first['schema']) is int and first['schema']==1 and
                first['kind'] in ('package-command','retained-source-validation','application-check'))
        key={'package-command':'packageCommandFailure','retained-source-validation':'retainedSourceValidationFailure','application-check':'applicationCheckFailure'}[first['kind']]
        require(first['reference']==journal.get(key) and isinstance(first['reference'],dict))
        failures=[entry for entry in journal.get('stages',[]) if entry.get('stage') in
                  ('package-command-failed','retained-source-validation-failed','application-check-failed')]
        require(failures and failures[0]['stage']=={'package-command':'package-command-failed',
                'retained-source-validation':'retained-source-validation-failed','application-check':'application-check-failed'}[first['kind']])
        if first['kind']=='application-check':
            descriptor=application_input(folder,journal,expected)
            return (descriptor,INPUT_LIMIT) if with_limit else descriptor
        if first['kind']=='retained-source-validation':
            descriptor=validation_input(folder,journal,expected)
            return (descriptor,VALIDATION_INPUT_LIMIT) if with_limit else descriptor
    else:
        # Only old command-only journals get the legacy fallback. Never guess.
        require('retainedSourceValidationFailure' not in journal and 'applicationCheckFailure' not in journal)
    reference = journal.get('packageCommandFailure', {})
    require(set(reference) == {'file', 'sha256', 'bytes'} and reference['file'] == PACKAGE_NAME
            and type(reference['bytes']) is int and 0 < reference['bytes'] <= INPUT_LIMIT
            and isinstance(reference['sha256'], str) and re.fullmatch('[a-f0-9]{64}', reference['sha256']))
    payload, raw, private_hash = private_json(folder / PACKAGE_NAME, INPUT_LIMIT)
    require(len(raw) == reference['bytes'] and private_hash == reference['sha256'])
    require(set(payload) == {'schema', 'binding', 'role', 'phase', 'exitStatus', 'timedOut', 'stdout', 'stderr',
            'stdoutTruncated', 'stderrTruncated', 'packageDriverSHA256', 'driverSHA256'})
    require(type(payload['schema']) is int and payload['schema'] == 1 and payload['binding'] == expected
            and payload['role'] in ('deploy', 'remove') and payload['phase'] in ('shared', 'transition', 'strict', 'rollback')
            and (payload['role'] != 'remove' or payload['phase'] == 'shared')
            and type(payload['exitStatus']) is int and -255 <= payload['exitStatus'] <= 255
            and type(payload['timedOut']) is bool and (payload['exitStatus'] != 0 or payload['timedOut']))
    for stream in ('stdout', 'stderr'):
        require(isinstance(payload[stream], str) and len(payload[stream].encode('utf-8')) <= 24 * 1024
                and type(payload[stream + 'Truncated']) is bool)
    failed = next((entry for entry in journal.get('stages', []) if entry.get('stage') == 'package-command-failed'), None)
    require(failed is not None and all(type(failed.get(key)) is type(payload[key]) and failed[key] == payload[key]
                                     for key in ('role', 'phase', 'exitStatus', 'timedOut')))
    for key, relative in [('packageDriverSHA256', 'tests/workload-identities/package_roundtrip.py'),
                          ('driverSHA256', 'tests/workload-identities/drive.py')]:
        require(payload[key] == journal.get(key) == reviewed_source_hash(relative))
    descriptor=sealed_payload(raw)
    return (descriptor,INPUT_LIMIT) if with_limit else descriptor

def application_input(folder,journal,expected):
    reference=journal.get('applicationCheckFailure',{})
    require(set(reference)=={'file','sha256','bytes'} and reference['file']==APPLICATION_NAME and
            type(reference['bytes']) is int and 0<reference['bytes']<=INPUT_LIMIT and
            isinstance(reference['sha256'],str) and re.fullmatch('[a-f0-9]{64}',reference['sha256']))
    payload,raw,private_hash=private_json(folder/APPLICATION_NAME,INPUT_LIMIT)
    require(len(raw)==reference['bytes'] and private_hash==reference['sha256'])
    require(set(payload)=={'schema','binding','check','phase','exitStatus','timedOut','stdout','stderr',
            'stdoutTruncated','stderrTruncated','packageDriverSHA256','driverSHA256'})
    require(type(payload['schema']) is int and payload['schema']==1 and payload['binding']==expected and
            payload['check'] in ('web-tls','api-smoke','flows','cloudtak') and
            payload['phase'] in ('baseline','transition','strict','rollback','fresh-strict') and
            type(payload['exitStatus']) is int and -255<=payload['exitStatus']<=255 and
            type(payload['timedOut']) is bool and (payload['exitStatus']!=0 or payload['timedOut']))
    for stream in ('stdout','stderr'):
        require(isinstance(payload[stream],str) and len(payload[stream].encode('utf-8'))<=24*1024 and
                type(payload[stream+'Truncated']) is bool)
    failed=next((entry for entry in journal.get('stages',[]) if entry.get('stage')=='application-check-failed'),None)
    require(failed is not None and all(type(failed.get(key)) is type(payload[key]) and failed[key]==payload[key]
                                     for key in ('check','phase','exitStatus','timedOut')))
    for key,relative in [('packageDriverSHA256','tests/workload-identities/package_roundtrip.py'),
                         ('driverSHA256','tests/workload-identities/drive.py')]:
        require(payload[key]==journal.get(key)==reviewed_source_hash(relative))
    return sealed_payload(raw)


def sealed_payload(raw):
    # Encrypt the validated snapshot, not a pathname that can change after checks.
    descriptor = os.memfd_create('staged-package-failure', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        require(os.write(descriptor, raw) == len(raw))
        # Linux UAPI values also support Python builds that omit their names.
        fcntl.fcntl(descriptor, getattr(fcntl, 'F_ADD_SEALS', 1033), 0x000F)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise



def validation_input(folder,journal,expected):
    reference=journal.get('retainedSourceValidationFailure',{})
    require(set(reference)=={'file','sha256','bytes'} and reference['file']==VALIDATION_NAME and
            type(reference['bytes']) is int and 0<reference['bytes']<=VALIDATION_INPUT_LIMIT and
            isinstance(reference['sha256'],str) and re.fullmatch('[a-f0-9]{64}',reference['sha256']))
    payload,raw,checksum=private_json(folder/VALIDATION_NAME,VALIDATION_INPUT_LIMIT)
    require(len(raw)==reference['bytes'] and checksum==reference['sha256'])
    require(set(payload)=={'schema','type','kind','binding','phase','snapshot','packageDriverSHA256','driverSHA256','retainedSourceSHA256'} and
            type(payload['schema']) is int and payload['schema']==1 and payload['type']=='retained-source-validation' and
            payload['kind'] in ('stored-hooks-drift','core-inventory-drift') and payload['binding']==expected and
            payload['phase'] in ('shared','transition','strict','rollback'))
    failed=next((entry for entry in journal.get('stages',[]) if entry.get('stage')=='retained-source-validation-failed'),None)
    require(failed is not None and failed.get('phase')==payload['phase'])
    for key,relative in [('packageDriverSHA256','tests/workload-identities/package_roundtrip.py'),
                         ('driverSHA256','tests/workload-identities/drive.py'),
                         ('retainedSourceSHA256','tests/workload-identities/retained_state.py')]:
        require(payload[key]==journal.get(key)==reviewed_source_hash(relative))
    # The reviewed retained-source helper binds the full hook bodies to their hash inventory.
    path=ROOT/'tests/workload-identities/retained_state.py'
    descriptor=regular_descriptor(path,256*1024)
    try:source=os.read(descriptor,256*1024+1)
    finally:os.close(descriptor)
    require(len(source)<=256*1024 and digest(source)==payload['retainedSourceSHA256'])
    retained=types.ModuleType('encrypted_retained_source');retained.__file__=str(path)
    exec(compile(source,str(path),'exec'),retained.__dict__)
    (retained.validate_source_failure if payload['kind']=='stored-hooks-drift' else retained.validate_core_failure)(payload['snapshot'])
    return sealed_payload(raw)


def select_private(temporary, with_limit=False):
    scenario = os.environ.get('SCENARIO', '')
    candidates = []
    try:
        if scenario in ('', 'velero', 'all'):
            owner_identity(temporary / 'staged-migrations/owner/journal.json')
            candidates.append((regular_descriptor(temporary / 'staged-migrations/owner/PRIVATE-command-failure.txt', INPUT_LIMIT),INPUT_LIMIT))
    except Exception:
        pass  # An ineligible channel never authorizes its private bytes.
    try:
        if scenario in ('identities', 'all') and os.environ.get('IDENTITY_METHOD') in ('package', 'combined'):
            candidates.append(package_input(temporary,with_limit=True))
    except Exception:
        pass
    if len(candidates) != 1:
        for descriptor,_limit in candidates:
            os.close(descriptor)
        require(False)
    return candidates[0] if with_limit else candidates[0][0]


def main():
    recipient = os.environ.get('STAGED_AGE_RECIPIENT', '')
    if not recipient or os.environ.get('STAGED_TRIAL_OUTCOME') != 'failure':
        print('Encrypted staged diagnostic disabled or trial did not fail')
        return 0
    descriptor, destination, owned = None, None, False
    stage = 'identity'
    try:
        context()
        require(RECIPIENT.fullmatch(recipient))
        temporary = Path(os.environ['RUNNER_TEMP'])
        require(temporary.is_absolute() and temporary.is_dir()
                and not any(p.is_symlink() for p in (temporary, *temporary.parents)))
        output_file = Path(os.environ['GITHUB_OUTPUT'])
        require(temporary in output_file.parents)
        output_descriptor = regular_descriptor(output_file, 1024 * 1024)
        os.close(output_descriptor)
        destination = temporary / OUTPUT_NAME
        require(not destination.exists() and not destination.is_symlink())
        stage = 'private-input'
        descriptor,input_limit = select_private(temporary,with_limit=True)
        stage = 'verified-tool'
        with tempfile.TemporaryDirectory(prefix='staged-age-tool-', dir=temporary) as tools:
            binary, pin = acquire_age(Path(tools))
            stage = 'encryption'
            ciphertext = (encrypt_private(binary,pin,descriptor,recipient) if input_limit==INPUT_LIMIT else
                          encrypt_private(binary,pin,descriptor,recipient,input_limit=input_limit))
        os.close(descriptor)
        descriptor = None
        context()
        stage = 'ciphertext-output'
        destination.mkdir(mode=0o700)
        owned = True
        cipher = destination / 'first-failure.age'
        fd = os.open(cipher, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(ciphertext)
        require(cipher.stat().st_size == len(ciphertext) and digest(cipher.read_bytes()) == digest(ciphertext))
        # Upload requires both this output and the encryption step's success.
        output_fd = os.open(output_file, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            require(stat.S_ISREG(os.fstat(output_fd).st_mode))
            require(os.write(output_fd, b'ready=true\n') == 11)
        finally:
            os.close(output_fd)
        return 0
    except Exception:
        # No exception, recipient, input, argv, stderr or URL is printable here.
        print('Encrypted staged diagnostic omitted: ' + stage, file=sys.stderr)
        if owned:
            try:
                (destination / 'first-failure.age').unlink(missing_ok=True)
                destination.rmdir()
            except OSError:
                pass
        return 1
    finally:
        if descriptor is not None:
            os.close(descriptor)


if __name__ == '__main__':
    sys.exit(main())
