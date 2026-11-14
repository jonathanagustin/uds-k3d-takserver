#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Find the pinned native Details icon from real pixels, never fixed coordinates.

The OpenGL radial widgets have no UI Automator nodes. The friendly-marker menu
puts Details in its second wedge. Bounds/density constrain that wedge, while the
official icon's foreground AND background must uniquely match before any tap.
No image library, private broadcast, or application-internal access is used.
"""
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import zlib

HERE = Path(__file__).resolve().parent
TEMPLATE_SHA256 = '3e2ea88a8faa5ead60fa4bbdbc38f8c07594d5246a82e0954bc92f8d1b9accf7'
MAX_FRAME_BYTES = 8 * 1024 * 1024


def live_density(payload):
    if len(payload) > 256:
        raise ValueError('unexpected display density output')
    lines = payload.decode('ascii').strip().splitlines()
    values = {}
    for line in lines:
        match = re.fullmatch(r'(Physical|Override) density: ([0-9]{2,3})', line.strip())
        if match is None or match[1] in values:
            raise ValueError('unexpected display density output')
        values[match[1]] = int(match[2])
    if 'Physical' not in values:
        raise ValueError('display density absent')
    dpi = values.get('Override', values['Physical'])
    if not 80 <= dpi <= 640:
        raise ValueError('unsupported display density')
    return dpi


def raw_frame(payload):
    """Android screencap's RGB(A)8888 frame, with 12- or 16-byte header."""
    if not 16 <= len(payload) <= MAX_FRAME_BYTES:
        raise ValueError('raw screenshot size outside bound')
    width, height, pixel_format = struct.unpack_from('<III', payload)
    if not (0 < width <= 4096 and 0 < height <= 4096 and pixel_format in (1, 2)):
        raise ValueError('unsupported raw screenshot shape or format')
    headers = [n for n in (12, 16) if len(payload) == n + width * height * 4]
    if len(headers) != 1:
        raise ValueError('incomplete or ambiguous raw screenshot')
    return width, height, memoryview(payload)[headers[0]:]


def template_alpha(path=HERE / 'details-icon.json'):
    data = path.read_bytes()
    if len(data) > 16 * 1024 or hashlib.sha256(data).hexdigest() != TEMPLATE_SHA256:
        raise ValueError('official Details template identity differs')
    value = json.loads(data)
    if (value['schema'] != 1 or value['width'] != 171 or value['height'] != 171
            or value['source_revision'] != '9f6893dd657feacc35ec5de03dad721c2e44170e'):
        raise ValueError('unsupported official Details template')
    decoder = zlib.decompressobj()
    alpha = decoder.decompress(base64.b64decode(value['alpha_zlib_base64'], validate=True), 171 * 171 + 1)
    if (len(alpha) != 171 * 171 or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail or hashlib.sha256(alpha).hexdigest() != value['alpha_sha256']):
        raise ValueError('official Details alpha differs')
    return alpha


def template_points(alpha, size):
    """Linear texture sampling; ignore uncertain anti-aliased edge pixels."""
    foreground, background = [], []
    for y in range(size):
        sy = (y + .5) * 171 / size - .5
        y0 = max(0, min(170, math.floor(sy)))
        y1, fy = min(170, y0 + 1), sy - math.floor(sy)
        for x in range(size):
            sx = (x + .5) * 171 / size - .5
            x0 = max(0, min(170, math.floor(sx)))
            x1, fx = min(170, x0 + 1), sx - math.floor(sx)
            value = (alpha[y0 * 171 + x0] * (1-fx) * (1-fy)
                     + alpha[y0 * 171 + x1] * fx * (1-fy)
                     + alpha[y1 * 171 + x0] * (1-fx) * fy
                     + alpha[y1 * 171 + x1] * fx * fy)
            if value >= 224:
                foreground.append((x, y))
            elif value <= 16:
                background.append((x, y))
    return foreground, background


def locate_details(payload, viewport, density_output):
    width, height, pixels = raw_frame(payload)
    dpi = live_density(density_output)
    if (len(viewport) != 4 or any(type(v) is not int for v in viewport)
            or not 0 <= viewport[0] < viewport[2] <= width
            or not 0 <= viewport[1] < viewport[3] <= height):
        raise ValueError('map viewport does not fit the live screenshot')
    left, top, right, bottom = viewport
    # AtakMapView initializes relative scaling to max(density / 1.5, 1).
    # a-f.xml: radius65, width90; MapMenuWidget applies width scalar0.76666.
    scale = max(dpi / 240, 1)
    inner, button_width = 65 * scale, 90 * .76666 * scale
    if 2 * (inner + button_width) + 4 > min(right-left, bottom-top):
        raise ValueError('pinned radial geometry does not fit the map viewport')
    center_x, center_y = (left+right)/2, (top+bottom)/2
    rmin, rmax = inner + .2 * button_width, inner + .8 * button_width
    # Second wedge: start -90 + span36 = -54; its full span is36 degrees.
    # Android screenshot Y increases downward, so use positive36..72 here.
    xlo = math.floor(center_x + rmin * math.cos(math.radians(72)))
    xhi = math.ceil(center_x + rmax * math.cos(math.radians(36)))
    ylo = math.floor(center_y + rmin * math.sin(math.radians(36)))
    yhi = math.ceil(center_y + rmax * math.sin(math.radians(72)))
    alpha, candidates, work = template_alpha(), [], 0
    nominal = round(32 * scale)
    for size in (nominal-1, nominal, nominal+1):
        foreground, background = template_points(alpha, size)
        anchors = foreground[::max(1, len(foreground)//8)][:8]
        for cy in range(ylo, yhi+1):
            for cx in range(xlo, xhi+1):
                work += 1
                if work > 150000:
                    raise ValueError('Details visual search budget exceeded')
                radius = math.hypot(cx-center_x, cy-center_y)
                angle = math.degrees(math.atan2(cy-center_y, cx-center_x))
                if not rmin <= radius <= rmax or not 36 <= angle <= 72:
                    continue
                x, y = cx-size//2, cy-size//2
                if x < left or y < top or x+size > right or y+size > bottom:
                    continue

                def lit(px, py):
                    i = ((y+py)*width+x+px)*4
                    return pixels[i] > 110 and pixels[i+1] > 100 and pixels[i+2] > 80

                if sum(lit(px, py) for px, py in anchors) < 7:
                    continue
                yes = sum(lit(px, py) for px, py in foreground) / len(foreground)
                no = sum(not lit(px, py) for px, py in background) / len(background)
                score = (yes+no)/2
                if yes >= .90 and no >= .96 and score >= .95:
                    candidates.append({'x': cx, 'y': cy, 'size': size, 'score': score})
                    if len(candidates) > 128:
                        raise ValueError('ambiguous Details visual matches')
    if not candidates:
        raise LookupError('official Details icon absent from the live wedge')
    # Adjacent raster alignments describe one control; separated matches do not.
    groups = []
    for candidate in sorted(candidates, key=lambda c: c['score'], reverse=True):
        group = next((g for g in groups if any(math.hypot(candidate['x']-p['x'], candidate['y']-p['y'])
                                            <= min(candidate['size'], p['size'])/2 for p in g)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    if len(groups) != 1:
        raise ValueError('ambiguous Details controls in the live wedge')
    best = groups[0][0]
    return {**best, 'density_dpi': dpi, 'viewport': list(viewport)}
