#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Postfailure namespace lookup from an existing agent; never historical proof."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

UUID = r'[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}'
NAME = r'[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?'


def identity(pod):
    """Only a current canonical agent/server identity can select exec."""
    meta, spec = pod['metadata'], pod['spec']
    name, uid, account = meta['name'], meta['uid'], spec['serviceAccountName']
    node = spec['nodeName']
    assert meta['namespace'] == 'zarf'
    assert re.fullmatch(r'agent-hook-[a-z0-9-]{1,242}', name)
    assert re.fullmatch(UUID, uid)
    assert re.fullmatch(NAME, account)
    assert re.fullmatch(NAME, node)
    assert len([c for c in spec['containers'] if c['name'] == 'server']) == 1
    return {'namespace': 'zarf', 'name': name, 'uid': uid, 'serviceAccount': account, 'node': node}


def snapshot(path):
    try:
        selected = identity(json.loads(Path(path).read_text()))
    except (AssertionError, KeyError, TypeError, ValueError, OSError):
        return {'snapshot': 'postfailure', 'result': 'invalid-agent-identity'}
    command = ['timeout', '--kill-after=1s', '3s', 'uds', 'zarf', 'tools',
               'kubectl', '--request-timeout=2s', 'exec', '-n', 'zarf',
               selected['name'], '-c', 'server', '--', '/zarf', 'tools',
               'kubectl', '--request-timeout=2s', 'get', 'namespace', 'velero',
               '-o', 'jsonpath={.metadata.uid}']
    start = time.monotonic()
    # Never expose exec errors: they can contain credentials or arbitrary output.
    value = b''
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as process:
            # Keep at most 129 bytes, even if an unexpected executable is noisy.
            # The outer timeout also bounds a blocked read or full pipe.
            value = process.stdout.read(129)
            code = process.wait()
    except OSError:
        code = None
    elapsed = round((time.monotonic() - start) * 1000)
    result = {'snapshot': 'postfailure', 'agent': selected, 'elapsed_ms': elapsed,
              'exit': code}
    if code != 0:
        result['result'] = ('exec-unavailable' if code in (None, 126, 127) else
                            'exec-or-lookup-timeout' if code in (124, 137) else
                            'exec-or-lookup-failed')
    elif len(value) <= 128 and re.fullmatch(UUID.encode(), value):
        result.update(result='lookup-succeeded', targetNamespace='velero',
                      targetUID=value.decode('ascii'))
    else:
        result['result'] = 'invalid-lookup-output'
    return result


if __name__ == '__main__':
    # Caller runs this only after primary evidence, within its existing deadline.
    for source in sys.argv[1:3]:
        print(json.dumps(snapshot(source)), flush=True)
