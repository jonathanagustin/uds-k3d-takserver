# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Shared strict-failure classifier; absence of diagnostics never proves acceptance."""
import re


def strict_jni_failures(text):
    """Return original offending lines, including mixed-case JVM critical warnings."""
    if not isinstance(text, str):
        raise TypeError('complete decoded JNI diagnostics required')
    result = []
    for line in text.splitlines():
        folded = line.casefold()
        severity = re.search(r'\b(?:warning|error|fatal)\b', folded)
        jni_context = any(marker in folded for marker in (
            'jni', 'native method', 'primitivearraycritical', 'stringcritical', 'critical region'))
        startup = any(marker in folded for marker in (
            'unsatisfiedlinkerror', 'noclassdeffounderror', 'enginelibrary: failed to load'))
        if (severity and jni_context) or 'fatal error' in folded or startup:
            result.append(line)
    return result
