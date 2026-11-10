#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded CI-only availability probe through the authenticated Kubernetes API."""
import argparse
import ipaddress
import json
import re
import subprocess
import sys
import time

NAMESPACE = 'zarf'
SERVICE = 'agent-hook'
PORT = 8443
TOTAL_SECONDS = 30


class Unavailable(Exception):
    pass


def kubectl(arguments, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Unavailable('live health deadline reached')
    try:
        result = subprocess.run(
            ['uds', 'zarf', 'tools', 'kubectl', '--request-timeout=3s', '-n', NAMESPACE, *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=min(4, remaining), check=False)
    except subprocess.TimeoutExpired as error:
        raise Unavailable('Kubernetes API request timed out') from error
    # Never emit raw API bodies or stderr into CI logs.
    if result.returncode:
        raise Unavailable('Kubernetes API request failed or was denied')
    return result.stdout


def object_metadata(obj, name):
    meta = obj.get('metadata', {})
    if meta.get('name') != name or meta.get('namespace') != NAMESPACE or meta.get('deletionTimestamp'):
        raise Unavailable('unexpected or terminating target object')
    return meta


def targets(service, endpoints):
    object_metadata(service, SERVICE)
    object_metadata(endpoints, SERVICE)
    selector = service.get('spec', {}).get('selector', {})
    if not selector or not all(isinstance(k, str) and isinstance(v, str) for k, v in selector.items()):
        raise Unavailable('agent Service has no valid selector')
    if not any(p.get('targetPort') == PORT and p.get('protocol', 'TCP') == 'TCP'
               for p in service.get('spec', {}).get('ports', [])):
        raise Unavailable('agent Service target port differs')
    found = {}
    for subset in endpoints.get('subsets', []):
        if not any(p.get('port') == PORT and p.get('protocol', 'TCP') == 'TCP' for p in subset.get('ports', [])):
            continue
        # notReadyAddresses are deliberately never candidates.
        for address in subset.get('addresses', []):
            ref = address.get('targetRef', {})
            name, uid = ref.get('name', ''), ref.get('uid', '')
            if (ref.get('kind') != 'Pod' or ref.get('namespace') != NAMESPACE
                    or ref.get('apiVersion', 'v1') != 'v1'
                    or not isinstance(name, str) or len(name) > 253
                    or not all(len(label) <= 63 and re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label)
                               for label in name.split('.'))
                    or not isinstance(uid, str) or not uid):
                raise Unavailable('ready endpoint has an invalid Pod reference')
            ip = str(ipaddress.ip_address(address['ip']))
            if name in found and found[name] != (uid, ip):
                raise Unavailable('conflicting ready endpoint identity')
            found[name] = (uid, ip)
    if not found or len(found) > 8:
        raise Unavailable('expected between one and eight ready agent Pods')
    return selector, found


def validate_pod(pod, name, uid, ip, selector):
    meta = object_metadata(pod, name)
    status = pod.get('status', {})
    if (meta.get('uid') != uid or str(ipaddress.ip_address(status.get('podIP', ''))) != ip
            or any(meta.get('labels', {}).get(k) != v for k, v in selector.items())
            or status.get('phase') != 'Running'
            or not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in status.get('conditions', []))):
        raise Unavailable('ready endpoint does not match a current ready Service Pod')


def require_two_deployment(deployment):
    meta = object_metadata(deployment, SERVICE)
    status = deployment.get('status', {})
    if (not meta.get('uid') or deployment.get('spec', {}).get('replicas') != 2
            or status.get('observedGeneration', 0) < meta.get('generation', 1)
            or any(status.get(key) != 2 for key in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas'))
            or status.get('unavailableReplicas', 0) != 0):
        raise Unavailable('two current agent replicas have not fully converged')
    return meta['uid'], meta['generation']


def require_owned_pod(pod, replica_sets):
    controllers = [owner for owner in pod.get('metadata', {}).get('ownerReferences', []) if owner.get('controller') is True]
    if len(controllers) != 1 or controllers[0].get('kind') != 'ReplicaSet' or controllers[0].get('uid') not in replica_sets:
        raise Unavailable('agent endpoint Pod is not controlled by the current deployment')


def two_replica_targets(get, selector, ready):
    deployment = get('deployment', SERVICE)
    identity = require_two_deployment(deployment)
    labels = ','.join(f'{key}={value}' for key, value in sorted(selector.items()))
    pods = get('pods', None, labels)['items']
    sets = get('replicasets', None, labels)['items']
    owned_sets = set()
    for replica_set in sets:
        meta = replica_set.get('metadata', {})
        if (not meta.get('deletionTimestamp') and meta.get('namespace') == NAMESPACE
                and any(owner.get('kind') == 'Deployment' and owner.get('controller') is True
                        and owner.get('uid') == identity[0] for owner in meta.get('ownerReferences', []))):
            owned_sets.add(meta.get('uid'))
    if (len(pods) != 2 or len(ready) != 2
            or {pod.get('metadata', {}).get('name') for pod in pods} != set(ready)
            or len({uid for uid, _ in ready.values()}) != 2):
        raise Unavailable('two current ready agent endpoint Pods are required')
    for pod in pods:
        name = pod.get('metadata', {}).get('name')
        if name not in ready:
            raise Unavailable('a selected agent Pod is missing from ready endpoints')
        uid, ip = ready[name]
        validate_pod(pod, name, uid, ip, selector)
        require_owned_pod(pod, owned_sets)
    return identity, owned_sets


def probe_once(deadline, request=kubectl, require_two=False):
    def get(kind, name, selector=None):
        arguments = ['get', kind]
        if name:
            arguments.append(name)
        arguments += ['-o', 'json']
        if selector:
            arguments += ['-l', selector]
        return json.loads(request(arguments, deadline))
    selector, ready = targets(get('service', SERVICE), get('endpoints', SERVICE))
    identity, owned_sets = two_replica_targets(get, selector, ready) if require_two else (None, None)
    for name, (uid, ip) in sorted(ready.items()):
        validate_pod(get('pod', name), name, uid, ip, selector)
        path = f'/api/v1/namespaces/{NAMESPACE}/pods/https:{name}:{PORT}/proxy/healthz'
        if request(['get', '--raw=' + path], deadline) != b'ok':
            raise Unavailable('agent live health response was not exactly ok')
        # Refuse a Pod identity change across the live request.
        current = get('pod', name)
        validate_pod(current, name, uid, ip, selector)
        if require_two:
            require_owned_pod(current, owned_sets)
    if require_two:
        if require_two_deployment(get('deployment', SERVICE)) != identity:
            raise Unavailable('agent deployment identity changed across live probes')
        after_selector, after_ready = targets(get('service', SERVICE), get('endpoints', SERVICE))
        if after_selector != selector or after_ready != ready:
            raise Unavailable('agent ready endpoints changed across live probes')
    return len(ready)


def main(argv=()):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-two-replicas', action='store_true', help='require both current deployment replicas and live responses')
    args = parser.parse_args(argv)
    deadline = time.monotonic() + TOTAL_SECONDS
    reason = 'no successful live response'
    while time.monotonic() < deadline:
        try:
            count = probe_once(deadline, require_two=True) if args.require_two_replicas else probe_once(deadline)
            print(f'Agent live HTTPS health passed for {count} ready Pod(s) through the Kubernetes API')
            return 0
        except (Unavailable, ValueError, KeyError, TypeError) as error:
            reason = str(error) if isinstance(error, Unavailable) else 'invalid target metadata'
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))
    print('Agent live HTTPS health failed: ' + reason, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
