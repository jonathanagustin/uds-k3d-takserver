# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Split one TAK pod start into pull, init, JVM, and Ready.

Times come from the pod status, kubelet events, and a timestamped log line.
A missing input stays None. This module does not read the cluster.
"""

from datetime import datetime


def parse_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed(start, end):
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 3)


def first_log_time(text, needles):
    """Timestamp of the first line that contains one of the needles."""
    if not text:
        return None
    for line in text.splitlines():
        if not any(needle in line for needle in needles):
            continue
        stamp = line.split(" ", 1)[0]
        parsed = parse_time(stamp)
        if parsed is not None:
            return parsed
    return None


def _status_times(status):
    state = status.get("state") or {}
    terminated = state.get("terminated") or {}
    running = state.get("running") or {}
    started = parse_time(terminated.get("startedAt") or running.get("startedAt"))
    finished = parse_time(terminated.get("finishedAt"))
    return started, finished


def _event_time(event):
    return parse_time(event.get("eventTime") or event.get("firstTimestamp") or event.get("lastTimestamp"))


def _pull_seconds(events):
    """Seconds the kubelet spent pulling this pod's images.

    Each container's `Pulling` is paired with the next `Pulled` for the same
    container (`involvedObject.fieldPath`), and the pairs are summed, since
    the kubelet pulls one image at a time by default. A `Pulled` with no
    `Pulling` before it is an image that was already present and adds
    nothing. `kubectl get events` does not sort by time, and an init
    container's `Pulled` can come before the main container's `Pulling`,
    so pairing the first of each across the pod gave negative values
    (-61 s on amd64 in Benchmark run 41613491855).
    """
    timed = []
    for event in events or []:
        reason = event.get("reason")
        if reason not in ("Pulling", "Pulled"):
            continue
        stamp = _event_time(event)
        if stamp is None:
            continue
        path = (event.get("involvedObject") or {}).get("fieldPath") or ""
        timed.append((stamp, reason, path))
    timed.sort(key=lambda item: item[0])
    pulling = {}
    total = None
    for stamp, reason, path in timed:
        if reason == "Pulling":
            pulling.setdefault(path, stamp)
            continue
        start = pulling.pop(path, None)
        if start is None:
            continue
        seconds = elapsed(start, stamp)
        total = round((total or 0.0) + seconds, 3)
    return total


def pod_phases(pod, events, log_text):
    """Phase seconds for one pod. None where the status does not say."""
    ready_at = None
    for condition in (pod.get("status") or {}).get("conditions") or []:
        if condition.get("type") == "Ready" and condition.get("status") == "True":
            ready_at = parse_time(condition.get("lastTransitionTime"))
    inits = []
    for status in (pod.get("status") or {}).get("initContainerStatuses") or []:
        started, finished = _status_times(status)
        inits.append({
            "name": status.get("name"),
            "seconds": elapsed(started, finished),
        })
    containers = (pod.get("status") or {}).get("containerStatuses") or []
    main_started = None
    if containers:
        main_started, _finished = _status_times(containers[0])
    log_at = first_log_time(log_text, ("Started TAK Server", "Tomcat started on port"))
    return {
        "image_pull_s": _pull_seconds(events),
        "inits": inits,
        "jvm_to_log_s": elapsed(main_started, log_at),
        "log_to_ready_s": elapsed(log_at, ready_at),
    }
