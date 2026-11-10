#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in age encryption of one private staged failure; never print its bytes."""
import hashlib
import io
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
OUTPUT_NAME = 'staged-encrypted-diagnostic'


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


def bounded_process(argv, stdin=None, limit=4096, seconds=15, home=None):
    # X25519 age needs no network, plugins, credentials or inherited loader flags.
    environment = {'PATH': os.defpath, 'HOME': str(home), 'LANG': 'C', 'LC_ALL': 'C'}
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


def encrypt_private(binary, pin, descriptor, recipient, home):
    def verified_binary():
        fd = regular_descriptor(binary, pin[3])
        try:
            data = os.read(fd, pin[3] + 1)
            return len(data) == pin[3] and digest(data) == pin[4]
        finally:
            os.close(fd)
    require(RECIPIENT.fullmatch(recipient) and verified_binary())
    require(bounded_process([str(binary), '--version'], home=home).strip() == VERSION.encode())
    require(verified_binary())
    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.read(descriptor, INPUT_LIMIT + 1)
    require(len(before) <= INPUT_LIMIT)
    os.lseek(descriptor, 0, os.SEEK_SET)
    ciphertext = bounded_process([str(binary), '--encrypt', '--recipient', recipient],
                                 stdin=descriptor, limit=CIPHER_LIMIT, home=home)
    os.lseek(descriptor, 0, os.SEEK_SET)
    require(os.read(descriptor, INPUT_LIMIT + 1) == before and verified_binary())
    require(ciphertext.startswith(b'age-encryption.org/v1\n') and len(ciphertext) <= CIPHER_LIMIT)
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
        owner_identity(temporary / 'staged-migrations/owner/journal.json')
        descriptor = regular_descriptor(temporary / 'staged-migrations/owner/PRIVATE-command-failure.txt', INPUT_LIMIT)
        stage = 'verified-tool'
        with tempfile.TemporaryDirectory(prefix='staged-age-tool-', dir=temporary) as tools:
            binary, pin = acquire_age(Path(tools))
            stage = 'encryption'
            ciphertext = encrypt_private(binary, pin, descriptor, recipient, Path(tools))
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
