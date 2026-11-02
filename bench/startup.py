# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment generation and container restarts for a cold TAK install.

A generation of 1 and a restart count of 0 means each Deployment rolled out
once. The harness records both. It does not invent a time when the API
objects are missing.
"""


def max_generation(deployments):
    generations = []
    for item in deployments:
        generation = (item.get("metadata") or {}).get("generation")
        if isinstance(generation, int):
            generations.append(generation)
    if not generations:
        return None
    return max(generations)


def max_restarts(pods):
    counts = []
    for pod in pods:
        statuses = (pod.get("status") or {}).get("containerStatuses") or []
        init_statuses = (pod.get("status") or {}).get("initContainerStatuses") or []
        for status in [*statuses, *init_statuses]:
            count = status.get("restartCount")
            if isinstance(count, int):
                counts.append(count)
    if not counts:
        return None
    return max(counts)
