# Copyright 2026 uds-k3d-takserver authors
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


def _pull_seconds(events):
    pulling = pulled = None
    for event in events or []:
        reason = event.get("reason")
        stamp = parse_time(event.get("firstTimestamp") or event.get("eventTime"))
        if stamp is None:
            continue
        if reason == "Pulling" and pulling is None:
            pulling = stamp
        elif reason == "Pulled" and pulled is None:
            pulled = stamp
    return elapsed(pulling, pulled)


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
