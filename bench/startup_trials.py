#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in startup-only begin/finish observations; never install or restart anything."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from bench import jvm_metrics as jvm, phases

APPS = jvm.APPS
LIMIT = 1024 * 1024
REASONS = {'unsupported_schema', 'bindings', 'context', 'cohort', 'node_inventory',
           'application_inventory', 'configuration', 'metadata', 'cold_not_empty',
           'phase_unavailable', 'phase_identity', 'timestamp_join', 'incarnation_reused',
           'platform_drift', 'configuration_drift', 'image_drift', 'node_drift',
           'pair_binding', 'warm_missing', 'boundary', 'output_path'}


class Invalid(Exception):
    pass


def failure_diagnostic(error):
    """Fixed exception kinds and source locations, never exception/data values."""
    modules = {str(Path(module.__file__).resolve()): (name, Path(module.__file__))
               for name, module in (('jvm_metrics', jvm), ('phases', phases))}
    modules[str(Path(__file__).resolve())] = ('startup_trials', Path(__file__))
    result = {'kind': 'other', 'module': 'unavailable', 'line': 0, 'source_sha256': None}
    for kind, classes in (('invalid-json', (json.JSONDecodeError,)),
                          ('invalid-text', (UnicodeError,)), ('missing-field', (KeyError,)),
                          ('type-error', (TypeError,)), ('guard-rejection', (Invalid,)),
                          ('observer-unavailable', (jvm.Unavailable,)),
                          ('invalid-value', (ValueError,)), ('io-error', (OSError,))):
        if isinstance(error, classes):
            result['kind'] = kind
            break
    if isinstance(error, jvm.Unavailable) and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in {
            'pod_schema', 'pod_namespace_or_deleted', 'pod_name', 'pod_uid', 'named_container_missing',
            'container_id', 'image_id', 'restart_count', 'timestamp_schema'}:
        result['observer_reason'] = error.args[0]
    if isinstance(error, jvm.CommandFailure):
        result['command'] = error.diagnostic()
    current = error.__traceback__
    while current is not None:
        selected = modules.get(current.tb_frame.f_code.co_filename)
        if selected is not None and current.tb_frame.f_code.co_name != 'require' and 0 < current.tb_lineno < 10000:
            name, path = selected
            try:
                source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                source_sha256 = None
            result.update(module=name, line=current.tb_lineno, source_sha256=source_sha256)
        current = current.tb_next
    return result


def require(value, reason):
    if not value:
        raise Invalid(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def token(value, pattern=r'[A-Za-z0-9_.-]{1,253}'):
    require(isinstance(value, str) and re.fullmatch(pattern, value), 'metadata')
    return value


def stamp():
    return datetime.now(timezone.utc).isoformat()


def read_json(commands, args, optional=False):
    data = commands.run(args, LIMIT)
    if optional and not data.strip():
        require('--ignore-not-found' in args, 'configuration')
        return None
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'unsupported_schema')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    require(isinstance(value, dict), 'unsupported_schema')
    return value


def references(template):
    found = {'configmaps': set(), 'secrets': set(), 'optional_configmaps': set()}
    required_configmaps = set()
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('configMapKeyRef', 'configMapRef', 'configMap') and isinstance(child, dict):
                    name = child.get('name')
                    if name:
                        name = token(name); found['configmaps'].add(name)
                        (found['optional_configmaps'] if child.get('optional') is True else required_configmaps).add(name)
                if key in ('secretKeyRef', 'secretRef', 'secret') and isinstance(child, dict):
                    name = child.get('name', child.get('secretName'))
                    if name: found['secrets'].add(token(name))
                if key == 'imagePullSecrets' and isinstance(child, list):
                    for item in child: found['secrets'].add(token(item['name']))
                visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(template)
    found['optional_configmaps'] -= required_configmaps
    require(len(found['configmaps'])+len(found['secrets']) <= 32, 'configuration')
    return found


def container_images(pod):
    """Resolve every measured Pod container image, including completed inits."""
    inventory = []
    for kind, declared_key, status_key, maximum in (
            ('main', 'containers', 'containerStatuses', 32),
            ('init', 'initContainers', 'initContainerStatuses', 16)):
        declared = pod.get('spec', {}).get(declared_key, [])
        statuses = pod.get('status', {}).get(status_key, [])
        require(isinstance(declared, list) and isinstance(statuses, list) and len(declared) <= maximum, 'application_inventory')
        names = [token(item['name'], r'[a-z0-9-]{1,63}') for item in declared]
        require(len(names) == len(set(names)) == len(statuses) and
                set(names) == {item['name'] for item in statuses}, 'application_inventory')
        for item in declared:
            status = next(value for value in statuses if value['name'] == item['name'])
            reference = item['image']
            require(isinstance(reference, str) and 0 < len(reference) <= 1024, 'application_inventory')
            inventory.append({'kind': kind, 'name': item['name'], 'image_id': jvm.image_digest(status.get('imageID')),
                              'image_reference_sha256': hashlib.sha256(status['imageID'].encode()).hexdigest(),
                              'declared_image_sha256': hashlib.sha256(reference.encode()).hexdigest()})
    require(any(item['kind'] == 'main' for item in inventory), 'application_inventory')
    return sorted(inventory, key=lambda item: (item['kind'], item['name']))


def snapshot(commands):
    """Return only typed identity/platform projections and opaque config hashes."""
    namespace = read_json(commands, ['get', 'namespace', 'kube-system', '-o', 'json'])
    cluster = token(namespace['metadata']['uid'])
    nodes = read_json(commands, ['get', 'nodes', '-o', 'json'])['items']
    require(isinstance(nodes, list) and 0 < len(nodes) <= 8, 'node_inventory')
    platform, cache, by_name = [], [], {}
    for node in nodes:
        meta, status = node['metadata'], node['status']
        name, uid = token(meta['name']), token(meta['uid'])
        require(name not in by_name, 'node_inventory')
        info = status['nodeInfo']
        item = {'uid': uid, 'architecture': token(info['architecture']),
                'os': token(info['operatingSystem']), 'kernel': token(info['kernelVersion']),
                'os_image_sha256': digest(info.get('osImage')),
                'runtime': token(info['containerRuntimeVersion'], r'[A-Za-z0-9_.:+/-]{1,253}'),
                'kubelet': token(info['kubeletVersion'], r'[A-Za-z0-9_.+-]{1,100}')}
        require(item['architecture'] in ('amd64', 'arm64'), 'node_inventory')
        platform.append(item); by_name[name] = uid
        images = status.get('images')
        require(isinstance(images, list) and len(images) <= 1024, 'node_inventory')
        reported = []
        for image in images:
            require(type(image.get('sizeBytes')) is int and image['sizeBytes'] >= 0, 'node_inventory')
            names = image.get('names')
            require(isinstance(names, list) and all(isinstance(n, str) and len(n) <= 1024 for n in names), 'node_inventory')
            reported.append({'names_sha256': digest(sorted(names)), 'bytes': image['sizeBytes']})
        cache.append({'node_uid': uid, 'reported_images_sha256': digest(sorted(reported, key=lambda x: x['names_sha256'])),
                      'reported_image_count': len(reported), 'inventory_may_be_truncated': True})
    deployments = read_json(commands, ['get', 'deployments', '-n', 'takserver', '-o', 'json'])['items']
    pods = read_json(commands, ['get', 'pods', '-n', 'takserver', '-l', 'app in (takserver-api,takserver-messaging)', '-o', 'json'])['items']
    require(isinstance(deployments, list) and isinstance(pods, list), 'application_inventory')
    config, identities, images, source_pods = {}, {}, {}, {}
    for app in APPS:
        ds = [d for d in deployments if d.get('metadata', {}).get('name') == app]
        ps = [p for p in pods if p.get('metadata', {}).get('labels', {}).get('app') == app]
        require(len(ds) <= 1 and len(ps) <= 1, 'application_inventory')
        if ds:
            deployment = ds[0]; template = copy.deepcopy(deployment['spec']['template'])
            # rollout restart changes only this declared annotation; all other inputs stay bound.
            template.setdefault('metadata', {}).setdefault('annotations', {}).pop('kubectl.kubernetes.io/restartedAt', None)
            refs = references(template); resources = {}
            for name in sorted(refs['configmaps']):
                optional = name in refs['optional_configmaps']
                args = ['get', 'configmap', name, '-n', 'takserver', '-o', 'json']
                if optional: args.append('--ignore-not-found')
                cm = read_json(commands, args, optional=optional)
                if cm is None:
                    resources['cm/'+name] = {'present': False}
                    continue
                resources['cm/'+name] = {'uid': token(cm['metadata']['uid']), 'rv': token(cm['metadata']['resourceVersion']),
                                        'sha256': digest({k: cm.get(k) for k in ('data', 'binaryData', 'immutable')})}
            for name in sorted(refs['secrets']):
                # Only metadata is emitted by kubectl; no Secret data/values enter this collector.
                raw = commands.run(['get', 'secret', name, '-n', 'takserver', '-o', 'jsonpath={.metadata.uid}{" "}{.metadata.resourceVersion}'], 512).decode().split()
                require(len(raw) == 2, 'metadata')
                resources['secret/'+name] = {'uid': token(raw[0]), 'rv': token(raw[1])}
            config[app] = digest({'deployment_uid': token(deployment['metadata']['uid']), 'template': template, 'resources': resources})
        if ps:
            identity = jvm.identity(ps[0], app)
            require(identity['restart_count'] == 0, 'application_inventory')
            node = ps[0]['spec'].get('nodeName'); require(node in by_name, 'node_inventory')
            identity['node_uid'] = by_name[node]
            identities[app] = identity; source_pods[app] = ps[0]
            images[app] = container_images(ps[0])
    return {'cluster_uid': cluster, 'platform': sorted(platform, key=lambda x: x['uid']),
            'reported_image_cache': sorted(cache, key=lambda x: x['node_uid']),
            'config_sha256': config, 'identities': identities, 'container_images': images}, source_pods


def begin(context, cohort, bindings, commands=None, observer=None):
    require(jvm.matches(context, r'[A-Za-z0-9_.-]{1,100}'), 'context')
    require(jvm.matches(cohort, r'[a-z0-9-]{1,64}'), 'cohort')
    require(isinstance(bindings, dict) and 'source' in bindings and all(jvm.matches(k, r'[a-z_]{1,40}') and jvm.matches(v, r'[a-f0-9]{64}') for k, v in bindings.items()), 'bindings')
    commands = commands or jvm.Commands(context, time.monotonic()+60)
    started = stamp(); observed, _ = snapshot(commands)
    observer = observer or jvm.observe
    starts = {}
    for app, identity in observed['identities'].items():
        observation = observer(app, context)
        require(observation.get('available') is True and
                all(observation['identity'].get(key) == value for key, value in identity.items() if key != 'node_uid'), 'phase_unavailable')
        starts[app] = observation['jvm_start_time_unix_ms']
    after, _ = snapshot(commands)
    require(all(after[key] == observed[key] for key in ('cluster_uid', 'platform', 'config_sha256', 'identities', 'container_images')), 'phase_identity')
    return {'schema': 1, 'kind': 'startup-begin', 'context': context, 'cohort': cohort,
            'bindings': bindings, 'observed_started_at': started, 'observed_finished_at': stamp(),
            'snapshot': observed, 'jvm_starts': starts, 'jvm_observer_sha256': hashlib.sha256(Path(jvm.__file__).read_bytes()).hexdigest(), 'caller': jvm.caller_metadata(),
            'cache_scope': 'reported kubelet image inventory; not page-cache, filesystem-cache or proven cache absence',
            'collector_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def finish(initial, mode, commands=None, observer=None):
    validate_begin(initial)
    require(mode in ('cold', 'warm'), 'boundary')
    if mode == 'cold':
        require(not initial['snapshot']['identities'] and not initial['snapshot']['config_sha256'], 'cold_not_empty')
    commands = commands or jvm.Commands(initial['context'], time.monotonic()+90)
    observer = observer or jvm.observe
    before, pods = snapshot(commands)
    require(set(before['identities']) == set(APPS) and set(before['config_sha256']) == set(APPS), 'application_inventory')
    result = {'schema': 1, 'kind': 'startup-finish', 'mode': mode, 'begin_sha256': digest(initial),
              'begin': initial, 'snapshot': before, 'phases': {}, 'pod_created_at': {}, 'observed_started_at': stamp()}
    ready, created = [], []
    for app in APPS:
        pod = pods[app]; identity = before['identities'][app]
        old = initial['snapshot']['identities'].get(app)
        require(old is None or old['pod_uid'] != identity['pod_uid'], 'incarnation_reused')
        events = read_json(commands, ['get', 'events', '-n', 'takserver', '--field-selector', 'involvedObject.uid='+identity['pod_uid'], '-o', 'json'])['items']
        require(isinstance(events, list) and len(events) <= 1024, 'unsupported_schema')
        declared_inits = [token(item['name'], r'[a-z0-9-]{1,63}') for item in pod.get('spec', {}).get('initContainers', [])]
        require(len(declared_inits) == len(set(declared_inits)) <= 16, 'application_inventory')
        paths = {'spec.'+('initContainers' if item['kind'] == 'init' else 'containers')+'{'+item['name']+'}' for item in before['container_images'][app]}
        for event in events:
            require(event.get('involvedObject', {}).get('uid') == identity['pod_uid'], 'phase_identity')
            if event.get('reason') in ('Pulling', 'Pulled'):
                require(event['involvedObject'].get('fieldPath') in paths, 'phase_identity')
                token(event.get('metadata', {}).get('uid'))
        logs = commands.run(['logs', '-n', 'takserver', identity['pod_name'], '-c', app, '--timestamps'], LIMIT).decode()
        phase = phases.pod_phases(pod, events, logs, container_name=app)
        phase['declared_init_names'] = declared_inits
        phase['image_pull_scope'] = 'sum of observed complete Pulling/Pulled pairs; missing events do not prove cache presence or zero pull time'
        observation = observer(app, initial['context'])
        jvm.join_phase(phase, observation)  # Preserve #533's independent-metrics semantics unchanged.
        require(phase['jvm_observation'].get('available') is True, 'phase_unavailable')
        require(phase['jvm_to_log_s'] is not None and phase['log_to_ready_s'] is not None, 'timestamp_join')
        require(jvm.epoch_ms(phase['evidence']['ready_at']) >= jvm.epoch_ms(phase['evidence']['startup_log_at']), 'timestamp_join')
        require(observation['identity']['pod_uid'] == identity['pod_uid'], 'phase_identity')
        require(observation['jvm_start_time_unix_ms'] >= jvm.epoch_ms(initial['observed_finished_at']), 'boundary')
        result['phases'][app] = phase
        ready.append(jvm.epoch_ms(phase['evidence']['ready_at']))
        result['pod_created_at'][app] = pod['metadata']['creationTimestamp']
        created.append(jvm.epoch_ms(pod['metadata']['creationTimestamp']))
    after, after_pods = snapshot(commands)
    require(after['cluster_uid'] == before['cluster_uid'] and after['platform'] == before['platform'], 'platform_drift')
    require(after['config_sha256'] == before['config_sha256'], 'configuration_drift')
    require(after['identities'] == before['identities'], 'phase_identity')
    require(after['container_images'] == before['container_images'], 'image_drift')
    for app in APPS:
        current_ready = phases.pod_phases(after_pods[app], [], '', container_name=app)['evidence']['ready_at']
        require(current_ready == result['phases'][app]['evidence']['ready_at'], 'phase_identity')
    require(before['cluster_uid'] == initial['snapshot']['cluster_uid'] and before['platform'] == initial['snapshot']['platform'], 'platform_drift')
    if mode == 'warm':
        require(set(initial['snapshot']['identities']) == set(APPS), 'warm_missing')
        require(before['config_sha256'] == initial['snapshot']['config_sha256'], 'configuration_drift')
        require(before['container_images'] == initial['snapshot']['container_images'], 'image_drift')
        for app in APPS:
            for key, reason in [('image_id', 'image_drift'), ('image_reference_sha256', 'image_drift'), ('node_uid', 'node_drift')]:
                require(before['identities'][app][key] == initial['snapshot']['identities'][app][key], reason)
    span = (max(ready)-min(created))/1000
    require(span >= 0, 'timestamp_join')
    result.update(observed_finished_at=stamp(), pod_creation_to_ready_span_s=span,
                  warm_s=span if mode == 'warm' else None,
                  duration_scope='earliest new application Pod creation to latest application Ready; not install/rollout command duration')
    validate_finished(result)
    return result


def validate_snapshot(value):
    token(value['cluster_uid'])
    platform, cache = value['platform'], value['reported_image_cache']
    require(isinstance(platform, list) and 0 < len(platform) <= 8 and isinstance(cache, list), 'node_inventory')
    ids = {node['uid'] for node in platform}
    require(len(ids) == len(platform) == len(cache) and ids == {item['node_uid'] for item in cache}, 'node_inventory')
    for node in platform:
        token(node['uid']); require(node['architecture'] in ('amd64', 'arm64'), 'node_inventory')
    for item in cache:
        require(jvm.matches(item['reported_images_sha256'], r'[a-f0-9]{64}') and
                type(item['reported_image_count']) is int and item['reported_image_count'] >= 0 and
                item['inventory_may_be_truncated'] is True, 'node_inventory')
    for app, identity in value['identities'].items():
        require(app in APPS and identity['node_uid'] in ids, 'node_inventory')
    require(set(value['config_sha256']) <= set(APPS) and
            all(jvm.matches(h, r'[a-f0-9]{64}') for h in value['config_sha256'].values()), 'configuration')
    require(set(value['container_images']) == set(value['identities']), 'image_drift')
    for app, images in value['container_images'].items():
        require(isinstance(images, list) and 0 < len(images) <= 48, 'image_drift')
        keys = {(item['kind'], item['name']) for item in images}
        require(len(keys) == len(images) and ('main', app) in keys, 'image_drift')
        for item in images:
            require(item['kind'] in ('main', 'init'), 'image_drift'); token(item['name'], r'[a-z0-9-]{1,63}')
            require(jvm.matches(item['image_id'], r'sha256:[a-f0-9]{64}') and
                    all(jvm.matches(item[key], r'[a-f0-9]{64}') for key in ('image_reference_sha256', 'declared_image_sha256')), 'image_drift')
        main = next(item for item in images if item['kind'] == 'main' and item['name'] == app)
        require(all(main[key] == value['identities'][app][key] for key in ('image_id', 'image_reference_sha256')), 'image_drift')
    return value


def validate_begin(initial):
    require(type(initial.get('schema')) is int and initial['schema'] == 1 and initial.get('kind') == 'startup-begin', 'boundary')
    require(jvm.matches(initial['context'], r'[A-Za-z0-9_.-]{1,100}') and
            jvm.matches(initial['cohort'], r'[a-z0-9-]{1,64}'), 'pair_binding')
    bindings = initial['bindings']
    require(isinstance(bindings, dict) and 'source' in bindings and
            all(jvm.matches(k, r'[a-z_]{1,40}') and jvm.matches(v, r'[a-f0-9]{64}') for k, v in bindings.items()), 'bindings')
    require(initial['collector_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest() and
            initial['jvm_observer_sha256'] == hashlib.sha256(Path(jvm.__file__).read_bytes()).hexdigest(), 'bindings')
    require(jvm.epoch_ms(initial['observed_started_at']) <= jvm.epoch_ms(initial['observed_finished_at']), 'boundary')
    validate_snapshot(initial['snapshot'])
    require(set(initial['jvm_starts']) == set(initial['snapshot']['identities']) and
            all(type(value) is int and value > 0 for value in initial['jvm_starts'].values()), 'phase_identity')
    return initial


def validate_finished(record):
    require(type(record.get('schema')) is int and record['schema'] == 1 and record.get('kind') == 'startup-finish', 'boundary')
    initial, current = record['begin'], record['snapshot']
    validate_begin(initial); validate_snapshot(current)
    require(record['begin_sha256'] == digest(initial), 'pair_binding')
    require(initial['collector_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'bindings')
    require(record['mode'] in ('cold', 'warm'), 'boundary')
    require(current['cluster_uid'] == initial['snapshot']['cluster_uid'] and current['platform'] == initial['snapshot']['platform'], 'platform_drift')
    require(set(current['identities']) == set(current['config_sha256']) == set(record['phases']) == set(APPS), 'application_inventory')
    require(jvm.epoch_ms(record['observed_started_at']) >= jvm.epoch_ms(initial['observed_finished_at']) and
            jvm.epoch_ms(record['observed_finished_at']) >= jvm.epoch_ms(record['observed_started_at']), 'boundary')
    ready = []
    for app in APPS:
        phase, identity = record['phases'][app], current['identities'][app]
        evidence, observation = phase['evidence'], phase['jvm_observation']
        for key in ('jvm_to_log_s', 'container_to_log_s', 'log_to_ready_s', 'image_pull_s'):
            value = phase[key]
            require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0), 'timestamp_join')
        require(observation.get('available') is True, 'phase_unavailable')
        require(observation.get('app') == app and observation.get('context') == initial['context'], 'phase_identity')
        require(all(evidence.get(key) == identity[key] and observation['identity'].get(key) == identity[key]
                    for key in ('pod_name', 'pod_uid', 'container_name', 'container_id', 'restart_count', 'image_id', 'image_reference_sha256')), 'phase_identity')
        require(jvm.epoch_ms(evidence['container_started_at']) == jvm.epoch_ms(identity['container_started_at']), 'phase_identity')
        require(type(observation.get('jvm_start_time_unix_ms')) is int, 'phase_identity')
        require(jvm.epoch_ms(record['pod_created_at'][app]) <= jvm.epoch_ms(evidence['container_started_at']) <=
                observation['jvm_start_time_unix_ms'] <= jvm.epoch_ms(evidence['ready_at']) <=
                jvm.epoch_ms(record['observed_started_at']), 'timestamp_join')
        require(observation.get('collector_sha256') == hashlib.sha256(Path(jvm.__file__).read_bytes()).hexdigest(), 'bindings')
        require(len(observation.get('samples', [])) == 2, 'phase_unavailable')
        for sample in observation['samples']:
            facts = jvm.parse_metrics(('\n'.join(name+' '+str(sample[name]) for name in jvm.NAMES)+'\n').encode())
            require(facts['jvm_start_time_unix_ms'] == sample['jvm_start_time_unix_ms'] == observation['jvm_start_time_unix_ms'], 'phase_identity')
            brackets = [sample[key] for key in ('observed_start_unix', 'observed_end_unix', 'observed_start_monotonic', 'observed_end_monotonic')]
            require(all(type(value) in (int, float) and math.isfinite(value) for value in brackets), 'timestamp_join')
            start, end, mono_start, mono_end = brackets
            require(start <= end and mono_start <= mono_end and
                    abs((end-start)-(mono_end-mono_start)) <= .5 and
                    facts['jvm_start_time_unix_ms'] <= jvm.epoch_ms(evidence['ready_at']) <= jvm.epoch_ms(record['observed_started_at']) <=
                    int(start*1000) <= int(end*1000) <= jvm.epoch_ms(record['observed_finished_at']), 'timestamp_join')
        first, last = observation['samples']
        require(first['observed_end_unix'] <= last['observed_start_unix'] and
                first['observed_end_monotonic'] <= last['observed_start_monotonic'] and
                all(last[name] >= first[name] for name in jvm.NAMES[2:]), 'timestamp_join')
        require(observation['jvm_start_time_unix_ms'] >= jvm.epoch_ms(initial['observed_finished_at']), 'boundary')
        joined = jvm.join_phase(copy.deepcopy(phase), observation)
        require(joined['jvm_observation'].get('available') is True and phase['jvm_to_log_s'] is not None
                and joined['jvm_to_log_s'] == phase['jvm_to_log_s'], 'timestamp_join')
        expected = phases.elapsed(phases.parse_time(evidence['startup_log_at']), phases.parse_time(evidence['ready_at']))
        require(expected is not None and phase['log_to_ready_s'] == expected, 'timestamp_join')
        container_elapsed = phases.elapsed(phases.parse_time(evidence['container_started_at']), phases.parse_time(evidence['startup_log_at']))
        require(container_elapsed is not None and phase['container_to_log_s'] == container_elapsed, 'timestamp_join')
        require(set(phase['declared_init_names']) == {item['name'] for item in phase['inits']} and
                len(phase['declared_init_names']) == len(phase['inits']) == len(evidence['init_intervals']), 'timestamp_join')
        require(set(phase['declared_init_names']) == {item['name'] for item in current['container_images'][app] if item['kind'] == 'init'}, 'image_drift')
        for item, interval in zip(phase['inits'], evidence['init_intervals']):
            require(item['name'] == interval['name'] and item['seconds'] is not None and
                    type(item['seconds']) in (int, float) and
                    item['seconds'] == phases.elapsed(phases.parse_time(interval['started_at']), phases.parse_time(interval['finished_at'])), 'timestamp_join')
            require(jvm.epoch_ms(record['pod_created_at'][app]) <= jvm.epoch_ms(interval['started_at']) <=
                    jvm.epoch_ms(interval['finished_at']) <= jvm.epoch_ms(evidence['container_started_at']), 'timestamp_join')
        events = evidence['pull_events']
        require(isinstance(events, list) and len(events) <= 1024, 'timestamp_join')
        require(len({token(event['uid']) for event in events}) == len(events), 'timestamp_join')
        known = current['container_images'][app]
        paths = {'spec.'+('initContainers' if item['kind'] == 'init' else 'containers')+'{'+item['name']+'}' for item in known}
        projected = []
        for event in events:
            require(event['reason'] in ('Pulling', 'Pulled') and event['container'] in paths, 'timestamp_join')
            if event['at'] is not None:
                require(jvm.epoch_ms(record['pod_created_at'][app]) <= jvm.epoch_ms(event['at']) <= jvm.epoch_ms(evidence['ready_at']), 'timestamp_join')
            projected.append({'reason': event['reason'], 'eventTime': event['at'], 'involvedObject': {'fieldPath': event['container']}})
        require(phase['image_pull_s'] == phases._pull_seconds(projected), 'timestamp_join')
        ready.append(jvm.epoch_ms(evidence['ready_at']))
        old = initial['snapshot']['identities'].get(app)
        require(old is None or old['pod_uid'] != identity['pod_uid'], 'incarnation_reused')
    require(isinstance(record.get('pod_created_at'), dict) and set(record['pod_created_at']) == set(APPS), 'timestamp_join')
    created = [jvm.epoch_ms(record['pod_created_at'][app]) for app in APPS]
    require(all(jvm.epoch_ms(initial['observed_finished_at']) <= jvm.epoch_ms(record['pod_created_at'][app]) <= record['phases'][app]['jvm_observation']['jvm_start_time_unix_ms'] for app in APPS), 'timestamp_join')
    span = (max(ready)-min(created))/1000
    require(type(record['pod_creation_to_ready_span_s']) in (int, float) and span >= 0 and record['pod_creation_to_ready_span_s'] == span, 'timestamp_join')
    if record['mode'] == 'cold':
        require(not initial['snapshot']['identities'] and not initial['snapshot']['config_sha256'], 'cold_not_empty')
        require(record.get('warm_s') is None, 'warm_missing')
    else:
        require(type(record.get('warm_s')) in (int, float) and record['warm_s'] == span, 'warm_missing')
        require(set(initial['snapshot']['identities']) == set(APPS), 'warm_missing')
        require(current['config_sha256'] == initial['snapshot']['config_sha256'], 'configuration_drift')
        require(current['container_images'] == initial['snapshot']['container_images'], 'image_drift')
        for app in APPS:
            for key, reason in [('image_id', 'image_drift'), ('image_reference_sha256', 'image_drift'), ('node_uid', 'node_drift')]:
                require(current['identities'][app][key] == initial['snapshot']['identities'][app][key], reason)
    return record


def validate_pair(cold, warm):
    validate_finished(cold); validate_finished(warm)
    require(cold.get('mode') == 'cold' and warm.get('mode') == 'warm', 'warm_missing')
    for key in ('context', 'cohort', 'bindings', 'collector_sha256'):
        require(cold['begin'][key] == warm['begin'][key], 'pair_binding')
    require(jvm.epoch_ms(cold['observed_finished_at']) <= jvm.epoch_ms(warm['begin']['observed_started_at']), 'pair_binding')
    for key in ('cluster_uid', 'platform', 'config_sha256', 'identities', 'container_images'):
        require(cold['snapshot'][key] == warm['begin']['snapshot'][key], 'pair_binding')
    require(set(warm['begin']['jvm_starts']) == set(APPS), 'pair_binding')
    for app in APPS:
        a, b = cold['phases'][app], warm['phases'][app]
        require(warm['begin']['jvm_starts'][app] == a['jvm_observation']['jvm_start_time_unix_ms'], 'pair_binding')
        require(a['evidence']['pod_uid'] != b['evidence']['pod_uid'] and
                a['jvm_observation']['jvm_start_time_unix_ms'] != b['jvm_observation']['jvm_start_time_unix_ms'], 'incarnation_reused')
    return {'schema': 1, 'accepted': True, 'cold_sha256': digest(cold), 'warm_sha256': digest(warm),
            'scope': 'one independent cold/warm application pair; no CDS, probe or class-loading-duration claim'}


def read_file(path):
    path = Path(path).absolute()
    require(path == path.resolve(), 'output_path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= LIMIT, 'output_path')
        data = stream.read(LIMIT+1)
        require(len(data) <= LIMIT, 'output_path')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'unsupported_schema')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Startup observation unavailable: invalid_arguments\n')


def main():
    parser = Parser(description=__doc__); parser.add_argument('action', choices=('begin', 'finish', 'pair'))
    parser.add_argument('--context'); parser.add_argument('--cohort'); parser.add_argument('--bindings')
    parser.add_argument('--begin'); parser.add_argument('--mode', choices=('cold', 'warm'))
    parser.add_argument('--cold'); parser.add_argument('--warm'); parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        output = Path(args.output).absolute(); parent = output.parent
        require(parent == parent.resolve() and parent.is_dir() and parent.stat().st_uid == os.getuid() and stat.S_IMODE(parent.stat().st_mode) == 0o700 and not output.exists() and not output.is_symlink(), 'output_path')
        if args.action == 'begin': result = begin(args.context, args.cohort, read_file(args.bindings))
        elif args.action == 'finish': result = finish(read_file(args.begin), args.mode)
        else: result = validate_pair(read_file(args.cold), read_file(args.warm))
        data = (json.dumps(result, sort_keys=True, allow_nan=False)+'\n').encode(); require(len(data) <= LIMIT, 'output_path')
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(data)
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, Invalid) and str(error) in REASONS else 'unsupported_schema'
        print(json.dumps({'schema': 1, 'accepted': False, 'reason': reason,
                          'diagnostic': failure_diagnostic(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
