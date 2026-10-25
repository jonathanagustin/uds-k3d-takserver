#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Bound the upstream load tester so a refused shutdown cannot hang the job.

tak_tester.py loops until KeyboardInterrupt, then join()s its client
processes without stopping them. A SIGTERM starts interpreter shutdown,
which joins those same processes and never returns. The rewrite gives the
loop a deadline, terminates the clients, closes any socket the parent
still holds, and the runner kills the process group if that still sticks.
"""

import os
import signal
import subprocess

HELPER = '''
import os as _tak_os
import signal as _tak_signal

_TAK_TESTER_PARENT = _tak_os.getpid()
_TAK_TESTER_STOP = False
_TAK_TESTER_DEADLINE = None
_raw_duration = _tak_os.environ.get("TAK_TESTER_DURATION", "").strip()
if _raw_duration:
    _TAK_TESTER_DEADLINE = time.time() + float(_raw_duration)

def _tak_tester_on_signal(signum, _frame):
    global _TAK_TESTER_STOP
    if _tak_os.getpid() != _TAK_TESTER_PARENT:
        _tak_signal.signal(signum, _tak_signal.SIG_DFL)
        _tak_os.kill(_tak_os.getpid(), signum)
        return
    _TAK_TESTER_STOP = True

def _tak_tester_should_stop():
    if _TAK_TESTER_STOP:
        return True
    return _TAK_TESTER_DEADLINE is not None and time.time() >= _TAK_TESTER_DEADLINE

def _tak_tester_sleep(seconds):
    end = time.time() + float(seconds)
    while time.time() < end:
        if _tak_tester_should_stop():
            return
        time.sleep(min(0.2, end - time.time()))

def _tak_tester_close(obj):
    for attr in ("sock", "socket", "_sock"):
        held = getattr(obj, attr, None)
        close = getattr(held, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception:
            pass

def _tak_tester_stop_procs(procs):
    for proc in list(procs):
        _tak_tester_close(proc)
        alive = getattr(proc, "is_alive", None)
        if callable(alive) and alive():
            terminate = getattr(proc, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except Exception:
                    pass
        join = getattr(proc, "join", None)
        if callable(join):
            try:
                join(2)
            except TypeError:
                try:
                    join()
                except Exception:
                    pass
            except Exception:
                pass
        if callable(alive) and alive():
            kill = getattr(proc, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception:
                    pass
            if callable(join):
                try:
                    join(1)
                except Exception:
                    pass

_tak_signal.signal(_tak_signal.SIGTERM, _tak_tester_on_signal)
_tak_signal.signal(_tak_signal.SIGINT, _tak_tester_on_signal)
'''

STREAM_LOOP = """    while True:
        try:
            logger.info(print_data_dict(data_dict))
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("trying to kill {} processes".format(len(procs)))
            for p in procs:
                p.join()
            exit(0)
"""

STREAM_LOOP_BOUNDED = """    while not _tak_tester_should_stop():
        try:
            logger.info(print_data_dict(data_dict))
            time.sleep(1)
        except KeyboardInterrupt:
            break
    logger.info("stopping {} clients".format(len(procs)))
    _tak_tester_stop_procs(procs)
"""

TLS_LOOP = """    while True:
        try:
            pass
        except KeyboardInterrupt:
            print("trying to kill {} processes".format(len(procs)))
            for p in procs:
                p.join()
                print(str(p.uid), "is dead")
            exit(0)
"""

TLS_LOOP_BOUNDED = """    while not _tak_tester_should_stop():
        try:
            _tak_tester_sleep(0.5)
        except KeyboardInterrupt:
            break
    print("stopping {} clients".format(len(procs)))
    _tak_tester_stop_procs(procs)
"""

START_JOIN = """            for p in procs:
                p.join()
            exit(0)
"""

START_JOIN_BOUNDED = """            _tak_tester_stop_procs(procs)
            exit(0)
"""

TLS_START_JOIN = """            for p in procs:
                p.join()
                print(str(p.uid), "is dead")
            exit(0)
"""

TLS_START_JOIN_BOUNDED = """            _tak_tester_stop_procs(procs)
            print("clients stopped")
            exit(0)
"""

OFFSET_SLEEP = """            time.sleep(offset)
"""

OFFSET_SLEEP_BOUNDED = """            _tak_tester_sleep(offset)
            if _tak_tester_should_stop():
                break
"""

UDP_LOOP = """    while True:
        try:
            for i in range(num_tracks_per_delta):
"""

UDP_LOOP_BOUNDED = """    while not _tak_tester_should_stop():
        try:
            for i in range(num_tracks_per_delta):
"""

UDP_TAIL = """            time.sleep(track_write_delta)
        except KeyboardInterrupt:
            return
"""

UDP_TAIL_BOUNDED = """            time.sleep(track_write_delta)
            if _tak_tester_should_stop():
                break
        except KeyboardInterrupt:
            break
    sock.close()
"""

TCP_LOOP = """        while True:
            if track_points:
"""

TCP_LOOP_BOUNDED = """        while not _tak_tester_should_stop():
            if track_points:
"""

ANCHOR = "from create_proto import CotProtoMessage, get_msg_size\n"


def _replace(source, old, new, expected, label):
    found = source.count(old)
    if found != expected:
        raise RuntimeError(f"{label} appeared {found} times, expected {expected}")
    return source.replace(old, new)


def bind_tester(source):
    """Return tak_tester.py source that stops at TAK_TESTER_DURATION."""
    if "_tak_tester_stop_procs" in source:
        return source
    if ANCHOR not in source:
        raise RuntimeError("tak_tester.py is missing the create_proto import")
    source = source.replace(ANCHOR, ANCHOR + HELPER, 1)
    source = _replace(source, STREAM_LOOP, STREAM_LOOP_BOUNDED, 3, "streaming loop")
    source = _replace(source, TLS_LOOP, TLS_LOOP_BOUNDED, 1, "tls loop")
    source = _replace(source, START_JOIN, START_JOIN_BOUNDED, 3, "startup join")
    source = _replace(source, TLS_START_JOIN, TLS_START_JOIN_BOUNDED, 1, "tls startup join")
    source = _replace(source, OFFSET_SLEEP, OFFSET_SLEEP_BOUNDED, 4, "client offset sleep")
    source = _replace(source, UDP_LOOP, UDP_LOOP_BOUNDED, 1, "udp loop head")
    source = _replace(source, UDP_TAIL, UDP_TAIL_BOUNDED, 1, "udp loop")
    source = _replace(source, TCP_LOOP, TCP_LOOP_BOUNDED, 1, "tcp loop")
    return source


def kill_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return False
    return True


def reap(proc, timeout):
    """Wait for proc. After timeout, SIGTERM the group, then SIGKILL."""
    try:
        stdout, _stderr = proc.communicate(timeout=timeout)
        return stdout or ""
    except subprocess.TimeoutExpired as expired:
        partial = expired.stdout or ""
        kill_group(proc.pid, signal.SIGTERM)
        try:
            rest, _stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired as again:
            partial += again.stdout or ""
            kill_group(proc.pid, signal.SIGKILL)
            rest, _stderr = proc.communicate(timeout=5)
        return partial + (rest or "")
