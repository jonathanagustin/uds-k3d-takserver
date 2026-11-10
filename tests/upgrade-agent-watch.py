#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in evidence only: never an application acceptance gate."""
import argparse
import datetime as dt
import json
import re
import resource
import subprocess
import tempfile
import time


class Unavailable(Exception):
    pass


def stamp(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError, TypeError):
        return 0


def valid(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


class Commands:
    def __init__(self, deadline):
        self.deadline = deadline

    def run(self, *args):
        # Temporary files bound memory; never print stdout/stderr on failures.
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Unavailable('deadline')
        with tempfile.TemporaryFile() as out:
            try:
                limit = min(1.2, max(0.01, remaining - 0.2))
                result = subprocess.run(['timeout', '--kill-after=0.1s', str(limit) + 's', *args],
                                        stdout=out, stderr=subprocess.DEVNULL,
                                        timeout=remaining, check=False,
                                        preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576)))
                if result.returncode or out.tell() > 1048576:
                    raise Unavailable('command-or-size')
                out.seek(0)
                return out.read().decode('utf-8')
            except (OSError, subprocess.TimeoutExpired, UnicodeError):
                raise Unavailable('command-unavailable') from None

    def kube(self, *args):
        try:
            return json.loads(self.run('uds', 'zarf', 'tools', 'kubectl',
                                       '--request-timeout=1s', *args, '-o', 'json'))
        except (ValueError, TypeError):
            raise Unavailable('invalid-json') from None


def identity(pod):
    meta = pod.get('metadata', {})
    uid, name = meta.get('uid'), meta.get('name')
    node = pod.get('spec', {}).get('nodeName')
    if not (valid(uid, r'[a-f0-9-]{36}') and valid(name, r'agent-hook-[a-z0-9-]{1,100}')
            and valid(node, r'k3d-[a-zA-Z0-9_.-]+-(?:server|agent)-[0-9]+')):
        raise Unavailable('pod-identity')
    statuses = [s for s in pod.get('status', {}).get('containerStatuses', [])
                if s.get('name') == 'server']
    if len(statuses) != 1:
        raise Unavailable('container-identity')
    status = statuses[0]
    cid = status.get('containerID', '')
    if not valid(cid, r'containerd://[a-f0-9]{64}'):
        raise Unavailable('container-protocol')
    started = stamp(status.get('state', {}).get('running', {}).get('startedAt'))
    if started <= 0:
        raise Unavailable('current-running-container-unavailable')
    return {'uid': uid, 'pod': name, 'node': node, 'containerID': cid, 'containerStartedAt': started,
            'restartCount': status.get('restartCount') if type(status.get('restartCount')) is int else None}


def count(event):
    value = event.get('series', {}).get('count', event.get('count', 1))
    return value if type(value) is int and value > 0 else 0


def live_failure(event, current, baseline, started):
    ref = event.get('involvedObject', {})
    key = event.get('metadata', {}).get('uid')
    timestamp = (event.get('series', {}).get('lastObservedTime') or
                 event.get('lastTimestamp') or event.get('eventTime'))
    return (valid(key, r'[a-f0-9-]{36}') and ref.get('uid') == current['uid']
            and ref.get('fieldPath') == 'spec.containers{server}'
            and event.get('reason') == 'Unhealthy'
            and event.get('message', '').startswith('Liveness probe failed:')
            and count(event) > baseline.get(key, 0) and stamp(timestamp) > started
            and stamp(timestamp) >= current.get('containerStartedAt', float('inf')))


def task_pid(text, cid):
    matches = []
    for line in text.splitlines():
        cols = line.split()
        if len(cols) == 3 and cols[0] == cid and cols[2] == 'RUNNING' and valid(cols[1], r'[1-9][0-9]{0,9}'):
            matches.append(cols[1])
    if len(matches) != 1:
        raise Unavailable('exact-running-task-unavailable')
    return matches[0]


def cgroup_path(text, cid):
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].startswith('0::/'):
        raise Unavailable('cgroup-v2-unavailable')
    path = lines[0][3:]
    parts = path.split('/')[1:]
    if (not parts or len(path) > 1024 or any(not valid(p, r'[A-Za-z0-9_.:-]+') or p in ('.', '..') for p in parts)
            or not any(p in (cid, 'cri-containerd-' + cid + '.scope') for p in parts)):
        raise Unavailable('cgroup-path-unavailable')
    return '/sys/fs/cgroup' + path


def metric(name, text):
    if len(text) > 4096:
        raise Unavailable('metric-size')
    if name in ('memory.current', 'memory.max'):
        value = text.strip()
        if valid(value, r'[0-9]+') or (name == 'memory.max' and value == 'max'):
            return value
    elif name == 'cpu.max':
        if valid(text.strip(), r'(?:max|[0-9]+) [0-9]+'):
            return text.strip()
    else:
        allowed = {'cpu.stat': {'usage_usec', 'user_usec', 'system_usec', 'nr_periods', 'nr_throttled', 'throttled_usec', 'nr_bursts', 'burst_usec'},
                   'memory.events': {'low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill'}}[name]
        result = {}
        for line in text.splitlines():
            cols = line.split()
            if len(cols) != 2 or cols[0] not in allowed or not valid(cols[1], r'[0-9]+') or cols[0] in result:
                raise Unavailable('metric-schema')
            result[cols[0]] = int(cols[1])
        if result:
            return result
    raise Unavailable('metric-schema')


def snapshot(cmd, current):
    node, cid = current['node'], current['containerID'].split('://')[1]
    def execute(*args):
        return cmd.run('docker', 'exec', node, 'timeout', '1', *args)
    def pid():
        return task_pid(execute('k3s', 'ctr', '-n', 'k8s.io', 'tasks', 'list'), cid)
    first = pid()
    path = cgroup_path(execute('cat', '/proc/' + first + '/cgroup'), cid)
    result = {}
    for name in ('cpu.stat', 'cpu.max', 'memory.current', 'memory.max', 'memory.events'):
        try:
            result[name] = metric(name, execute('cat', path + '/' + name))
        except Unavailable:
            result[name] = 'unavailable'
    if pid() != first or cgroup_path(execute('cat', '/proc/' + first + '/cgroup'), cid) != path:
        raise Unavailable('identity-changed-during-capture')
    return {'pid': int(first), 'cgroupVersion': 2, 'metrics': result}


def observe(seconds):
    deadline = time.monotonic() + seconds
    cmd = Commands(deadline)
    # Establish baseline BEFORE observation starts. Never accept restored events.
    events = cmd.kube('get', 'events', '-n', 'zarf')
    baseline = {e.get('metadata', {}).get('uid'): count(e) for e in events['items']}
    started = time.time()
    print(json.dumps({'watch': 'started', 'observedAt': started}), flush=True)
    while time.monotonic() < deadline:
        try:
            service = cmd.kube('get', 'service', 'agent-hook', '-n', 'zarf')
            selector = service.get('spec', {}).get('selector', {})
            if not selector or not all(valid(k, r'[a-zA-Z0-9_./-]+') and valid(v, r'[a-zA-Z0-9_.-]+') for k, v in selector.items()):
                raise Unavailable('service-selector')
            pods = cmd.kube('get', 'pods', '-n', 'zarf', '-l', ','.join(k+'='+v for k,v in sorted(selector.items())))
            if len(pods['items']) > 2:
                raise Unavailable('pod-limit')
            events = cmd.kube('get', 'events', '-n', 'zarf')
            for pod in pods['items']:
                current = identity(pod)
                failures = [e for e in events['items'] if live_failure(e, current, baseline, started)]
                if failures:
                    event = failures[0]
                    event_at = (event.get('series', {}).get('lastObservedTime') or event.get('lastTimestamp') or event.get('eventTime'))
                    record = {'watch': 'first-live-liveness-failure', 'observedAt': time.time(),
                              'eventAt': stamp(event_at), 'eventCount': count(event), **current}
                    try:
                        # Revalidate current UID/container immediately before node access.
                        fresh = identity(cmd.kube('get', 'pod', current['pod'], '-n', 'zarf'))
                        if fresh != current:
                            raise Unavailable('pod-changed-before-capture')
                        record['snapshot'] = snapshot(cmd, current)
                        if identity(cmd.kube('get', 'pod', current['pod'], '-n', 'zarf')) != current:
                            raise Unavailable('pod-changed-during-capture')
                    except Unavailable as error:
                        record['snapshot'] = {'unavailable': str(error)}
                    record['captureFinishedAt'] = time.time()
                    print(json.dumps(record), flush=True)
                    return 0
        except (Unavailable, KeyError, TypeError, AttributeError):
            # No raw error strings or API payloads escape this boundary.
            pass
        time.sleep(min(1, max(0, deadline-time.monotonic())))
    print(json.dumps({'watch': 'deadline', 'evidence': 'unavailable-or-no-new-failure', 'observedAt': time.time()}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-ephemeral-trial', action='store_true', required=True)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        parser.error('--seconds must be between 1 and 900')
    try:
        return observe(args.seconds)
    except (Unavailable, KeyError, TypeError, AttributeError):
        print('{"watch":"unavailable","stage":"initial-event-baseline"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
