#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in, numeric-only observations of existing application JVM telemetry."""
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time

APPS = ('takserver-api', 'takserver-messaging')
NAMES = ('process_start_time_seconds', 'jvm_classes_currently_loaded',
         'jvm_classes_loaded_total', 'jvm_classes_unloaded_total')
NUMBER = r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
MAX_METRICS = 64 * 1024
MAX_POD = 1024 * 1024


class Unavailable(Exception):
    """Only fixed internal reason codes may escape a collector boundary."""


def require(condition, reason):
    if not condition:
        raise Unavailable(reason)


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def epoch_ms(value):
    require(isinstance(value, str) and len(value) <= 40, 'timestamp_schema')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None, 'timestamp_schema')
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise Unavailable('timestamp_schema') from None


def parse_metrics(data):
    require(isinstance(data, bytes) and len(data) <= MAX_METRICS, 'metrics_size')
    try:
        text = data.decode('utf-8')
    except UnicodeError:
        raise Unavailable('metrics_encoding') from None
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        token = re.split(r'[\s{]', line, maxsplit=1)[0]
        if token not in NAMES:
            continue  # Unrelated names/labels/payload are never returned.
        require(token not in found, 'metrics_duplicate')
        match = re.fullmatch(re.escape(token) + r'[ \t]+(' + NUMBER + ')', line)
        require(match is not None and len(match[1]) <= 128, 'metrics_schema')
        try:
            value = Decimal(match[1])
        except InvalidOperation:
            raise Unavailable('metrics_number') from None
        require(value.is_finite() and value >= 0, 'metrics_number')
        if token == NAMES[0]:
            require(0 < value < Decimal('253402300800'), 'metrics_epoch')
            # Exposition uses a floating seconds conversion of an integer ms.
            # Keep that decimal and round only the derived millisecond value.
            millis = int((value * 1000).to_integral_value(rounding=ROUND_HALF_UP))
            found[token] = str(value)
            found['jvm_start_time_unix_ms'] = millis
        else:
            require(value == value.to_integral_value() and value <= 2**63-1, 'metrics_count')
            found[token] = int(value)
    require(all(name in found for name in NAMES), 'metrics_missing')
    return found


def image_digest(value):
    if matches(value, r'sha256:[a-f0-9]{64}'):
        return value
    require(matches(value, r'(?:docker-pullable://)?(?:[A-Za-z0-9.-]+(?::[0-9]{1,5})?/)?[A-Za-z0-9_./-]+@sha256:[a-f0-9]{64}'), 'image_id')
    return value.rsplit('@', 1)[1]


def identity(pod, app):
    require(isinstance(pod, dict), 'pod_schema')
    meta, status = pod.get('metadata') or {}, pod.get('status') or {}
    require(meta.get('namespace') == 'takserver' and not meta.get('deletionTimestamp'), 'pod_namespace_or_deleted')
    require(matches(meta.get('name'), re.escape(app) + r'-[a-z0-9-]{1,100}'), 'pod_name')
    require(matches(meta.get('uid'), r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'), 'pod_uid')
    containers = [c for c in (pod.get('spec') or {}).get('containers', []) if c.get('name') == app]
    statuses = [s for s in status.get('containerStatuses', []) if s.get('name') == app]
    require(len(containers) == len(statuses) == 1, 'named_container_missing')
    item = statuses[0]
    require(matches(item.get('containerID'), r'containerd://[a-f0-9]{64}'), 'container_id')
    image = image_digest(item.get('imageID'))
    image_reference_hash = hashlib.sha256(item['imageID'].encode()).hexdigest()
    require(type(item.get('restartCount')) is int and item['restartCount'] >= 0, 'restart_count')
    started = (item.get('state') or {}).get('running', {}).get('startedAt')
    epoch_ms(started)
    return {'pod_name': meta['name'], 'pod_uid': meta['uid'], 'container_name': app,
            'container_id': item['containerID'], 'image_id': image, 'image_reference_sha256': image_reference_hash,
            'restart_count': item['restartCount'], 'container_started_at': started}


class Commands:
    def __init__(self, context, deadline, prefix=None):
        require(matches(context, r'[A-Za-z0-9_.-]{1,100}'), 'context_required')
        self.context, self.deadline = context, deadline
        self.prefix = prefix or (['kubectl'] if shutil.which('kubectl') else ['uds', 'zarf', 'tools', 'kubectl'])

    def run(self, args, limit, use_context=True):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0.1, 'deadline')
        child = None
        body = bytearray()
        end = min(self.deadline-0.1, time.monotonic()+2.9)
        try:
            context_args = ['--context', self.context] if use_context else []
            child = subprocess.Popen([*self.prefix, *context_args, '--request-timeout=2s', *args],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            os.set_blocking(child.stdout.fileno(), False)
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                complete = False
                while not complete:
                    budget = end-time.monotonic()
                    require(budget > 0, 'command_timeout')
                    if not selector.select(budget):
                        raise Unavailable('command_timeout')
                    chunk = os.read(child.stdout.fileno(), min(65536, limit+1-len(body)))
                    if not chunk:
                        complete = True
                    else:
                        body.extend(chunk)
                        require(len(body) <= limit, 'output_size')
                child.wait(timeout=max(0.001, end-time.monotonic()))
            require(child.returncode == 0, 'command_failed')
            return bytes(body)
        except (OSError, subprocess.SubprocessError):
            raise Unavailable('command_unavailable') from None
        finally:
            if child is not None:
                # Kill our whole session even if an exited parent left a child.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=max(0.001, self.deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise Unavailable('cleanup_deadline') from None
                finally:
                    child.stdout.close()

    def pod(self, args):
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    require(key not in result, 'pod_duplicate_field')
                    result[key] = value
                return result
            value = json.loads(self.run(['get', *args, '-n', 'takserver', '-o', 'json'], MAX_POD), object_pairs_hook=unique)
            require(isinstance(value, dict), 'pod_schema')
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise Unavailable('pod_json') from None


def current_context_matches(context):
    """Benchmark's other reads use current-context; refuse a different cluster."""
    try:
        command = Commands(context, time.monotonic()+3)
        selected = command.run(['config', 'current-context'], 256, use_context=False).decode('utf-8').strip()
        return selected == context
    except (Unavailable, UnicodeError):
        return False


def unavailable_phase(reason):
    return {'evidence': {'jvm_started_at': None}, 'inits': [], 'image_pull_s': None,
            'container_to_log_s': None, 'log_to_ready_s': None, 'jvm_to_log_s': None,
            'jvm_observation': {'available': False, 'reason': reason}}


def caller_metadata():
    """Curated caller context, not independent checkout/run attestation."""
    result = {}
    for env, field, pattern in (('GITHUB_SHA', 'source_sha', r'[a-f0-9]{40}'),
                                ('GITHUB_RUN_ID', 'run_id', r'[1-9][0-9]{0,19}'),
                                ('GITHUB_RUN_ATTEMPT', 'run_attempt', r'[1-9][0-9]{0,9}')):
        value = os.environ.get(env)
        if matches(value, pattern):
            result[field] = value
    return result


def observe(app, context, commands=None):
    """15-second per-app read-only budget; unavailable never asserts app health."""
    result = {'schema': 1, 'available': False, 'app': app if app in APPS else None,
              'caller': caller_metadata()}
    try:
        require(app in APPS, 'app_unsupported')
        require(matches(context, r'[A-Za-z0-9_.-]{1,100}'), 'context_required')
        result['context'] = context
        commands = commands or Commands(context, time.monotonic()+15)
        listing = commands.pod(['pods', '-l', 'app='+app])
        pods = listing.get('items')
        require(isinstance(pods, list) and len(pods) == 1, 'pod_ambiguous')
        current = identity(pods[0], app)
        samples = []
        for _ in range(2):
            before_unix, before_mono = time.time(), time.monotonic()
            data = commands.run(['get', '--raw', '/api/v1/namespaces/takserver/pods/'+current['pod_name']+':9100/proxy/metrics'], MAX_METRICS)
            sample = parse_metrics(data)
            sample.update(observed_start_unix=before_unix, observed_end_unix=time.time(),
                          observed_start_monotonic=before_mono, observed_end_monotonic=time.monotonic())
            samples.append(sample)
        fresh = identity(commands.pod(['pod', current['pod_name']]), app)
        require(fresh == current, 'pod_incarnation_changed')
        first, last = samples
        require(first['jvm_start_time_unix_ms'] == last['jvm_start_time_unix_ms']
                and Decimal(first[NAMES[0]]) == Decimal(last[NAMES[0]]), 'jvm_incarnation_changed')
        for metric in NAMES[2:]:
            require(last[metric] >= first[metric], 'class_counter_reset')
        started = first['jvm_start_time_unix_ms']
        require(epoch_ms(current['container_started_at']) <= started <= int(first['observed_end_unix']*1000), 'jvm_start_outside_lifetime')
        if isinstance(commands, Commands):
            require(time.monotonic() <= commands.deadline, 'deadline')
        result.update(available=True, identity=current, samples=samples,
                      jvm_start_time_unix_ms=started, source='RuntimeMXBean-via-existing-JMX-exporter',
                      observation_kind='existing-incarnation-snapshot',
                      class_counts_scope='observed-at-scrape-not-startup-duration',
                      collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    except Unavailable as error:
        result['reason'] = str(error)
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, RecursionError, OSError):
        result['reason'] = 'unsupported_schema'
    return result


def join_phase(phase, observation):
    """Join only exact existing phase identity; otherwise retain null timing."""
    evidence = phase.get('evidence') or {}
    phase['evidence'] = evidence
    evidence['jvm_started_at'] = None
    phase['jvm_to_log_s'] = None
    # Independent metrics evidence is never an accepted timing join. Clear it
    # on every attempt so stale successful observations cannot survive failures.
    phase.pop('jvm_metric_observation', None)
    phase['jvm_observation'] = observation
    if not observation.get('available'):
        return phase
    current = observation['identity']
    keys = ('pod_name', 'pod_uid', 'container_name', 'container_id', 'restart_count', 'image_id', 'image_reference_sha256')
    if any(evidence.get(key) != current[key] for key in keys):
        phase['jvm_observation'] = {'available': False, 'reason': 'phase_identity_mismatch'}
        return phase
    try:
        require(epoch_ms(evidence.get('container_started_at')) == epoch_ms(current['container_started_at']), 'phase_identity_mismatch')
        # Preserve only the observer's bounded numeric projection after exact
        # phase incarnation binding, even if marker/Ready chronology rejects timing.
        phase['jvm_metric_observation'] = copy.deepcopy(observation)
        marker_ms = epoch_ms(evidence.get('startup_log_at'))
        started = observation['jvm_start_time_unix_ms']
        require(started <= marker_ms, 'jvm_start_after_marker')
        if evidence.get('ready_at'):
            require(marker_ms <= epoch_ms(evidence['ready_at']), 'marker_after_ready')
    except Unavailable as error:
        phase['jvm_observation'] = {'available': False, 'reason': str(error)}
        return phase
    evidence['jvm_started_at'] = datetime.fromtimestamp(started/1000, timezone.utc).isoformat()
    evidence['jvm_start_limit'] = 'Official JVM epoch start (millisecond resolution); not class-loading duration'
    phase['jvm_to_log_s'] = (marker_ms-started)/1000
    return phase


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'JVM observation unavailable: invalid_arguments\n')


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--app', choices=APPS, required=True)
    args = parser.parse_args()
    result = observe(args.app, args.context)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['available'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
