# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Split one TAK pod start into pull, init, container start, and Ready.

Times come from the pod status, kubelet events, and a timestamped log line.
A missing input stays None. This module does not read the cluster.
"""

import hashlib
from datetime import datetime

from bench.jvm_metrics import image_digest, Unavailable


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
    seconds = (end - start).total_seconds()
    return round(seconds, 3) if seconds >= 0 else None


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


def pod_phases(pod, events, log_text, container_name=None):
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
    expected = container_name or ((pod.get("spec") or {}).get("containers") or [{}])[0].get("name")
    if expected:
        containers = [status for status in containers if status.get("name") == expected]
    main_started = None
    if containers:
        main_started, _finished = _status_times(containers[0])
    log_at = first_log_time(log_text, ("Started TAK Server", "Tomcat started on port"))
    marker = next((needle for needle in ("Started TAK Server", "Tomcat started on port")
                   if first_log_time(log_text, (needle,)) == log_at), None) if log_at else None
    if main_started is None or (log_at and log_at < main_started):
        log_at = None
        marker = None
    metadata = pod.get("metadata") or {}
    def stamp(value):
        return value.isoformat() if value else None
    result = {
        "evidence": {
            "pod_name": metadata.get("name"), "pod_uid": metadata.get("uid"),
            "container_name": containers[0].get("name") if containers else None,
            "container_id": containers[0].get("containerID") if containers else None,
            "restart_count": containers[0].get("restartCount") if containers else None,
            "container_started_at": stamp(main_started), "startup_log_at": stamp(log_at),
            "startup_log_marker": marker, "ready_at": stamp(ready_at),
            "jvm_started_at": None,
            "jvm_start_limit": "Kubernetes container startedAt is not a JVM start timestamp",
            "init_intervals": [{"name": status.get("name"),
                                "started_at": stamp(_status_times(status)[0]),
                                "finished_at": stamp(_status_times(status)[1])}
                               for status in (pod.get("status") or {}).get("initContainerStatuses") or []],
            "pull_events": [{"uid": event.get("metadata", {}).get("uid"),
                             "reason": event.get("reason"),
                             "container": (event.get("involvedObject") or {}).get("fieldPath"),
                             "at": stamp(_event_time(event))}
                            for event in events or [] if event.get("reason") in ("Pulling", "Pulled")],
        },
        "image_pull_s": _pull_seconds(events),
        "inits": inits,
        "jvm_to_log_s": None,
        "container_to_log_s": elapsed(main_started, log_at),
        "log_to_ready_s": elapsed(log_at, ready_at),
    }
    if container_name:
        try:
            result['evidence']['image_id'] = image_digest(containers[0].get('imageID')) if containers else None
            result['evidence']['image_reference_sha256'] = hashlib.sha256(containers[0]['imageID'].encode()).hexdigest() if containers else None
        except Unavailable:
            result['evidence']['image_id'] = None
    return result
