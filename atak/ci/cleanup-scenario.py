#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Delete only nonce-labelled owned resources and verify their actual absence."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


class Kubernetes:
    def call(self, args, data=None):
        with subprocess.Popen(['uds', 'zarf', 'tools', 'kubectl', '--request-timeout=1s', *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True) as process:
            try:
                output, _ = process.communicate(input=data, timeout=2)
                if process.returncode:
                    raise RuntimeError('owned-resource API operation failed')
                if len(output) > 65536:
                    raise ValueError('owned-resource API output exceeded bound')
                return output.decode().strip()
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=1)

    def identity(self, kind, namespace, name):
        projection = r'jsonpath={.metadata.uid}{"\t"}{.metadata.labels.tak\.jonathanagustin\.github\.io/scenario-owner}'
        output = self.call(['get', kind, name, '-n', namespace, '--ignore-not-found', '-o', projection])
        if not output:
            return None
        parts = output.split('\t')
        if len(parts) != 2 or not re.fullmatch('[a-f0-9-]{1,64}', parts[0]):
            raise ValueError('invalid owned-resource identity response')
        return tuple(parts)

    def delete(self, path, uid):
        # UID precondition prevents deleting a replacement between GET/DELETE.
        body = json.dumps({'apiVersion':'v1', 'kind':'DeleteOptions', 'preconditions':{'uid':uid}, 'gracePeriodSeconds':0}).encode()
        self.call(['delete', '--raw', path, '-f', '-'], body)


def remove_owned(api, owner, deadline):
    resources = [('takclient', 'takclients', 'atak-peer-'+owner, '/apis/tak.jonathanagustin.github.io/v1alpha1/namespaces/takclients/takclients/atak-peer-'+owner),
                 ('pod', 'atak', 'atak-scenario-'+owner, '/api/v1/namespaces/atak/pods/atak-scenario-'+owner)]
    pending, foreign = [], False
    # Request both owned deletions before waiting, so one finalizer cannot
    # prevent the other owned helper from being stopped.
    for kind, namespace, name, path in resources:
        identity = api.identity(kind, namespace, name)
        if identity is None:
            continue
        uid, label = identity
        if label != owner:
            foreign = True
            continue
        api.delete(path, uid)
        pending.append((kind, namespace, name, identity))
    while pending:
        remaining = []
        for kind, namespace, name, identity in pending:
            current = api.identity(kind, namespace, name)
            if current is None:
                continue
            if current != identity:
                foreign = True
                continue  # Never issue another delete against a replacement.
            remaining.append((kind, namespace, name, identity))
        pending = remaining
        if pending:
            if time.monotonic() >= deadline:
                raise TimeoutError('owned resources remain after delete requests')
            time.sleep(.1)
    if foreign:
        raise ValueError('unowned or replaced resource prevented verified cleanup')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{16}', args.owner):
        parser.error('invalid owned identity')
    receipt = {'cleanup_verified':False, 'owned_resources_absent':False}
    def expired(signum, frame):
        raise TimeoutError('cleanup deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    previous_term = signal.signal(signal.SIGTERM, expired)
    signal.alarm(15)
    try:
        remove_owned(Kubernetes(), args.owner, time.monotonic()+15)
        receipt.update(cleanup_verified=True, owned_resources_absent=True)
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        raise SystemExit('owned cleanup failed: '+type(error).__name__) from None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        signal.signal(signal.SIGTERM, previous_term)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'cleanup.json').write_text(json.dumps(receipt)+'\n')


if __name__ == '__main__':
    main()
