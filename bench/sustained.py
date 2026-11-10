# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Explicit baseline-only synthetic study; historical short sweeps stay unchanged."""
import hashlib
import json
import math
import os
from pathlib import Path

RAMP_DEADLINE = 120
WARMUP = 300
DURATION = 1200
REPEATS = 3
CLIENTS = 50
INTERVAL = 5
COUNTERS = ('messages_sent', 'messages_received', 'connect_event_count',
            'disconnect_event_count', 'ping_count', 'pong_count', 'time_between_ping_pong')
DB_COUNTERS = ('blks_hit', 'blks_read', 'temp_files', 'temp_bytes', 'checkpoints_timed',
               'checkpoints_req', 'checkpoint_write_ms', 'checkpoint_sync_ms', 'buffers_backend')


def enabled(env=None):
    env = os.environ if env is None else env
    mode = env.get('BENCH_STUDY', 'short')
    if mode not in ('short', 'synthetic-baseline'):
        raise ValueError('BENCH_STUDY must be short or synthetic-baseline')
    if mode == 'synthetic-baseline':
        if env.get('BENCH_PROFILE') != 'baseline' or env.get('BENCH_CLIENTS') != '50':
            raise ValueError('synthetic-baseline requires baseline profile and exactly 50 clients')
        return True
    return False


def provenance(config, source, tester):
    tester_hash = hashlib.sha256(tester.read_bytes()).hexdigest()
    fixture = Path(__file__).with_name('fixtures') / 'tester/tak_tester.py.txt'
    if tester_hash != hashlib.sha256(fixture.read_bytes()).hexdigest():
        raise ValueError('study tester differs from pinned source fixture')
    return {'protocol': 'synthetic-baseline-v1', 'repeat_count': REPEATS,
            'ramp_deadline_s': RAMP_DEADLINE, 'warmup_s': WARMUP, 'measurement_s': DURATION, 'requested_clients': CLIENTS,
            'self_sa_interval_s': INTERVAL, 'offered_self_sa_per_s': CLIENTS / INTERVAL,
            'ping_interval_ms': 5000, 'production_representative': False,
            'config_settings': config,
            'tester_commit': '5187abd46d827d37cfc5708805eced197a837e49',
            'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            'source_commit': source,
            'tester_sha256': tester_hash}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class WindowInvalid(ValueError):
    def __init__(self, message, window, category="measurement-invalid"):
        super().__init__(message)
        self.window = window
        self.category = category


def parse_window(text):
    lines = [line.removeprefix('BENCH_WINDOW_JSON:') for line in text.splitlines()
             if line.startswith('BENCH_WINDOW_JSON:')]
    if len(lines) != 1:
        raise ValueError('missing or ambiguous measured window')
    value = json.loads(lines[0])
    def reject(message, category="measurement-invalid"):
        raise WindowInvalid(message, value, category)
    if isinstance(value, dict) and value.get('client_error'):
        reject('a tracked client exited unexpectedly during warmup or measurement', 'client-process-exit')
    if not isinstance(value, dict) or not all(finite(value.get(k)) for k in ('start_monotonic', 'end_monotonic', 'start_unix', 'end_unix')):
        reject('invalid measured timestamps')
    before, after = value.get('before'), value.get('after')
    if not isinstance(before, dict) or not isinstance(after, dict):
        reject('invalid measured snapshot objects')
    ready = value.get('ready')
    ready_at = value.get('ready_monotonic')
    if (not isinstance(ready, dict) or len(ready) != CLIENTS or not finite(ready_at)
            or value['start_monotonic']-ready_at < WARMUP):
        reject('all-client steady warmup was shorter than 300 seconds')
    elapsed = value['end_monotonic'] - value['start_monotonic']
    if not finite(elapsed) or not DURATION <= elapsed <= DURATION + 3:
        reject('measured window duration outside tolerance')
    if len(before) != CLIENTS or set(before) != set(after) or set(before) != set(ready):
        reject('measured window lacks all 50 stable client identities')
    totals = [0] * len(COUNTERS)
    for uid in before:
        first, last = before[uid], after[uid]
        if not isinstance(ready[uid], list) or len(ready[uid]) != len(COUNTERS) or ready[uid][2:4] != first[2:4]:
            reject('a client reconnected or disconnected during steady warmup')
        if not isinstance(first, list) or not isinstance(last, list) or len(first) != len(COUNTERS) or len(last) != len(COUNTERS):
            reject('invalid measured counter schema')
        if not all(type(v) is int and v >= 0 for v in first + last):
            reject('invalid measured counters')
        if first[2] - first[3] != 1 or last[2] - last[3] != 1 or last[2:4] != first[2:4]:
            reject('client did not maintain one observed connection throughout window')
        delta = [b-a for a,b in zip(first, last)]
        if any(v < 0 for v in delta):
            reject('measured counters reset or overflowed')
        self_sa = delta[0] - delta[4]  # pinned CoT source: sent includes self-SA + ping; missions disabled
        minimum = int((DURATION / INTERVAL) * 0.9)
        if self_sa < minimum or delta[4] < minimum or delta[5] < minimum or delta[1] <= delta[5]:
            reject('a client missed measured self-SA/ping/pong workload fidelity or broadcast progress', 'workload-performance-failed')
        totals = [a+b for a,b in zip(totals, delta)]
    sent, received, connects, disconnects, _ping, pong, latency = totals
    if not sent or not received or not pong:
        reject('no observed measured send/receive/pong traffic')
    return {'duration_s': elapsed, 'counter_source': 'parent-window-delta-v1',
            'messages_sent': sent, 'messages_received': received,
            'connects': connects, 'disconnects': disconnects, 'pong_count': pong,
            'ping_pong_ms_sum': latency, 'ping_pong_ms_mean': latency/pong if pong else None,
            'p95_ms': None, 'observed_stable_clients': CLIENTS,
            'sent_messages_per_s': sent/elapsed, 'self_sa_messages_sent': sent-_ping,
            'observed_self_sa_per_s': (sent-_ping)/elapsed, 'received_messages_per_s': received/elapsed,
            'offered_self_sa_per_s': CLIENTS/INTERVAL,
            'window': value}


def postgres_delta(before, after):
    result = dict(after)
    reset_keys = {'stats_reset_database', 'stats_reset_checkpointer', 'stats_reset_io'}
    if (set(before.get('stats_reset', {})) != reset_keys or set(after.get('stats_reset', {})) != reset_keys
            or before['stats_reset'] != after['stats_reset']):
        raise ValueError('PostgreSQL statistics reset crossed measured window')
    if before['settings'] != after['settings']:
        raise ValueError('PostgreSQL settings changed within measured window')
    for key in DB_COUNTERS:
        a, b = before[key], after[key]
        if not finite(a) or not finite(b) or b < a:
            raise ValueError('PostgreSQL counters reset or unavailable')
        result[key] = b-a
    hits, reads = result['blks_hit'], result['blks_read']
    result['hit_ratio'] = hits/(hits+reads) if hits+reads else None
    result['window_before'] = before
    result['window_after'] = after
    return result


# Inject after the existing helper. Only the parent reads the handshake or
# snapshots shared arrays. Children continue using the same live TLS sessions.
HELPER = '''
import json as _bench_json
_TAK_TESTER_DEADLINE = None
_bench_started = None
_bench_before = None
_bench_start_unix = None
_bench_snapshot_times = {}
_bench_before_times = {}
_bench_clients = {}
_bench_client_error = False
_bench_ready = None
_bench_ready_snapshot = None
_bench_ready_unix = None

def _bench_snapshot():
    global _bench_snapshot_times
    begin = time.monotonic()
    times = {}
    result = {}
    deadline = time.monotonic() + 2
    for uid, arr in list(stats.data.items()):
        lock = arr.get_lock()
        if not lock.acquire(timeout=max(0, deadline-time.monotonic())):
            raise RuntimeError("measured counter lock unavailable")
        try:
            result[str(uid)] = list(arr)
            times[str(uid)] = time.monotonic()
        finally:
            lock.release()
    _bench_snapshot_times = {"begin_monotonic": begin, "end_monotonic": time.monotonic(), "per_uid_monotonic": times}
    return result

def _bench_check_clients(require_all=False):
    global _bench_client_error
    if any(not proc.is_alive() or proc.exitcode is not None for proc in _bench_clients.values()):
        _bench_client_error = True
    if require_all and len(_bench_clients) != 50:
        _bench_client_error = True
    return not _bench_client_error

def _tak_tester_should_stop():
    global _bench_started, _bench_before, _bench_start_unix, _bench_before_times
    global _bench_ready, _bench_ready_snapshot, _bench_ready_unix
    if _TAK_TESTER_STOP:
        return True
    if _tak_os.getpid() != _TAK_TESTER_PARENT:
        return False
    if not _bench_check_clients():
        return True
    if _bench_ready is None and len(_bench_clients) == 50:
        candidate = _bench_snapshot()
        if len(candidate) == 50 and all(row[2]-row[3] == 1 for row in candidate.values()):
            _bench_ready_snapshot = candidate
            _bench_ready = time.monotonic()
            _bench_ready_unix = time.time()
            with open(_tak_os.environ["BENCH_WINDOW_READY"], "x") as stream:
                _bench_json.dump({"ready_unix": _bench_ready_unix}, stream)
    if _bench_ready is not None and time.monotonic()-_bench_ready >= 300 and _bench_started is None and _tak_os.path.isfile(_tak_os.environ["BENCH_WINDOW_GO"]):
        if not _bench_check_clients(require_all=True):
            return True
        _bench_before = _bench_snapshot()
        _bench_before_times = dict(_bench_snapshot_times)
        _bench_started = time.monotonic()
        _bench_start_unix = time.time()
        with open(_tak_os.environ["BENCH_WINDOW_START"], "x") as stream:
            _bench_json.dump({"start_unix": _bench_start_unix}, stream)
    return _bench_started is not None and time.monotonic()-_bench_started >= 1200

def _tak_tester_emit_stats():
    global _TAK_STATS_EMITTED
    if _TAK_STATS_EMITTED or _tak_os.getpid() != _TAK_TESTER_PARENT:
        return
    _TAK_STATS_EMITTED = True
    _bench_check_clients(require_all=True)
    end = time.monotonic()
    after = _bench_snapshot()
    end = time.monotonic()
    value = {"before": _bench_before, "after": after,
             "ready": _bench_ready_snapshot, "ready_monotonic": _bench_ready, "ready_unix": _bench_ready_unix,
             "start_monotonic": _bench_started, "end_monotonic": end,
             "start_unix": _bench_start_unix,
             "end_unix": time.time(), "start_snapshot_times": _bench_before_times,
             "end_snapshot_times": _bench_snapshot_times, "client_error": _bench_client_error}
    print("BENCH_WINDOW_JSON:" + _bench_json.dumps(value), flush=True)
    with open(_tak_os.environ["BENCH_WINDOW_END"], "x") as stream:
        _bench_json.dump({"end_unix": value["end_unix"]}, stream)
'''


def bind(source, anchor):
    if source.count(anchor) != 1:
        raise ValueError('bounded tester helper contract changed')
    # Existing helper is directly after anchor. Append this after the complete
    # existing helper so these optional definitions override its defaults.
    from bench.tester_exit import HELPER as legacy
    needle = anchor + legacy
    if source.count(needle) != 1:
        raise ValueError('bounded tester helper contract changed')
    source = source.replace(needle, needle + HELPER, 1)
    begin = source.index('def test_streaming_cot(')
    end = source.index('def test_udp_wrapper(', begin)
    body = source[begin:end]
    if body.count('            p.start()\n') != 1:
        raise ValueError('CoT client launch contract changed')
    body = body.replace('            p.start()\n', '            p.start()\n            _bench_clients[uid] = p\n')
    return source[:begin] + body + source[end:]
