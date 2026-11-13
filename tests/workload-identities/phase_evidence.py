# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded identity guard inputs. No cluster access; never retain Pod payloads."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 256 * 1024
MAX_ITEMS = 256
MAX_PHASES = 16
PHASES = {'baseline', 'dual-before-rollout', 'transition', 'strict', 'rollback', 'shared', 'fresh-strict'}
HEX = r'[a-f0-9]{64}'
TOKEN = r'[A-Za-z0-9_.:/@*+-]{1,253}'
DIAGNOSTIC_STEPS = {
    'capture': frozenset({'render_inputs', 'application_baseline', 'package_projection', 'policy_inventory',
        'policy_projection', 'network_projection', 'application_deployments', 'application_replicasets',
        'application_pods', 'pepr_baseline', 'pepr_deployments', 'pepr_replicasets', 'pepr_pods', 'snapshot_bound'}),
    'replay': frozenset({'snapshot_schema', 'binding', 'render_inputs', 'source_binding', 'policy_inventory',
        'inventory_counts', 'network_baseline', 'policy_guard', 'application_templates', 'application_guard',
        'pepr_guard', 'verdict'}),
}
DIAGNOSTIC_SCOPES = frozenset(DIAGNOSTIC_STEPS)
DIAGNOSTIC_REASONS = frozenset({'unsupported_schema', 'inventory_bound', 'unsupported_policy_condition',
    'policy_inventory_incomplete', 'snapshot_bound', 'malformed_input', 'guard_rejected'})


class EvidenceError(ValueError):
    """Fixed reason codes only; never echo rejected input."""


def require(value, code='unsupported_schema'):
    if not value:
        raise EvidenceError(code)


def public_diagnostic(value):
    """Closed public enum only; never exception text, object names or input paths."""
    require(isinstance(value, dict) and set(value) == {'scope', 'step', 'reason'})
    require(all(isinstance(value[key], str) for key in ('scope', 'step', 'reason')))
    require(value['scope'] in DIAGNOSTIC_SCOPES and value['step'] in DIAGNOSTIC_STEPS[value['scope']])
    require(value['reason'] in DIAGNOSTIC_REASONS)
    return {key: value[key] for key in ('scope', 'step', 'reason')}


def _failure_diagnostic(scope, step, error):
    reason = 'malformed_input'
    if isinstance(error, EvidenceError):
        code = error.args[0] if error.args else None
        reason = code if isinstance(code, str) and code in DIAGNOSTIC_REASONS else 'unsupported_schema'
    elif scope == 'replay' and step in {'policy_guard', 'application_guard', 'pepr_guard'} and isinstance(error, (ValueError, StopIteration)):
        reason = 'guard_rejected'
    return public_diagnostic({'scope': scope, 'step': step, 'reason': reason})


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def token(value):
    require(isinstance(value, str) and re.fullmatch(TOKEN, value))
    return value


def number(value):
    require(type(value) is int and 0 <= value <= 2**53)
    return value


def items(value):
    require(isinstance(value, list) and len(value) <= MAX_ITEMS, 'inventory_bound')
    return value


def labels(value):
    require(isinstance(value, dict) and len(value) <= 64)
    return {token(k): token(v) for k, v in value.items()}


def metadata(obj, namespace='takserver'):
    meta = obj['metadata']
    result = {key: token(meta[key]) for key in ('name', 'uid', 'resourceVersion') if key in meta}
    result['namespace'] = token(meta.get('namespace', namespace))
    for key in ('generation',):
        if key in meta:
            result[key] = number(meta[key])
    if meta.get('deletionTimestamp'):
        # Only its presence affects guards; no arbitrary annotation/time text.
        result['deletionTimestamp'] = True
    return result


def owners(meta):
    result = []
    for owner in items(meta.get('ownerReferences', [])):
        require(type(owner.get('controller', False)) is bool)
        result.append({'uid': token(owner['uid']), 'controller': owner.get('controller', False)})
    return result


def binding(value):
    required = {'sourceSHA', 'runID', 'runAttempt', 'clusterUID', 'meshConfigUID', 'meshConfigHash', 'phase'}
    extras = {'bundleArchiveSHA256', 'packageArchiveSHA256', 'baselineValuesSHA256', 'renderInputsSHA256'}
    require(isinstance(value, dict) and required <= set(value) <= required | extras)
    require(re.fullmatch(r'[a-f0-9]{40}', value['sourceSHA']))
    require(all(re.fullmatch(r'[1-9][0-9]{0,19}', value[k]) for k in ('runID', 'runAttempt')))
    require(value['phase'] in PHASES)
    token(value['clusterUID']); token(value['meshConfigUID'])
    require(re.fullmatch(HEX, value['meshConfigHash']))
    require(all(re.fullmatch(HEX, value[k]) for k in extras if k in value))
    return dict(value)


def validate_render_inputs(value):
    require(isinstance(value, dict) and set(value) == {'apiVersions', 'apiVersionsSHA256', 'packageCRD'})
    versions = [token(v) for v in items(value['apiVersions'])]
    require(versions and versions == sorted(set(versions)) and digest(versions) == value['apiVersionsSHA256'])
    crd = value['packageCRD']
    require(isinstance(crd, dict) and set(crd) == {'name', 'uid', 'generation', 'resourceVersion', 'version', 'schemaSHA256'})
    require(crd['name'] == 'packages.uds.dev')
    for key in ('uid', 'resourceVersion', 'version'):
        token(crd[key])
    number(crd['generation']); require(re.fullmatch(HEX, crd['schemaSHA256']))
    result = {'apiVersions': versions, 'apiVersionsSHA256': value['apiVersionsSHA256'], 'packageCRD': dict(crd)}
    semantic = copy.deepcopy(result)
    semantic['packageCRD'].pop('resourceVersion')
    return result, digest(semantic)


def policy(obj):
    """Complete supported ALLOW specification; unsupported schemas cannot pass."""
    spec = obj['spec']
    action = spec.get('action', 'ALLOW')
    require(action in ('ALLOW', 'DENY', 'AUDIT', 'CUSTOM'))
    meta = metadata(obj)
    require(meta['namespace'] in ('takserver', 'istio-system'))
    if action != 'ALLOW':
        return {'metadata': meta, 'spec': {'action': action}}
    require(set(spec) <= {'action', 'selector', 'rules'})
    selector = spec.get('selector', {})
    require(set(selector) <= {'matchLabels'})
    meta['labels'] = {k: token(v) for k, v in obj['metadata'].get('labels', {}).items()
                      if k in ('uds/package', 'uds/generation')}
    rules = []
    for rule in items(spec.get('rules', [])):
        require(set(rule) <= {'from', 'to', 'when'})
        # Conditions may carry bearer tokens or arbitrary application data.
        # Refuse them rather than leaking or dropping a policy that matters.
        require(not rule.get('when'), 'unsupported_policy_condition')
        projected = {}
        if 'when' in rule:
            projected['when'] = []
        if 'from' in rule:
            projected['from'] = []
            for source in items(rule['from']):
                require(set(source) == {'source'} and set(source['source']) <= {'principals'})
                principals = [token(p) for p in items(source['source'].get('principals', []))]
                projected['from'].append({'source': {'principals': principals}})
        if 'to' in rule:
            projected['to'] = []
            for target in items(rule['to']):
                require(set(target) == {'operation'} and set(target['operation']) <= {'ports'})
                ports = [token(p) for p in items(target['operation'].get('ports', []))]
                projected['to'].append({'operation': {'ports': ports}})
        rules.append(projected)
    return {'metadata': meta, 'spec': {'action': action, 'selector': {'matchLabels': labels(selector.get('matchLabels', {}))}, 'rules': rules}}


def package_rules(package):
    allowed = {'direction', 'selector', 'remoteSelector', 'remoteNamespace', 'remoteServiceAccount',
               'remoteGenerated', 'port', 'description'}
    rules = []
    for rule in items(package['spec']['network']['allow']):
        if rule.get('direction') != 'Ingress':
            continue  # The shared policy guard examines ingress only.
        require(set(rule) <= allowed)
        result = {'direction': 'Ingress'}
        for key in ('selector', 'remoteSelector'):
            if key in rule:
                result[key] = labels(rule[key])
        for key in ('remoteNamespace', 'remoteServiceAccount', 'remoteGenerated'):
            if key in rule:
                result[key] = token(rule[key])
        if 'port' in rule:
            result['port'] = number(rule['port'])
        rules.append(result)
    return rules


def workload(obj, kind, guards, pepr=False):
    meta = metadata(obj)
    meta['ownerReferences'] = owners(obj['metadata'])
    meta['labels'] = {key: token(value) for key, value in obj['metadata'].get('labels', {}).items()
                      if key in ('app', 'app.kubernetes.io/managed-by')}
    if pepr:
        meta['labels'] = labels(obj['metadata'].get('labels', {}))
        meta['namespace'] = token(obj['metadata'].get('namespace', 'pepr-system'))
    annotation = obj['metadata'].get('annotations', {})
    meta['annotations'] = {key: token(annotation[key]) for key in
                           ('meta.helm.sh/release-name', 'meta.helm.sh/release-namespace', 'ambient.istio.io/redirection')
                           if key in annotation}
    spec, status = obj.get('spec', {}), obj.get('status', {})
    if kind == 'Pod':
        result = {'metadata': meta, 'spec': {'serviceAccountName': token(spec.get('serviceAccountName', 'default'))},
                  'status': {'phase': token(status.get('phase', 'Unknown')),
                             'conditions': [{'type': 'Ready', 'status': c['status']} for c in items(status.get('conditions', []))
                                            if c.get('type') == 'Ready' and c.get('status') in ('True', 'False', 'Unknown')]}}
    else:
        fingerprint = guards.template_fingerprint(obj, pepr)
        require(re.fullmatch(HEX, fingerprint))
        # Exact full-template digest preserves comparisons without container env,
        # commands, mounts, image strings or unrelated annotations in evidence.
        result = {'metadata': meta, 'templateSHA256': fingerprint,
                  'spec': {'replicas': number(spec.get('replicas', 1)),
                           'serviceAccountName': token(spec['template']['spec'].get('serviceAccountName', 'default'))},
                  'status': {k: number(status[k]) for k in ('observedGeneration', 'replicas', 'updatedReplicas',
                              'readyReplicas', 'availableReplicas', 'unavailableReplicas') if k in status}}
    if pepr:
        actual_spec = spec if kind == 'Pod' else spec['template']['spec']
        phases = [e.get('value') for c in actual_spec.get('containers', []) for e in c.get('env', [])
                  if e.get('name') == 'TAK_WORKLOAD_IDENTITY_PHASE']
        require(all(value in ('shared', 'transition', 'strict', 'rollback') for value in phases))
        result['phases'] = phases
        if kind != 'Pod':
            result['spec']['selector'] = {'matchLabels': labels(spec.get('selector', {}).get('matchLabels', {}))}
    return result


def capture(bind, *, guards, package, policies, network_policies, baseline_network,
            deployments, replicasets, pods, account, baseline_uids, template_fingerprints, policy_lists,
            pepr, pepr_uids, pepr_template_fingerprints, render_inputs):
    """Project SAME fetched observations. No getters, kubectl or later refetches."""
    result = {'schema': 1, 'binding': binding(bind), 'complete': True,
              'guardSHA256': hashlib.sha256(Path(guards.__file__).read_bytes()).hexdigest(),
              'captureSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    step = 'render_inputs'
    try:
        inputs, semantic_hash = validate_render_inputs(render_inputs)
        require(result['binding'].get('renderInputsSHA256', semantic_hash) == semantic_hash)
        result['binding']['renderInputsSHA256'] = semantic_hash
        result['renderInputs'] = inputs
        step = 'application_baseline'
        require(account in ('shared', 'dedicated'))
        require(set(baseline_uids) == set(guards.APPS) == set(template_fingerprints))
        result.update(account=account, baselineUIDs={k: token(v) for k, v in baseline_uids.items()},
                      templateFingerprints=dict(template_fingerprints))
        require(all(re.fullmatch(HEX, h) for h in template_fingerprints.values()))
        step = 'package_projection'
        result['package'] = {'metadata': metadata(package), 'status': {
            'phase': token(package['status']['phase']), 'observedGeneration': number(package['status']['observedGeneration'])},
            'spec': {'network': {'allow': package_rules(package)}}}
        step = 'policy_inventory'
        require(set(policy_lists) == {'takserver', 'istio-system'}, 'policy_inventory_incomplete')
        result['policyLists'] = {namespace: {'resourceVersion': token(entry['resourceVersion']), 'itemCount': number(entry['itemCount'])}
                                 for namespace, entry in policy_lists.items()}
        step = 'policy_projection'
        result['policies'] = [policy(p) for p in items(policies)]
        step = 'policy_inventory'
        require(all(sum(p['metadata']['namespace'] == namespace for p in result['policies']) == entry['itemCount']
                    for namespace, entry in result['policyLists'].items()), 'policy_inventory_incomplete')
        require(len({(p['metadata']['namespace'], p['metadata']['name']) for p in result['policies']}) == len(result['policies']))
        step = 'network_projection'
        result['network'] = [{'metadata': {**metadata(p), 'labels': {
            k: token(v) for k, v in p['metadata'].get('labels', {}).items() if k in ('uds/package', 'uds/generation')}},
            'specSHA256': digest(p['spec'])} for p in items(network_policies)]
        result['baselineNetwork'] = list(baseline_network)
        require(all(re.fullmatch(HEX, h) for h in baseline_network))
        step = 'application_deployments'
        result['deployments'] = [workload(d, 'Deployment', guards) for d in items(deployments)
                                 if d['metadata']['name'] in guards.APPS]
        step = 'application_replicasets'
        result['replicasets'] = [workload(r, 'ReplicaSet', guards) for r in items(replicasets)]
        step = 'application_pods'
        result['pods'] = [workload(p, 'Pod', guards) for p in items(pods)]
        step = 'pepr_baseline'
        require(set(pepr_uids) == set(guards.PEPR) == set(pepr_template_fingerprints))
        result['pepr'] = {}
        for key, kind in [('deployments', 'Deployment'), ('replicasets', 'ReplicaSet'), ('pods', 'Pod')]:
            step = 'pepr_' + key
            result['pepr'][key] = [workload(obj, kind, guards, True) for obj in items(pepr[key])]
        step = 'pepr_baseline'
        result['pepr']['baselineUIDs'] = {k: token(v) for k, v in pepr_uids.items()}
        result['pepr']['templateFingerprints'] = dict(pepr_template_fingerprints)
        require(all(re.fullmatch(HEX, h) for h in pepr_template_fingerprints.values()))
        result['counts'] = {k: len(result[k]) for k in ('policies', 'network', 'deployments', 'replicasets', 'pods')}
        step = 'snapshot_bound'
        require(len(encoded(result)) <= MAX_BYTES, 'snapshot_bound')
    except (EvidenceError, KeyError, TypeError, AttributeError, ValueError, OverflowError) as error:
        # No partial inventory can masquerade as complete proof or leak payload.
        return {k: result[k] for k in ('schema', 'binding', 'guardSHA256', 'captureSHA256')} | {
            'complete': False, 'reason': 'insufficient_evidence', 'diagnostic': _failure_diagnostic('capture', step, error)}
    return result


def _restore_workload(obj):
    value = copy.deepcopy(obj)
    fingerprint = value.pop('templateSHA256')
    require(re.fullmatch(HEX, fingerprint))
    account = value['spec'].pop('serviceAccountName')
    value['spec']['template'] = {'spec': {'serviceAccountName': account}, 'capturedTemplateSHA256': fingerprint}
    return value


def _validate_pepr(snapshot, guards):
    proof = snapshot['pepr']
    deployments, replicasets, pods = {}, [], []
    for key, kind in [('deployments', 'Deployment'), ('replicasets', 'ReplicaSet'), ('pods', 'Pod')]:
        for obj in proof[key]:
            value = copy.deepcopy(obj)
            phases = value.pop('phases')
            require(all(phase in ('shared', 'transition', 'strict', 'rollback') for phase in phases))
            container = {'env': [{'name': 'TAK_WORKLOAD_IDENTITY_PHASE', 'value': phase} for phase in phases]}
            if kind == 'Pod':
                value['spec']['containers'] = [container]
                pods.append(value)
            else:
                value = _restore_workload(value)
                value['spec']['template']['spec']['containers'] = [container]
                if kind == 'Deployment':
                    require(obj['templateSHA256'] == proof['templateFingerprints'][value['metadata']['name']])
                    deployments[value['metadata']['name']] = value
                else:
                    replicasets.append(value)
    require(set(deployments) == set(guards.PEPR))
    phase = {'baseline': 'shared', 'dual-before-rollout': 'shared', 'fresh-strict': 'strict'}.get(
        snapshot['binding']['phase'], snapshot['binding']['phase'])
    # Exact pure live validator; no Driver/get/kubectl fallback exists here.
    return guards.validate_pepr(list(deployments.values()), replicasets, pods, phase, proof['baselineUIDs'], {
        name: guards.template_fingerprint(value, True) for name, value in deployments.items()})



def validate_phase(snapshot, guards, expected_binding=None):
    """Fixed public verdict; reuses live policy/workload guards, never a fallback read."""
    verdict = {'schema': 1, 'accepted': False, 'reason': 'insufficient_evidence'}
    step = 'snapshot_schema'
    try:
        if isinstance(snapshot, dict) and snapshot.get('complete') is False and 'diagnostic' in snapshot:
            verdict['diagnostic'] = public_diagnostic(snapshot['diagnostic'])
            return verdict
        require(isinstance(snapshot, dict) and snapshot.get('schema') == 1 and snapshot.get('complete') is True)
        require(len(encoded(snapshot)) <= MAX_BYTES)
        step = 'binding'
        bind = binding(snapshot['binding'])
        require(expected_binding is None or bind == expected_binding)
        step = 'render_inputs'
        _inputs, semantic_hash = validate_render_inputs(snapshot['renderInputs'])
        require(bind.get('renderInputsSHA256') == semantic_hash)
        step = 'source_binding'
        guard_hash = hashlib.sha256(Path(guards.__file__).read_bytes()).hexdigest()
        require(snapshot['guardSHA256'] == guard_hash)
        require(snapshot['captureSHA256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        step = 'policy_inventory'
        require(set(snapshot['policyLists']) == {'takserver', 'istio-system'})
        require(all(sum(p['metadata']['namespace'] == namespace for p in snapshot['policies']) == entry['itemCount']
                    and token(entry['resourceVersion']) for namespace, entry in snapshot['policyLists'].items()))
        step = 'inventory_counts'
        require(snapshot['counts'] == {k: len(snapshot[k]) for k in ('policies', 'network', 'deployments', 'replicasets', 'pods')})
        step = 'network_baseline'
        require(sorted({p['specSHA256'] for p in snapshot['network']}) == snapshot['baselineNetwork'])
        network = [{'metadata': p['metadata'], 'spec': {'capturedSpecSHA256': p['specSHA256']}} for p in snapshot['network']]
        baseline = sorted({guards.sha(p['spec']) for p in network})
        step = 'policy_guard'
        fingerprint = guards.validate_policies(snapshot['package'], snapshot['policies'], network, baseline)
        step = 'application_templates'
        for deployment in snapshot['deployments']:
            require(deployment['templateSHA256'] == snapshot['templateFingerprints'][deployment['metadata']['name']])
        step = 'application_guard'
        identities = guards.validate_workloads([_restore_workload(d) for d in snapshot['deployments']],
            [_restore_workload(r) for r in snapshot['replicasets']], snapshot['pods'], snapshot['account'], snapshot['baselineUIDs'])
        step = 'pepr_guard'
        pepr_result = _validate_pepr(snapshot, guards)
        step = 'verdict'
        verdict.update(accepted=True, reason='passed', binding=bind, inputSHA256=digest(snapshot), guardSHA256=guard_hash,
                       captureSHA256=snapshot['captureSHA256'], policyFingerprint=fingerprint, workloadCount=len(identities), peprWorkloadCount=len(pepr_result), inventoryCounts=snapshot['counts'])
    except (EvidenceError, KeyError, TypeError, AttributeError, ValueError, StopIteration, OverflowError) as error:
        verdict['diagnostic'] = _failure_diagnostic('replay', step, error)
    return verdict


def write_phase(directory, snapshot):
    """New private bounded file; never overwrite historical phase observations."""
    directory = Path(directory)
    require(directory.is_dir() and not any(p.is_symlink() for p in (directory, *directory.parents)))
    require(stat.S_IMODE(directory.stat().st_mode) == 0o700)
    require(len(list(directory.glob('phase-*.json'))) < MAX_PHASES, 'phase_bound')
    data = encoded(snapshot)
    require(len(data) <= MAX_BYTES, 'snapshot_bound')
    phase = binding(snapshot['binding'])['phase']
    path = directory / ('phase-' + phase + '.json')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
    return {'file': path.name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def read_phase(directory, reference):
    directory = Path(directory)
    require(set(reference) == {'file', 'sha256', 'bytes'})
    require(re.fullmatch(r'phase-[a-z-]+\.json', reference['file']) and re.fullmatch(HEX, reference['sha256']))
    path = directory / reference['file']
    require(not any(p.is_symlink() for p in (path, *path.parents)))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES and len(data) == reference['bytes'] and hashlib.sha256(data).hexdigest() == reference['sha256'])
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result)
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=unique)
