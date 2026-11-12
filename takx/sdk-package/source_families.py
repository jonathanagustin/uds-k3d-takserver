# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Exact existing Java family replacement; no extra or duplicate FQCN overlays."""
import re

FAMILIES = (
    'com/atakmap/map/EngineLibrary',
    'android/content/res/Resources',
    'com/atakmap/coremap/io/DefaultIOProvider',
    'gov/tak/platform/commons/opengl/GLES20',
)


def members(names):
    return {name for name in names if any(re.fullmatch(re.escape(family) + r'(?:\$[^/]+)?\.class', name) for family in FAMILIES)}


def merge(original, replacement):
    expected = members(original)
    if not expected or set(replacement) != expected:
        raise ValueError('only complete existing reviewed loader/resource/provider/GLES20 families may change')
    if not all(any(name == family + '.class' for name in expected) for family in FAMILIES):
        raise ValueError('original required class family missing')
    result = dict(original)
    result.update(replacement)
    if set(result) != set(original):
        raise ValueError('class inventory changed')
    return result
