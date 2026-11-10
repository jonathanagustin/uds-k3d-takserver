#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bind staged acceptance to this job's local, disposable k3d cluster."""

import argparse
import importlib.util
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

CONTEXT = 'k3d-uds'
NAMESPACE = 'kube-system'
MARKER = 'uds-ephemeral-trial'
REPOSITORY = 'jonathanagustin/uds-takserver'
NODE = 'k3d-uds-server-0'
GATEWAY = 'k3d-uds-serverlb'
FORMAT = ('{"id":{{json .Id}},"running":{{json .State.Running}},'
          '"labels":{{json .Config.Labels}},"ports":{{json .NetworkSettings.Ports}}}')
# The selected Core v1.16.0 checkpoint uses this direct node-local binary:
# packages/checkpoint-dev/checkpoint.sh (not a k3s subcommand).
NODE_UID_COMMAND = ['docker', 'exec', NODE, 'kubectl', 'get', 'namespace', NAMESPACE,
                    '-o', 'jsonpath={.metadata.uid}']


def node_uid_failure(returncode, stderr):
    """Classify bounded, whole-stream-redacted stderr; never publish its text."""
    classification = 'stderr-unavailable-or-oversized'
    if isinstance(stderr, bytes) and len(stderr) <= 65536:
        try:
            spec = importlib.util.spec_from_file_location(
                'ephemeral_redaction', Path(__file__).resolve().parents[1] / '.github/scripts/redact-logs.py')
            redactor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(redactor)
            safe, _ = redactor.redact_text(redactor.decode_log(stderr))
            # Registry authentication, signed URLs and authorization streams are
            # omitted as a whole, including any multiline continuation.
            if re.search(r'authorization|bearer|registry.*(?:auth|credential|token)|dockerconfigjson|'
                         r'\bauths\b|identitytoken|[?&](?:sig|signature|token|access_token)=|'
                         r'://[^\s/@]+:[^\s/@]+@', safe, re.IGNORECASE):
                classification = 'stderr-credential-bearing'
            else:
                classification = 'unclassified'
                for label, pattern in (
                    ('kubectl-unavailable', r'no help topic for [\"\']?kubectl|(?:exec:|executable file).*kubectl.*(?:not found|no such file)'),
                    ('kubeconfig-unavailable', r'(?:kubeconfig|k3s\.yaml).*(?:no such file|permission denied)|no configuration has been provided'),
                    ('tls-error', r'x509:|tls handshake|certificate.*(?:expired|unknown authority)'),
                    ('api-authentication-error', r'you must be logged in|unauthorized|forbidden'),
                    ('api-connection-error', r'connection refused|unable to connect to the server|i/o timeout|context deadline exceeded'),
                ):
                    if re.search(pattern, safe, re.IGNORECASE):
                        classification = label
                        break
        except Exception:
            classification = 'stderr-unsanitizable'
    print(json.dumps({'stage': 'node-namespace-uid', 'exit': returncode,
                      'stderr_bytes': len(stderr) if isinstance(stderr, bytes) else None,
                      'classification': classification}), file=sys.stderr)


def command(argv, input_text=None):
    try:
        result = subprocess.run(argv, input=input_text.encode() if input_text is not None else None,
                                capture_output=True, timeout=45)
    except subprocess.TimeoutExpired as error:
        if argv == NODE_UID_COMMAND:
            node_uid_failure('timeout', error.stderr)
        raise ValueError('ephemeral cluster identity command timed out') from None
    if result.returncode != 0 and argv == NODE_UID_COMMAND:
        node_uid_failure(result.returncode, result.stderr)
    require(result.returncode == 0, 'ephemeral cluster identity command failed')
    return result.stdout.decode('utf-8')


def require(value, message):
    if not value:
        raise ValueError(message)


def k(context, *args):
    return ['kubectl', '--context', context, *args]


def verify_local_docker(command):
    """Check endpoint configuration before any daemon call or cluster bootstrap."""
    require(not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT'),
            'Docker host/context overrides are not allowed for staged acceptance')
    require(command(['docker', 'context', 'show']).strip() == 'default',
            'current Docker context must be default')
    endpoint = json.loads(command(['docker', 'context', 'inspect', 'default', '--format',
                                   '{{json .Endpoints.docker.Host}}']))
    require(endpoint == 'unix:///var/run/docker.sock', 'Docker daemon endpoint must be the local Unix socket')
    return {'dockerContext': 'default', 'dockerEndpoint': endpoint}


def _run_identity(command):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY,
            'staged mutation requires this repository GitHub Actions job')
    run, attempt, sha = (os.environ.get(key, '') for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA'))
    require(re.fullmatch('[1-9][0-9]*', run) and re.fullmatch('[1-9][0-9]*', attempt)
            and re.fullmatch('[a-f0-9]{40}', sha), 'missing run, attempt or source identity')
    require(command(['git', 'rev-parse', 'HEAD']).strip() == sha, 'checkout differs from the reviewed workflow source')
    return run, attempt, sha


def verify_bootstrap(context, command):
    """Refuse reuse before any checkpoint bootstrap mutation."""
    require(context == CONTEXT, 'only the explicit k3d-uds test context is allowed')
    run, attempt, sha = _run_identity(command)
    endpoint = verify_local_docker(command)
    names = command(['docker', 'ps', '--all', '--filter', 'label=app=k3d',
                     '--filter', 'label=k3d.cluster=uds', '--format', '{{.Names}}']).strip()
    require(not names, 'staged bootstrap refuses an existing uds k3d container, including stopped containers')
    named = command(['docker', 'ps', '--all', '--filter', 'name=k3d-uds-', '--format', '{{.Names}}']).strip()
    require(not named, 'staged bootstrap refuses an existing named uds k3d container')
    contexts = command(['kubectl', 'config', 'get-contexts', '-o', 'name']).splitlines()
    require(CONTEXT not in contexts, 'staged bootstrap refuses an existing k3d-uds kubeconfig context')
    return {'schema': '1', 'purpose': 'staged-bootstrap', 'repository': REPOSITORY,
            'runID': run, 'runAttempt': attempt, 'sourceSHA': sha, 'context': context, **endpoint}


def _local_identity(context, command):
    require(context == CONTEXT, 'only the explicit k3d-uds test context is allowed')
    run, attempt, sha = _run_identity(command)
    verify_local_docker(command)
    require(command(['kubectl', 'config', 'current-context']).strip() == context,
            'current context differs; refusing tools that use the current context')
    endpoint = command(['kubectl', '--context', context, 'config', 'view', '--minify',
                        '-o', 'jsonpath={.clusters[0].cluster.server}']).strip()
    parsed = urlsplit(endpoint)
    host = parsed.hostname
    local = host == 'localhost'
    if host != 'localhost':
        try:
            local = ipaddress.ip_address(host).is_loopback or host == '0.0.0.0'
        except ValueError:
            local = False
    require(parsed.scheme == 'https' and local and parsed.port and not parsed.username and not parsed.password
            and parsed.path in ('', '/') and not parsed.query and not parsed.fragment, 'API endpoint is not local k3d HTTPS')
    names = command(['docker', 'ps', '--filter', 'label=app=k3d', '--filter', 'label=k3d.cluster=uds',
                     '--format', '{{.Names}}']).splitlines()
    require(NODE in names and set(names).issubset({NODE, GATEWAY}), 'unexpected local k3d node set')
    nodes = {}
    for name in names:
        value = json.loads(command(['docker', 'inspect', name, '--format', FORMAT]))
        require(value.get('running') is True and re.fullmatch('[a-f0-9]{64}', value.get('id', ''))
                and value.get('labels', {}).get('app') == 'k3d'
                and value['labels'].get('k3d.cluster') == 'uds', 'unrecognized local k3d container')
        nodes[name] = value
    require(any(str(binding.get('HostPort')) == str(parsed.port)
                for node in nodes.values() for binding in (node.get('ports', {}).get('6443/tcp') or [])),
            'selected API port is not published by this local k3d cluster')
    cluster = json.loads(command(k(context, 'get', 'namespace', NAMESPACE, '-o', 'json')))
    uid = cluster.get('metadata', {}).get('uid', '')
    require(re.fullmatch('[a-f0-9-]{36}', uid), 'missing cluster namespace UID')
    node_uid = command(NODE_UID_COMMAND).strip()
    require(node_uid == uid, 'context is not the cluster inside the local k3d node')
    return {'schema': '1', 'purpose': 'staged-acceptance', 'repository': REPOSITORY,
            'runID': run, 'runAttempt': attempt, 'sourceSHA': sha, 'context': context,
            'clusterUID': uid, 'nodeContainerID': nodes[NODE]['id']}


def _marker(context, command):
    output = command(k(context, 'get', 'configmap', MARKER, '-n', NAMESPACE, '--ignore-not-found', '-o', 'json'))
    return json.loads(output) if output.strip() else None


def _check_marker(marker, expected):
    require(marker is not None and marker.get('kind') == 'ConfigMap', 'ephemeral trial marker is missing')
    meta = marker.get('metadata', {})
    require(meta.get('name') == MARKER and meta.get('namespace') == NAMESPACE and not meta.get('deletionTimestamp')
            and meta.get('labels', {}).get('app.kubernetes.io/part-of') == 'uds-staged-acceptance',
            'ephemeral trial marker is not current')
    require(marker.get('data') == expected, 'marker belongs to another run, source or cluster')
    require(meta.get('uid') and meta.get('resourceVersion'), 'marker has no API identity')
    return {**expected, 'markerUID': meta['uid'], 'markerResourceVersion': meta['resourceVersion']}


def verify(context, command):
    """Read-only guard. command(argv, input_text=None) returns stdout or raises."""
    expected = _local_identity(context, command)
    return _check_marker(_marker(context, command), expected)


def mark(context, command):
    """Create only a matching local-job marker; never overwrite an existing one."""
    expected = _local_identity(context, command)
    previous = _marker(context, command)
    if previous is not None:
        return _check_marker(previous, expected)
    marker = {'apiVersion': 'v1', 'kind': 'ConfigMap',
              'metadata': {'name': MARKER, 'namespace': NAMESPACE,
                           'labels': {'app.kubernetes.io/part-of': 'uds-staged-acceptance'}}, 'data': expected}
    command(k(context, 'create', '-f', '-', '-o', 'json'), json.dumps(marker))
    return verify(context, command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('docker', 'bootstrap', 'mark', 'verify'))
    parser.add_argument('--context', choices=(CONTEXT,), required=True)
    args = parser.parse_args()

    result = (verify_local_docker(command) if args.operation == 'docker'
              else {'bootstrap': verify_bootstrap, 'mark': mark, 'verify': verify}[args.operation](args.context, command))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
