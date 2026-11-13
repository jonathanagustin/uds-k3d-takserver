#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Disposable #32 acceptance harness; never a production Helm migration tool."""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import ssl
import shutil
import tempfile
import urllib.request
import urllib.parse
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
APPS = ('takserver-api', 'takserver-config', 'takserver-messaging', 'takserver-plugins')
LEGACY = 'takserver-ignite'
UUID = 'pepr-c72fcf944a4f43bbb386d22371aa640f'
PEPR = (UUID, UUID + '-watcher')
NS = 'takserver'
CONTEXT = 'k3d-uds'
PHASES = ('shared', 'transition', 'strict', 'rollback')
ROLE_NAMES = {'takserver-workload-discovery', 'takserver-config-ignite-log'}
RBAC = {('ServiceAccount', app) for app in APPS} | {('Role', name) for name in ROLE_NAMES} | {
    ('RoleBinding', app + '-discovery') for app in APPS} | {('RoleBinding', 'takserver-config-ignite-log')}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def ready(obj):
    require(not obj['metadata'].get('deletionTimestamp'), 'terminating resource')
    require(obj.get('status', {}).get('observedGeneration') == obj['metadata']['generation'], 'stale resource generation')


def helm_owner(obj, release, namespace):
    meta = obj['metadata']
    require(meta.get('annotations', {}).get('meta.helm.sh/release-name') == release and
            meta.get('annotations', {}).get('meta.helm.sh/release-namespace') == namespace and
            meta.get('labels', {}).get('app.kubernetes.io/managed-by') == 'Helm', 'unexpected Helm owner')


def validate_policies(package, policies, network_policies, baseline_network):
    ready(package)
    require(package['status'].get('phase') == 'Ready', 'Package not Ready')
    generation = str(package['metadata']['generation'])
    rules = package['spec']['network']['allow']
    affected = [r for r in rules if r.get('direction') == 'Ingress' and r.get('remoteSelector', {}).get('app') in APPS]
    require(affected, 'no identity-scoped ingress rules')
    targets = {(sha(r['selector']), int(r['port'])): r['selector'] for r in affected}
    expected = set()
    for rule in rules:
        if rule.get('direction') != 'Ingress' or (sha(rule.get('selector', {})), int(rule.get('port', -1))) not in targets:
            continue
        account = rule.get('remoteServiceAccount')
        require(account and not rule.get('remoteGenerated'), 'unsupported identity rule contract')
        principal = 'cluster.local/ns/' + rule.get('remoteNamespace', NS) + '/sa/' + account
        expected.add((sha(rule['selector']), int(rule['port']), principal))
    actual = set()
    for policy in policies:
        spec = policy['spec']
        if spec.get('action', 'ALLOW') != 'ALLOW':
            continue
        selector = spec.get('selector', {}).get('matchLabels', {})
        # Package selectors do not enumerate every label on destination Pods.
        # An additional policy label is therefore unknown, not a disjointness
        # proof. Only a conflicting value for a known label excludes overlap.
        relevant = [(key, labels) for key, labels in targets.items()
                    if all(k not in labels or labels[k] == v for k, v in selector.items())]
        if not relevant:
            continue
        for rule in spec.get('rules', []):
            operations = [t.get('operation', {}) for t in rule.get('to', [])]
            ports = {int(p) for op in operations for p in op.get('ports', []) if str(p).isdigit()}
            applicable = [key for key, _ in relevant if not operations or not ports or key[1] in ports]
            if not applicable:
                continue
            meta = policy['metadata']
            require(not meta.get('deletionTimestamp') and meta.get('namespace', NS) == NS and meta.get('labels', {}).get('uds/package') == NS and
                    meta.get('labels', {}).get('uds/generation') == generation, 'stale or foreign overlapping policy')
            allowed_ports = {key[1] for key, _ in relevant if key[0] == sha(selector)}
            require(all(re.fullmatch(r'[1-9][0-9]*', str(port)) and 1 <= int(port) <= 65535
                        for op in operations for port in op.get('ports', [])) and ports <= allowed_ports,
                    'extra, wildcard or invalid operation port')
            require(not rule.get('when') and operations and ports and all(set(op) == {'ports'} for op in operations),
                    'unsupported or broad operation')
            require(rule.get('from'), 'broad source policy')
            for source in rule['from']:
                source = source.get('source', {})
                require(set(source) == {'principals'} and source['principals'], 'non-principal source')
                for key in applicable:
                    require(sha(selector) == key[0], 'broader destination selector')
                    for principal in source['principals']:
                        require('*' not in principal, 'wildcard principal')
                        actual.add((key[0], key[1], principal))
    require(actual == expected, 'generated policy identities/ports differ from requested rules')
    network = set()
    for policy in network_policies:
        meta = policy['metadata']
        require(not meta.get('deletionTimestamp') and meta.get('labels', {}).get('uds/generation') == generation,
                'stale or terminating NetworkPolicy')
        network.add(sha(policy['spec']))
    require(network and sorted(network) == baseline_network, 'label/port NetworkPolicy changed during identity-only trial')
    return sha(sorted(actual))


def validate_workloads(deployments, replicasets, pods, account, baseline_uids):
    by_uid = {r['metadata']['uid']: r for r in replicasets}
    identities = []
    for app in APPS:
        deployment = next(d for d in deployments if d['metadata']['name'] == app)
        require(deployment['metadata']['uid'] == baseline_uids[app], 'Deployment replaced')
        helm_owner(deployment, 'takserver', NS)
        ready(deployment)
        desired = deployment['spec'].get('replicas', 1)
        require(desired > 0 and deployment['status'].get('updatedReplicas') == desired and
                deployment['status'].get('readyReplicas') == desired and
                deployment['status'].get('availableReplicas') == desired and
                deployment['status'].get('replicas') == desired and
                deployment['status'].get('unavailableReplicas', 0) == 0, 'mixed or incomplete rollout')
        expected = app if account == 'dedicated' else LEGACY
        require(deployment['spec']['template']['spec'].get('serviceAccountName') == expected, 'wrong Deployment identity')
        owners = {r['metadata']['uid'] for r in replicasets if any(
            o.get('controller') is True and o.get('uid') == baseline_uids[app]
            for o in r['metadata'].get('ownerReferences', []))}
        active = [r for r in replicasets if r['metadata']['uid'] in owners and r['spec'].get('replicas', 1) > 0]
        require(len(active) == 1 and active[0]['spec'].get('replicas', 1) == desired and
                not active[0]['metadata'].get('deletionTimestamp') and
                active[0]['spec']['template']['spec'].get('serviceAccountName') == expected, 'mixed or stale active ReplicaSets')
        require(template_fingerprint(active[0]) == template_fingerprint(deployment), 'active ReplicaSet template drift')
        relevant = [p for p in pods if p['metadata'].get('labels', {}).get('app') == app or any(
            o.get('uid') in owners for o in p['metadata'].get('ownerReferences', []))]
        require(len(relevant) == desired, 'stale, extra, missing or terminating workload Pods')
        for pod in relevant:
            meta = pod['metadata']
            require(not meta.get('deletionTimestamp') and meta.get('labels', {}).get('app') == app, 'terminating or mislabeled Pod')
            controllers = [o for o in meta.get('ownerReferences', []) if o.get('controller') is True]
            require(len(controllers) == 1 and controllers[0].get('uid') in owners, 'foreign or standalone workload Pod')
            require(controllers[0]['uid'] == active[0]['metadata']['uid'],
                    'workload Pod is owned by an inactive ReplicaSet')
            rs = by_uid[controllers[0]['uid']]
            require(not rs['metadata'].get('deletionTimestamp') and
                    rs['spec']['template']['spec'].get('serviceAccountName') == expected, 'stale ReplicaSet identity')
            require(pod['spec'].get('serviceAccountName') == expected and pod['status'].get('phase') == 'Running' and any(
                c.get('type') == 'Ready' and c.get('status') == 'True' for c in pod['status'].get('conditions', [])), 'Pod identity/readiness mismatch')
            require(meta.get('annotations', {}).get('ambient.istio.io/redirection') == 'enabled', 'Pod not enrolled in ambient mesh')
            identities.append({'app': app, 'name': meta['name'], 'uid': meta['uid'], 'account': expected,
                               'resourceVersion': meta['resourceVersion'], 'controllerReplicaSetUID': controllers[0]['uid']})
    return identities


def validate_rbac(resources):
    require(len(resources) == len(RBAC) and {(r['kind'], r['metadata']['name']) for r in resources} == RBAC, 'unexpected dedicated RBAC render')
    discovery = [{'apiGroups': [''], 'resources': ['pods', 'endpoints'], 'verbs': ['get', 'list', 'watch']},
                 {'apiGroups': ['apps'], 'resources': ['deployments'], 'verbs': ['get', 'list', 'watch']}]
    logs = [{'apiGroups': [''], 'resources': ['pods/log'], 'resourceNames': ['takserver-ignite-0'], 'verbs': ['get']}]
    for resource in resources:
        kind, name = resource['kind'], resource['metadata']['name']
        require(resource['metadata'].get('namespace', NS) == NS and resource.get('apiVersion') ==
                ('v1' if kind == 'ServiceAccount' else 'rbac.authorization.k8s.io/v1'), 'RBAC namespace/API group changed')
        if kind == 'Role':
            require(resource.get('rules') == (discovery if name == 'takserver-workload-discovery' else logs),
                    'dedicated Role permissions changed')
        elif kind == 'RoleBinding':
            account = 'takserver-config' if name == 'takserver-config-ignite-log' else name.removesuffix('-discovery')
            role = 'takserver-config-ignite-log' if name == 'takserver-config-ignite-log' else 'takserver-workload-discovery'
            require(resource.get('roleRef') == {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': role} and
                    resource.get('subjects') == [{'kind': 'ServiceAccount', 'name': account, 'namespace': NS}],
                    'dedicated RoleBinding target changed')
        else:
            require(set(resource) <= {'apiVersion', 'kind', 'metadata'}, 'unexpected dedicated ServiceAccount fields')


def package_invariant(package):
    spec = copy.deepcopy(package['spec'])
    spec['network'].pop('allow', None)
    return sha(spec)


def template_fingerprint(deployment, pepr=False):
    template = copy.deepcopy(deployment['spec']['template'])
    template.get('metadata', {}).get('labels', {}).pop('pod-template-hash', None)
    if pepr:
        for container in template['spec']['containers']:
            for env in container.get('env', []):
                if env['name'] == 'TAK_WORKLOAD_IDENTITY_PHASE':
                    require(env.get('value') in PHASES and 'valueFrom' not in env, 'unknown Pepr phase')
                    env['value'] = '<phase>'
    else:
        template['spec'].pop('serviceAccountName', None)
    return sha(template)


class Driver:
    def __init__(self, evidence):
        self.evidence = evidence
        self.state = {'schema': 1, 'stages': [], 'created': [], 'completed': False, 'accepted': False, 'recoveryOnly': False}
        self.guard_module = None
        self.deadline = time.monotonic() + 2400

    def guard(self):
        require(time.monotonic() < self.deadline, '40-minute trial wall budget exhausted')
        if self.guard_module is None:
            for relative in ('tests/workload-identities/drive.py', 'tests/workload-identities/ProtocolProbe.java', 'tests/ephemeral-cluster.py'):
                reviewed = self.command(['git', 'show', 'HEAD:' + relative])
                require(reviewed.encode() == (ROOT / relative).read_bytes(), 'consumed trial code differs from reviewed HEAD')
            path = ROOT / 'tests/ephemeral-cluster.py'
            require(path.is_file(), 'reviewed ephemeral-cluster guard is required')
            spec = importlib.util.spec_from_file_location('ephemeral_guard', path)
            self.guard_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.guard_module)
        receipt = self.guard_module.verify(CONTEXT, self.command)
        if 'guard' in self.state:
            require(receipt == self.state['guard'], 'ephemeral marker or cluster/job identity changed')
        return receipt

    def command(self, args, payload=None, timeout=45):
        result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=timeout)
        require(result.returncode == 0, 'command failed: ' + args[0] + ' ' + args[1])
        return result.stdout

    def kube(self, *args, payload=None, mutate=False):
        if mutate:
            self.guard()
        return self.command(['uds', 'zarf', 'tools', 'kubectl', '--context', CONTEXT, *args], payload)

    def get(self, kind, name=None, namespace=NS, labels=None):
        args = ['get', kind, '-n', namespace]
        if name:
            args.append(name)
        if labels:
            args += ['-l', labels]
        return json.loads(self.kube(*args, '-o', 'json'))

    def patch(self, kind, obj, path, value, namespace=NS):
        allowed = (namespace == NS and ((kind == 'package' and obj['metadata']['name'] == NS) or
                   (kind == 'deployment' and obj['metadata']['name'] in APPS))) or (
                   namespace == 'pepr-system' and kind == 'deployment' and obj['metadata']['name'] in PEPR) or (
                   namespace == NS and kind == 'Pod' and path == '/metadata/labels' and any(
                       e['kind'] == 'Pod' and e['name'] == obj['metadata']['name'] and e['uid'] == obj['metadata']['uid']
                       for e in self.state['created']))
        require(allowed, 'mutation outside exact resource scope')
        require((kind == 'package' and path == '/spec/network/allow') or
                (kind == 'deployment' and namespace == NS and path == '/metadata/annotations') or
                (kind == 'deployment' and namespace == 'pepr-system' and re.fullmatch(r'/spec/template/spec/containers/[0-9]+/env/[0-9]+/value', path)) or
                (kind == 'Pod' and path == '/metadata/labels'), 'mutation outside exact field scope')
        operations = [{'op': 'test', 'path': '/metadata/uid', 'value': obj['metadata']['uid']},
                      {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']}]
        old = obj
        for component in path.strip('/').split('/'):
            old = old[int(component)] if isinstance(old, list) else old[component.replace('~1', '/').replace('~0', '~')]
        operations += [{'op': 'test', 'path': path, 'value': old}, {'op': 'replace', 'path': path, 'value': value}]
        return json.loads(self.kube('patch', kind, obj['metadata']['name'], '-n', namespace, '--type=json',
                                   '-p', json.dumps(operations), '-o', 'json', mutate=True))

    def journal(self, stage, **receipt):
        self.state['stages'].append({'stage': stage, **receipt})
        temporary = self.evidence.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True) + '\n')
        temporary.chmod(0o600)
        temporary.replace(self.evidence)

    def wait(self, callback, seconds=300):
        deadline = time.monotonic() + seconds
        last = 'no observation'
        stable, fingerprint = 0, None
        while time.monotonic() < deadline:
            self.guard()
            try:
                result = callback()
                current = sha(result)
                stable = stable + 1 if current == fingerprint else 1
                fingerprint = current
                if stable >= 3:
                    return result
            except ValueError as error:
                stable, fingerprint, last = 0, None, str(error)
            time.sleep(3)
        raise ValueError('convergence timeout: ' + last)

    def render(self, phase):
        values = copy.deepcopy(self.values)
        values['workloadIdentityPhase'] = phase
        text = self.command(['helm', 'template', 'uds-takserver-config', str(ROOT / 'charts/takserver'),
                             '--namespace', NS, '--values', '-'], json.dumps(values))
        docs = [d for d in yaml.safe_load_all(text) if d]
        package = next(d for d in docs if d['kind'] == 'Package' and d['metadata']['name'] == NS)
        return package, [d for d in docs if (d['kind'], d['metadata']['name']) in RBAC]

    def policies(self):
        package = self.get('package', NS)
        require(package['metadata']['uid'] == self.state['packageUID'] and
                package['spec']['network']['allow'] == self.state['currentAllow'], 'requested Package UID/rules changed')
        require(package_invariant(package) == self.state['packageInvariant'], 'unrelated Package specification drift')
        mesh = self.get('configmap', 'istio', 'istio-system')
        require(mesh['metadata']['uid'] == self.state['meshConfigUID'] and sha(mesh.get('data', {}).get('mesh')) == self.state['meshConfigHash'],
                'Istio mesh/root-namespace configuration changed')
        policies = self.get('authorizationpolicies.security.istio.io')['items']
        policies += self.get('authorizationpolicies.security.istio.io', namespace='istio-system')['items']
        network = self.get('networkpolicies', labels='uds/package=' + NS)['items']
        return validate_policies(package, policies, network, self.state['baselineNetwork'])

    def identities(self, account):
        deployments = self.get('deployments')['items']
        for deployment in deployments:
            app = deployment['metadata']['name']
            if app in APPS:
                require(template_fingerprint(deployment) == self.state['templateFingerprints'][app], 'workload template drift')
        return validate_workloads(deployments, self.get('replicasets')['items'],
                                  self.get('pods')['items'], account, self.state['deploymentUIDs'])

    def stage_config(self, phase):
        if phase in ('strict', 'shared'):
            self.wait(lambda: self.identities('dedicated' if phase == 'strict' else 'shared'))
        current = self.get('package', NS)
        require(current['metadata']['uid'] == self.state['packageUID'], 'Package replaced')
        require(package_invariant(current) == self.state['packageInvariant'], 'unrelated Package specification drift')
        require(current['spec']['network']['allow'] == self.state['currentAllow'], 'concurrent Package rule drift')
        desired, _ = self.render(phase)
        require(desired['spec']['network']['allow'] == self.state['phaseRules'][phase], 'rendered phase rules changed')
        self.patch('package', current, '/spec/network/allow', desired['spec']['network']['allow'])
        self.state['currentAllow'] = desired['spec']['network']['allow']
        self.journal('config-requested-' + phase)
        fingerprint = self.wait(self.policies)
        self.journal('policy-converged-' + phase, policyFingerprint=fingerprint)

    def stage_admission(self, phase):
        for name in PEPR:
            self.policies()
            deployment = self.get('deployment', name, 'pepr-system')
            require(deployment['metadata']['uid'] == self.state['peprUIDs'][name], 'Pepr Deployment replaced')
            helm_owner(deployment, 'takserver-oidc', 'pepr-system')
            require(template_fingerprint(deployment, True) == self.state['peprTemplateFingerprints'][name], 'Pepr template drift')
            locations = [(i, j) for i, container in enumerate(deployment['spec']['template']['spec']['containers'])
                         for j, env in enumerate(container.get('env', [])) if env['name'] == 'TAK_WORKLOAD_IDENTITY_PHASE']
            require(len(locations) == 1, 'ambiguous Pepr phase environment')
            i, j = locations[0]
            env = deployment['spec']['template']['spec']['containers'][i]['env'][j]
            require(env.get('value') in PHASES and 'valueFrom' not in env, 'unknown Pepr phase')
            self.patch('deployment', deployment, f'/spec/template/spec/containers/{i}/env/{j}/value', phase, 'pepr-system')
        def pepr_ready():
            result = []
            for name in PEPR:
                deployment = self.get('deployment', name, 'pepr-system')
                ready(deployment)
                count = deployment['spec'].get('replicas', 1)
                require(count > 0 and deployment['status'].get('replicas') == count and
                        deployment['status'].get('updatedReplicas') == count and
                        deployment['status'].get('readyReplicas') == count and deployment['status'].get('availableReplicas') == count and
                        deployment['status'].get('unavailableReplicas', 0) == 0, 'Pepr rollout incomplete')
                replicasets = self.get('replicasets', namespace='pepr-system')['items']
                rsuids = {r['metadata']['uid'] for r in replicasets if any(o.get('controller') is True and
                          o.get('uid') == deployment['metadata']['uid'] for o in r['metadata'].get('ownerReferences', []))}
                selector = deployment['spec'].get('selector', {}).get('matchLabels', {})
                require(selector, 'Pepr selector is empty')
                pods = [p for p in self.get('pods', namespace='pepr-system')['items'] if any(
                    o.get('uid') in rsuids for o in p['metadata'].get('ownerReferences', [])) or
                    all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())]
                require(len(pods) == count, 'stale or mixed Pepr Pods')
                for pod in pods:
                    owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller') is True]
                    require(len(owners) == 1 and owners[0].get('uid') in rsuids, 'foreign Pepr Pod matches the selector')
                    require(not pod['metadata'].get('deletionTimestamp') and pod['spec'].get('serviceAccountName') == name and
                            pod['status'].get('phase') == 'Running' and any(c.get('type') == 'Ready' and c.get('status') == 'True'
                            for c in pod['status'].get('conditions', [])), 'Pepr Pod identity/readiness mismatch')
                    phases = [e.get('value') for c in pod['spec']['containers'] for e in c.get('env', [])
                              if e['name'] == 'TAK_WORKLOAD_IDENTITY_PHASE']
                    require(phases == [phase], 'old Pepr phase Pod remains')
                active = [r for r in replicasets if r['metadata']['uid'] in rsuids and r['spec'].get('replicas', 1) > 0]
                require(len(active) == 1 and active[0]['spec'].get('replicas', 1) == count and
                        not active[0]['metadata'].get('deletionTimestamp') and
                        template_fingerprint(active[0], True) == template_fingerprint(deployment, True), 'mixed active Pepr ReplicaSets')
                result.append((name, deployment['metadata']['generation'], sorted(p['metadata']['uid'] for p in pods)))
            return result
        self.wait(pepr_ready)
        # A real existing Deployment update exercises the installed mutating adapter.
        for app in APPS:
            self.policies()
            deployment = self.get('deployment', app)
            annotations = dict(deployment['metadata'].get('annotations', {}))
            annotations['uds.dev/identity-trial'] = self.state['trialID'] + '-' + phase
            self.patch('deployment', deployment, '/metadata/annotations', annotations)
        account = 'dedicated' if phase in ('transition', 'strict') else 'shared'
        identities = self.wait(lambda: self.identities(account))
        self.journal('workloads-' + phase, pods=identities)
        return identities

    def create(self, obj):
        obj = copy.deepcopy(obj)
        kind, name = obj['kind'], obj['metadata']['name']
        require((kind, name) in RBAC or (kind in ('Job', 'ServiceAccount') and name.startswith(self.state['trialID'])),
                'create outside trial resource scope')
        obj['metadata']['namespace'] = NS
        obj['metadata'].setdefault('labels', {})['uds.dev/identity-trial'] = self.state['trialID']
        # create, not apply: any pre-existing owner/name is a refusal.
        created = json.loads(self.kube('create', '-f', '-', '-o', 'json', payload=json.dumps(obj), mutate=True))
        item = {'kind': kind, 'name': name, 'uid': created['metadata']['uid']}
        self.state['created'].append(item)
        self.journal('created', resource=item)
        return created

    def delete_created(self, kind, name):
        require((kind, name) in RBAC or (kind in ('Pod', 'Job', 'ServiceAccount') and
                name.startswith(self.state['trialID'] + '-') and re.fullmatch(r'[a-z0-9-]{1,63}', name)),
                'delete outside exact trial resource scope')
        entry = next(e for e in reversed(self.state['created']) if e['kind'] == kind and e['name'] == name and not e.get('deleted'))
        if kind == 'Pod' and entry.get('controllerJobName'):
            require(not self.kube('get', 'job', entry['controllerJobName'], '-n', NS, '--ignore-not-found', '-o', 'json').strip(),
                    'delete the exact controlling Job before Pod cleanup')
        output = self.kube('get', kind, name, '-n', NS, '--ignore-not-found', '-o', 'json')
        if not output.strip():
            entry['deleted'] = True
            self.journal('already-absent', resource=entry)
            return
        obj = json.loads(output)
        meta = obj['metadata']
        if kind == 'Job':
            children = [p for p in self.get('pods')['items'] if any(o.get('controller') is True and o.get('uid') == entry['uid']
                        for o in p['metadata'].get('ownerReferences', []))]
            known = {e['uid'] for e in self.state['created'] if e['kind'] == 'Pod' and e.get('controllerJobUID') == entry['uid']}
            require(all(p['metadata']['uid'] in known for p in children), 'unrecorded Job child; manual recovery review required')
        if kind == 'Pod' and entry.get('controllerJobUID'):
            owners = [o for o in meta.get('ownerReferences', []) if o.get('controller') is True]
            require(len(owners) == 1 and owners[0].get('kind') == 'Job' and owners[0].get('uid') == entry['controllerJobUID'],
                    'control Pod was adopted; refusing deletion')
        require(meta['uid'] == entry['uid'] and meta.get('labels', {}).get('uds.dev/identity-trial') == self.state['trialID'],
                'refusing to delete foreign/replaced trial object')
        self.guard()
        # kubectl delete has no UID/resourceVersion precondition flags. Use the
        # actual local k3d API with DeleteOptions; never check-then-blind-delete.
        config = json.loads(self.command(['kubectl', '--context', CONTEXT, 'config', 'view', '--minify', '--raw', '-o', 'json']))
        require(len(config['clusters']) == 1 and len(config['users']) == 1, 'ambiguous local kubeconfig')
        cluster, user = config['clusters'][0]['cluster'], config['users'][0]['user']
        host = urllib.parse.urlsplit(cluster['server'])
        require(host.scheme == 'https' and host.hostname in ('127.0.0.1', 'localhost', '0.0.0.0', '::1') and not host.username,
                'delete endpoint is not local k3d')
        require(set(user) == {'client-certificate-data', 'client-key-data'} and cluster.get('certificate-authority-data'),
                'delete requires the local certificate-only k3d kubeconfig')
        context = ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data']).decode())
        with tempfile.TemporaryDirectory(prefix='uds-identity-client-') as directory:
            cert, key = Path(directory) / 'client.crt', Path(directory) / 'client.key'
            for path, field in ((cert, 'client-certificate-data'), (key, 'client-key-data')):
                path.write_bytes(base64.b64decode(user[field], validate=True))
                path.chmod(0o600)
            context.load_cert_chain(cert, key)
            plurals = {'Pod': 'pods', 'ServiceAccount': 'serviceaccounts', 'Role': 'roles', 'RoleBinding': 'rolebindings', 'Job': 'jobs'}
            require(kind in plurals and re.fullmatch('[a-z0-9-]+', name), 'unsupported deletion kind/name')
            prefix = '/api/v1' if kind in ('Pod', 'ServiceAccount') else ('/apis/batch/v1' if kind == 'Job' else '/apis/rbac.authorization.k8s.io/v1')
            endpoint = cluster['server'].rstrip('/') + prefix + '/namespaces/' + NS + '/' + plurals[kind] + '/' + name
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                       'preconditions': {'uid': meta['uid'], 'resourceVersion': meta['resourceVersion']},
                       'propagationPolicy': 'Foreground'}
            request = urllib.request.Request(endpoint, data=json.dumps(options).encode(), method='DELETE',
                                             headers={'Content-Type': 'application/json'})
            # This endpoint was bound to the local Docker node by the shared guard.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
            with opener.open(request, timeout=30) as response:
                require(response.status in (200, 202), 'conditional delete rejected')
        def gone():
            output = self.kube('get', kind, name, '-n', NS, '--ignore-not-found', '-o', 'json')
            require(not output.strip(), 'trial resource deletion is incomplete')
            return {'deletedUID': meta['uid']}
        self.wait(gone, 90)
        entry['deleted'] = True
        self.journal('deleted', resource=entry)

    def control_job(self, manifest, source_labels):
        job = self.create({'apiVersion': 'batch/v1', 'kind': 'Job',
            'metadata': copy.deepcopy(manifest['metadata']),
            'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 180, 'parallelism': 1, 'completions': 1,
                     'template': {'metadata': {'labels': {'app': 'identity-control',
                                  'uds.dev/identity-trial': self.state['trialID']}}, 'spec': manifest['spec']}}})
        def owned_pod():
            pods = self.get('pods', labels='batch.kubernetes.io/job-name=' + job['metadata']['name'])['items']
            require(len(pods) == 1, 'control Job has missing/extra Pods')
            pod = pods[0]
            owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller') is True]
            require(len(owners) == 1 and owners[0].get('kind') == 'Job' and owners[0].get('uid') == job['metadata']['uid'],
                    'control Pod is not owned by its exact Job')
            require(not pod['metadata'].get('deletionTimestamp') and pod['status'].get('phase') == 'Running', 'control not Running')
            return {'name': pod['metadata']['name'], 'uid': pod['metadata']['uid']}
        identity = self.wait(owned_pod, 90)
        pod = self.get('pod', identity['name'])
        require(pod['metadata']['uid'] == identity['uid'], 'control Pod replaced')
        self.state['created'].append({'kind': 'Pod', 'name': identity['name'], 'uid': identity['uid'],
                                      'controllerJobUID': job['metadata']['uid'], 'controllerJobName': job['metadata']['name']})
        self.journal('job-pod-bound', jobUID=job['metadata']['uid'], pod=identity)
        labels = copy.deepcopy(pod['metadata'].get('labels', {}))
        # Preserve all Job selector labels so its controller cannot release the Pod.
        forbidden = {'pod-template-hash', 'controller-uid', 'job-name',
                     'batch.kubernetes.io/controller-uid', 'batch.kubernetes.io/job-name'}
        labels.update({k: v for k, v in source_labels.items() if k not in forbidden})
        pod = self.patch('Pod', pod, '/metadata/labels', labels)
        selector = job['spec'].get('selector', {}).get('matchLabels', {})
        require(selector and all(labels.get(k) == v for k, v in selector.items()), 'Job selector protection lost')
        return pod, job

    def exec(self, pod, container, args, payload=None):
        self.guard()
        expected = getattr(self, 'active_pods', {}).get(pod)
        if expected:
            current = self.get('pod', pod)
            require(current['metadata']['uid'] == expected['uid'] and not current['metadata'].get('deletionTimestamp') and
                    current['spec'].get('serviceAccountName') == expected['account'], 'probe Pod identity changed')
            owners = [o for o in current['metadata'].get('ownerReferences', []) if o.get('controller') is True]
            require(len(owners) == 1 and owners[0].get('uid') == expected['ownerUID'], 'probe Pod controller changed')
        return subprocess.run(['uds', 'zarf', 'tools', 'kubectl', '--context', CONTEXT, 'exec', '-i', '-n', NS,
                               pod, '-c', container, '--', *args], input=payload, text=True,
                              capture_output=True, timeout=20)

    def install_probe(self, pod, container):
        # Fixed source/JDK-produced class; no downloaded executable or mutable image.
        directory = '/tmp/' + self.state['trialID']
        script = ('umask 077; if [ -e ' + directory + ' ]; then '
                  'test -d ' + directory + ' && test ! -L ' + directory + ' && '
                  'test -f ' + directory + '/ProtocolProbe.class && test ! -L ' + directory + '/ProtocolProbe.class || exit 1; '
                  'printf \'%s  %s\\n\' ' + self.state['probeClassSHA256'] + ' ' + directory + '/ProtocolProbe.class | sha256sum -c - >/dev/null; '
                  'else mkdir ' + directory + '; base64 -d > ' + directory + '/ProtocolProbe.class; fi')
        result = self.exec(pod, container, ['/bin/bash', '-ceu', script], self.probe_class)
        require(result.returncode == 0, 'could not stage the fixed protocol probe in writable /tmp')
        return directory

    def protocol(self, pod, container, directory, mode, ip=None, port=None):
        args = ['/usr/bin/env', '-u', 'JAVA_TOOL_OPTIONS', '-u', 'JDK_JAVA_OPTIONS', '-u', '_JAVA_OPTIONS',
                'java', '-Xms8m', '-Xmx32m', '-XX:MaxMetaspaceSize=32m', '-cp', directory, 'ProtocolProbe', mode]
        if ip is not None:
            args += [ip, str(port)]
        result = self.exec(pod, container, args)
        expected = {0: 'DNS_RESPONSE' if mode == 'dns' else 'APPLICATION_RESPONSE', 10: 'TRANSPORT_REJECTED'}
        require(result.returncode in expected and result.stdout.strip() == expected[result.returncode] and not result.stderr.strip(),
                'probe execution/protocol invalid (not a valid network denial)')
        return result.returncode

    def traffic(self, identities, phase):
        self.active_pods = {p['name']: {'uid': p['uid'], 'account': p['account'],
                                      'ownerUID': p['controllerReplicaSetUID']} for p in identities}
        pods = self.get('pods')['items']
        targets = {}
        selectors = {'ignite': {'app': 'takserver-ignite'},
                     'postgres': {'app.kubernetes.io/name': 'postgresql', 'app.kubernetes.io/component': 'primary'},
                     'nats': {'app.kubernetes.io/name': 'nats', 'app.kubernetes.io/component': 'nats'}}
        for protocol, selector in selectors.items():
            matching = [p for p in pods if all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())]
            require(len(matching) == 1, 'trial requires exactly one Ready backend per protocol')
            target = matching[0]
            require(not target['metadata'].get('deletionTimestamp') and target['status'].get('phase') == 'Running' and any(
                c.get('type') == 'Ready' and c.get('status') == 'True' for c in target['status'].get('conditions', [])), 'backend not Ready')
            require(target['status'].get('podIP'), 'backend has no Pod IP')
            targets[protocol] = {'name': target['metadata']['name'], 'uid': target['metadata']['uid'], 'ip': target['status']['podIP'],
                                 'serviceAccount': target['spec'].get('serviceAccountName', 'default')}
            if protocol == 'ignite':
                require(targets[protocol]['serviceAccount'] == LEGACY, 'Ignite identity changed')
        if 'backendTargets' in self.state:
            require(targets == self.state['backendTargets'], 'backend Pod/identity changed during the trial')
        else:
            self.state['backendTargets'] = targets
            self.journal('backend-identities', targets=targets)
        # Only the actual dedicated Ignite server is probed; no cache join/write.
        config = self.get('configmap', 'takserver-ignite-configmap')
        xml = config.get('data', {}).get('ignite-config.xml', '')
        require(xml and not re.search(r'sslcontext|sslenabled|<import\b', xml, re.I),
                'TLS/unknown Ignite listener requires a separately validated protocol probe')
        ignite = self.get('pod', targets['ignite']['name'])
        require(any(v.get('configMap', {}).get('name') == 'takserver-ignite-configmap' for v in ignite['spec'].get('volumes', [])),
                'probed Ignite does not mount the inspected configuration')
        ignite_containers = [c for c in ignite['spec']['containers'] if 'takserver-ignite' in c['image']]
        require(len(ignite_containers) == 1, 'unexpected Ignite application container')
        version = self.exec(ignite['metadata']['name'], ignite_containers[0]['name'], ['/bin/sh', '-ceu',
                            'test -f /opt/ignite/libs/ignite-core-2.17.0.jar'])
        require(version.returncode == 0, 'selected Ignite2.17.0 wire contract is not installed')
        receipts = []
        for identity in identities:
            app = identity['app']
            source = self.get('pod', identity['name'])
            require(source['metadata']['uid'] == identity['uid'], 'source Pod changed during traffic check')
            containers = [c for c in source['spec']['containers'] if 'takserver-' in c['image']]
            require(len(containers) == 1, 'ambiguous application container')
            container = containers[0]['name']
            directory = self.install_probe(identity['name'], container)
            protocols = [('ignite', 47100)] + ([] if app == 'takserver-config' else [('postgres', 5432), ('nats', 4222)])
            statuses = [s for s in source['status']['containerStatuses'] if s['name'] == container]
            require(len(statuses) == 1, 'application image status missing')
            image = statuses[0].get('imageID', '').removeprefix('docker-pullable://')
            require(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image), 'negative control requires the actual immutable application image')
            controls = [('unrelated', self.state['negativeAccount'])]
            if phase == 'strict' and app != 'takserver-config':
                controls.append(('legacy-postgres', LEGACY))
            for control, account in controls:
                self.state['controlSequence'] = self.state.get('controlSequence', 0) + 1
                self.journal('control-sequence')
                name = self.state['trialID'] + '-' + phase + '-' + app.removeprefix('takserver-') + '-' + str(self.state['controlSequence'])
                labels = copy.deepcopy(source['metadata'].get('labels', {}))
                labels.pop('pod-template-hash', None)
                control_manifest = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'labels': {'app': 'identity-control'}},
                    'spec': {'serviceAccountName': account, 'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                             'activeDeadlineSeconds': 180, 'securityContext': source['spec'].get('securityContext', {}),
                             'containers': [{'name': 'probe', 'image': image, 'command': ['/bin/bash', '-ceu', 'trap \'exit 0\' TERM INT; sleep 180 & wait'],
                                             'securityContext': containers[0].get('securityContext', {}),
                                             'resources': {'requests': {'cpu': '10m', 'memory': '64Mi'}, 'limits': {'cpu': '250m', 'memory': '192Mi'}},
                                             'readinessProbe': {'exec': {'command': ['/bin/bash', '-c', 'exit 1']}},
                                             'volumeMounts': [{'name': 'tmp', 'mountPath': '/tmp'}]}],
                             'volumes': [{'name': 'tmp', 'emptyDir': {'sizeLimit': '16Mi'}}]}}
                negative, negative_job = self.control_job(control_manifest, labels)
                allowed_manifest = copy.deepcopy(control_manifest)
                allowed_manifest['metadata']['name'] = name + '-allow'
                allowed_manifest['spec']['serviceAccountName'] = identity['account']
                allowed, allowed_job = self.control_job(allowed_manifest, labels)
                negative_name, allowed_name = negative['metadata']['name'], allowed['metadata']['name']
                def started(control_pod, expected_account, owner_job):
                    p = self.get('pod', control_pod['metadata']['name'])
                    require(p['metadata']['uid'] == control_pod['metadata']['uid'] and p['spec'].get('serviceAccountName') == expected_account,
                            'negative control identity changed')
                    owners = [o for o in p['metadata'].get('ownerReferences', []) if o.get('controller') is True]
                    require(len(owners) == 1 and owners[0].get('uid') == owner_job['metadata']['uid'] and owners[0].get('kind') == 'Job',
                            'control was released or adopted by another controller')
                    require(not p['metadata'].get('deletionTimestamp') and p['status'].get('phase') == 'Running' and
                            p['metadata'].get('annotations', {}).get('ambient.istio.io/redirection') == 'enabled', 'control not running in ambient')
                    require(not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p['status'].get('conditions', [])),
                            'negative control became a Service endpoint')
                    return {'uid': p['metadata']['uid'], 'account': account}
                self.wait(lambda: started(negative, account, negative_job), 90)
                self.wait(lambda: started(allowed, identity['account'], allowed_job), 90)
                for control_pod, job, control_account in ((negative, negative_job, account), (allowed, allowed_job, identity['account'])):
                    self.active_pods[control_pod['metadata']['name']] = {'uid': control_pod['metadata']['uid'],
                        'account': control_account, 'ownerUID': job['metadata']['uid']}
                allowdir = self.install_probe(allowed_name, 'probe')
                require(self.protocol(allowed_name, 'probe', allowdir, 'dns') == 0, 'positive control DNS failed')
                negdir = self.install_probe(negative_name, 'probe')
                require(self.protocol(negative_name, 'probe', negdir, 'dns') == 0, 'negative control DNS/network baseline failed')
                selected = [('postgres', 5432)] if control == 'legacy-postgres' else protocols
                for protocol, port in selected:
                    target = targets[protocol]
                    require(self.protocol(identity['name'], container, directory, protocol, target['ip'], port) == 0, 'positive protocol baseline failed')
                    require(self.protocol(allowed_name, 'probe', allowdir, protocol, target['ip'], port) == 0, 'same-label permitted control failed')
                    require(self.protocol(negative_name, 'probe', negdir, protocol, target['ip'], port) == 10, 'wrong identity received application data')
                    require(self.protocol(allowed_name, 'probe', allowdir, protocol, target['ip'], port) == 0, 'same-label permitted recovery control failed')
                    require(self.protocol(identity['name'], container, directory, protocol, target['ip'], port) == 0, 'positive recovery check failed')
                    fresh = self.get('pod', target['name'])
                    require(fresh['metadata']['uid'] == target['uid'] and fresh['status'].get('podIP') == target['ip'] and
                            not fresh['metadata'].get('deletionTimestamp'), 'backend changed during control')
                    receipts.append({'source': identity, 'protocol': protocol, 'port': port, 'target': target,
                                     'negativePodUID': negative['metadata']['uid'], 'negativeJobUID': negative_job['metadata']['uid'],
                                     'positiveControlUID': allowed['metadata']['uid'], 'positiveJobUID': allowed_job['metadata']['uid'], 'negativeAccount': account,
                                     'control': control, 'positiveBefore': True, 'negativeNoApplicationResponse': True, 'positiveAfter': True})
                self.delete_created('Job', negative_job['metadata']['name'])
                self.delete_created('Job', allowed_job['metadata']['name'])
                self.delete_created('Pod', negative_name)
                self.delete_created('Pod', allowed_name)
            cleanup = self.exec(identity['name'], container, ['/bin/bash', '-ceu', 'rm -f ' + directory + '/ProtocolProbe.class; rmdir ' + directory])
            require(cleanup.returncode == 0, 'source probe cleanup failed')
        self.journal('traffic-' + phase, checks=receipts)
        return receipts

    def prepare(self):
        receipt = self.guard()
        require(not self.evidence.exists(), 'evidence exists; use the explicit reverse operation for recovery')
        if not self.evidence.parent.exists():
            self.evidence.parent.mkdir(parents=True, mode=0o700)
        require(self.evidence.parent.stat().st_mode & 0o077 == 0, 'evidence directory must be private (0700)')
        require(self.get('namespace', NS, NS)['metadata'].get('labels', {}).get('istio.io/dataplane-mode') == 'ambient',
                'takserver namespace is not ambient')
        self.values = json.loads(self.command(['helm', '--kube-context', CONTEXT, 'get', 'values', 'uds-takserver-config',
                                              '-n', NS, '-o', 'json']) or '{}') or {}
        require(self.values.get('workloadIdentityPhase', 'shared') == 'shared', 'trial must start from shared Helm values')
        package = self.get('package', NS)
        helm_owner(package, 'uds-takserver-config', NS)
        initial, _ = self.render('shared')
        require(package['spec'] == initial['spec'], 'deployed Package differs from exact config chart/values')
        deployments = {d['metadata']['name']: d for d in self.get('deployments')['items'] if d['metadata']['name'] in APPS}
        require(set(deployments) == set(APPS), 'four exact TAK Deployments required')
        pepr = {name: self.get('deployment', name, 'pepr-system') for name in PEPR}
        for name, deployment in pepr.items():
            helm_owner(deployment, 'takserver-oidc', 'pepr-system')
            ready(deployment)
            phases = [env.get('value') for c in deployment['spec']['template']['spec']['containers']
                      for env in c.get('env', []) if env['name'] == 'TAK_WORKLOAD_IDENTITY_PHASE']
            require(phases == ['shared'], 'Pepr must initially have one explicit shared phase')
        mesh = self.get('configmap', 'istio', 'istio-system')
        mesh_values = yaml.safe_load(mesh.get('data', {}).get('mesh', ''))
        require(isinstance(mesh_values, dict) and mesh_values.get('rootNamespace', 'istio-system') == 'istio-system' and
                mesh_values.get('trustDomain', 'cluster.local') == 'cluster.local', 'unsupported Istio root namespace/trust domain')
        network = self.get('networkpolicies', labels='uds/package=' + NS)['items']
        for item in network:
            require(not item['metadata'].get('deletionTimestamp'), 'initial terminating NetworkPolicy')
        trial = 'identity-' + hashlib.sha256((receipt['runID'] + '-' + receipt['runAttempt']).encode()).hexdigest()[:8]
        nodes = self.get('nodes', namespace='default')['items']
        require(len(nodes) == 1 and nodes[0]['metadata']['name'] == 'k3d-uds-server-0', 'unexpected Kubernetes node set')
        architecture = nodes[0]['metadata'].get('labels', {}).get('kubernetes.io/arch')
        require(architecture in ('amd64', 'arm64') and nodes[0]['status']['nodeInfo'].get('architecture') == architecture,
                'node architecture is not verified')
        self.state.update({'guard': receipt, 'scenario': 'identities', 'architecture': architecture,
                           'sourceSHA': receipt['sourceSHA'], 'runID': receipt['runID'], 'runAttempt': receipt['runAttempt'],
                           'clusterUID': receipt['clusterUID'], 'meshConfigUID': mesh['metadata']['uid'], 'meshConfigHash': sha(mesh['data']['mesh']), 'trialID': trial, 'negativeAccount': trial + '-denied',
                           'packageUID': package['metadata']['uid'], 'packageInvariant': package_invariant(package), 'currentAllow': package['spec']['network']['allow'],
                           'baselineAllow': package['spec']['network']['allow'],
                           'baselineNetwork': sorted({sha(p['spec']) for p in network}),
                           'deploymentUIDs': {n: d['metadata']['uid'] for n, d in deployments.items()},
                           'templateFingerprints': {n: template_fingerprint(d) for n, d in deployments.items()},
                           'peprUIDs': {n: d['metadata']['uid'] for n, d in pepr.items()},
                           'peprTemplateFingerprints': {n: template_fingerprint(d, True) for n, d in pepr.items()},
                           'originalTrialAnnotations': {n: d['metadata'].get('annotations', {}).get('uds.dev/identity-trial') for n, d in deployments.items()},
                           'phaseRules': {phase: self.render(phase)[0]['spec']['network']['allow'] for phase in PHASES},
                           'driverSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           'probeSourceSHA256': hashlib.sha256((HERE / 'ProtocolProbe.java').read_bytes()).hexdigest()})
        self.journal('preflight')
        self.wait(self.policies)
        self.wait(lambda: self.identities('shared'))
        # Refuse existing dedicated RBAC before creating any trial-owned objects.
        _, resources = self.render('transition')
        validate_rbac(resources)
        for kind, name in RBAC:
            require(not self.kube('get', kind, name, '-n', NS, '--ignore-not-found', '-o', 'json').strip(),
                    'dedicated RBAC already exists; fresh shared baseline required')
        return resources

    def compile_probe(self, directory=None):
        directory = directory or self.evidence.parent / 'probe'
        require(not directory.exists(), 'probe output must be new')
        directory.mkdir()
        require(shutil.which('javac'), 'a host Java compiler is required')
        self.command(['javac', '--release', '17', '-d', str(directory), str(HERE / 'ProtocolProbe.java')])
        files = list(directory.glob('*.class'))
        require(len(files) == 1 and files[0].name == 'ProtocolProbe.class', 'unexpected protocol compiler output')
        self.probe_class = base64.b64encode(files[0].read_bytes()).decode()
        compiler = Path(shutil.which('javac')).resolve()
        self.state['compiler'] = {'path': str(compiler), 'sha256': hashlib.sha256(compiler.read_bytes()).hexdigest(),
                                  'version': self.command([str(compiler), '-version']).strip()}
        self.state['probeClassSHA256'] = hashlib.sha256(files[0].read_bytes()).hexdigest()
        self.journal('probe-compiled')

    def reverse(self):
        # Reverse always restores dual policies BEFORE restoring workload identities.
        current = self.get('package', NS)
        require(current['metadata']['uid'] == self.state['packageUID'] and
                current['spec']['network']['allow'] in self.state['phaseRules'].values(), 'unknown Package state; refusing recovery')
        self.state['currentAllow'] = current['spec']['network']['allow']
        self.stage_config('rollback')
        identities = self.stage_admission('rollback')
        self.traffic(identities, 'rollback')
        self.stage_config('shared')
        identities = self.stage_admission('shared')
        self.traffic(identities, 'shared')
        require(self.get('package', NS)['spec']['network']['allow'] == self.state['baselineAllow'], 'baseline rules not restored')
        for app in APPS:
            obj = self.get('deployment', app)
            annotations = dict(obj['metadata'].get('annotations', {}))
            original = self.state['originalTrialAnnotations'][app]
            if original is None:
                annotations.pop('uds.dev/identity-trial', None)
            else:
                annotations['uds.dev/identity-trial'] = original
            self.patch('deployment', obj, '/metadata/annotations', annotations)
        # Only UID/resourceVersion-matched trial objects can be removed.
        for entry in reversed(self.state['created']):
            if entry['kind'] != 'Pod' and not entry.get('deleted'):
                self.delete_created(entry['kind'], entry['name'])
        self.wait(lambda: self.identities('shared'))
        self.wait(self.policies)
        self.state['completed'] = True
        required = {'traffic-baseline', 'policy-converged-transition', 'traffic-dual-before-rollout', 'workloads-transition',
                    'traffic-transition', 'policy-converged-strict', 'workloads-strict', 'traffic-strict',
                    'policy-converged-rollback', 'workloads-rollback', 'traffic-rollback',
                    'policy-converged-shared', 'workloads-shared', 'traffic-shared'}
        observed = {entry['stage'] for entry in self.state['stages']}
        self.state['accepted'] = not self.state.get('recoveryOnly', False) and required <= observed
        self.state['results'] = {'fullRoundTrip': self.state['accepted'], 'sharedRestored': True,
                                 'scope': 'policy/Pod identity and protocol reachability; not all application behavior'}
        self.journal('reversed-and-verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('round-trip', 'reverse'))
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    driver = Driver(args.evidence.resolve())
    try:
        if args.operation == 'round-trip':
            resources = driver.prepare()
            driver.compile_probe()
            driver.create({'apiVersion': 'v1', 'kind': 'ServiceAccount',
                           'metadata': {'name': driver.state['negativeAccount']}, 'automountServiceAccountToken': False})
            for obj in resources:
                driver.create(obj)
            driver.traffic(driver.identities('shared'), 'baseline')
            driver.stage_config('transition')
            driver.traffic(driver.identities('shared'), 'dual-before-rollout')
            identities = driver.stage_admission('transition')
            driver.traffic(identities, 'transition')
            driver.stage_config('strict')
            identities = driver.stage_admission('strict')
            driver.traffic(identities, 'strict')
            driver.reverse()
        else:
            require(args.evidence.is_file(), 'existing trial evidence required')
            driver.state = json.loads(args.evidence.read_text())
            driver.state['recoveryOnly'], driver.state['accepted'] = True, False
            require(re.fullmatch(r'identity-[0-9a-f]{8}', driver.state.get('trialID', '')) and
                    re.fullmatch(r'[0-9a-f]{64}', driver.state.get('probeClassSHA256', '')) and
                    driver.state.get('negativeAccount') == driver.state['trialID'] + '-denied', 'invalid recovery identifiers')
            require(not driver.state.get('completed'), 'trial already reversed')
            receipt = driver.guard()
            require(receipt == driver.state['guard'], 'ephemeral cluster/job marker changed')
            expected_trial = 'identity-' + hashlib.sha256((receipt['runID'] + '-' + receipt['runAttempt']).encode()).hexdigest()[:8]
            require(driver.state['trialID'] == expected_trial, 'recovery trial belongs to another job')
            require(driver.state.get('driverSHA256') == hashlib.sha256(Path(__file__).read_bytes()).hexdigest() and
                    driver.state.get('probeSourceSHA256') == hashlib.sha256((HERE / 'ProtocolProbe.java').read_bytes()).hexdigest(), 'recovery code changed')
            driver.values = json.loads(driver.command(['helm', '--kube-context', CONTEXT, 'get', 'values', 'uds-takserver-config',
                                                       '-n', NS, '-o', 'json']) or '{}') or {}
            for phase in PHASES:
                require(driver.render(phase)[0]['spec']['network']['allow'] == driver.state['phaseRules'][phase],
                        'chart/values changed; refusing recovery')
            # Never trust executable class bytes supplied by a recovery journal/cache.
            # Recompile the reviewed fixed source and record the actual compiler again.
            with tempfile.TemporaryDirectory(prefix='identity-probe-recovery-', dir=args.evidence.parent) as directory:
                driver.compile_probe(Path(directory) / 'classes')
            # Interrupted controls are deleted only with their original recorded UID.
            for entry in list(driver.state['created']):
                if entry['kind'] == 'Job' and not entry.get('deleted'):
                    driver.delete_created('Job', entry['name'])
            for entry in driver.state['created']:
                if entry['kind'] == 'Pod' and not entry.get('deleted') and driver.kube('get', 'pod', entry['name'], '-n', NS, '--ignore-not-found', '-o', 'json').strip():
                    driver.delete_created('Pod', entry['name'])
            account = driver.kube('get', 'serviceaccount', driver.state['negativeAccount'], '-n', NS, '--ignore-not-found', '-o', 'json')
            if not account.strip():
                for entry in driver.state['created']:
                    if entry['kind'] == 'ServiceAccount' and entry['name'] == driver.state['negativeAccount']:
                        entry['deleted'] = True
                driver.create({'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': driver.state['negativeAccount']},
                               'automountServiceAccountToken': False})
            driver.reverse()
    except (ValueError, TypeError, StopIteration, yaml.YAMLError, subprocess.SubprocessError, OSError, KeyError) as error:
        if driver.state.get('trialID'):
            driver.journal('stopped', failure=type(error).__name__, message=str(error)[:300])
        raise SystemExit('identity trial stopped; no automatic rollback or broad cleanup: ' + str(error)[:300])


if __name__ == '__main__':
    main()
