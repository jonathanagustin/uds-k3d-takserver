#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Build the ffmpeg filter chain for one demo segment.

terminal TAPE DURATION WORKDIR
    Reads '# caption: text' and '# zoom: ax,ay,factor' lines from a VHS tape.
    Each applies to the next Type step and starts when that step presses
    Enter. Times come from the tape itself: characters x typing speed plus
    every Sleep.
web EVENTS DURATION WORKDIR
    Reads the events.json the Playwright walkthrough writes. Captions are
    drawn in the page there, so only zoom events are used.

Prints a -vf chain that zooms (eased in, held, eased out) and burns in
lower-third captions.
"""

import json
import re
import sys
from pathlib import Path

FPS = 24
W, H = 1280, 720
EASE = 0.6
HOLD = 2.0


def parse_ms(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", value)
    if not match:
        raise ValueError(f"bad duration {value}")
    number = float(match.group(1))
    return number / 1000 if match.group(2) == "ms" else number


def terminal_events(tape):
    default_speed = 0.075
    settings = Path(tape).parent.parent / "settings.tape"
    for line in settings.read_text().splitlines():
        if line.startswith("Set TypingSpeed"):
            default_speed = parse_ms(line.split()[-1])
    t = 0.0
    shown = False
    pending = []
    events = []
    for raw in Path(tape).read_text().splitlines():
        line = raw.strip()
        if line == "Show":
            shown = True
            continue
        if not shown:
            continue
        if line.startswith("# caption:") or line.startswith("# zoom:"):
            pending.append(line[2:])
            continue
        type_match = re.match(r'Type(?:@(\S+))?\s+"(.*)"$', line)
        if type_match:
            speed = parse_ms(type_match.group(1)) if type_match.group(1) else default_speed
            t += speed * len(type_match.group(2))
            continue
        if line.startswith("Sleep "):
            t += parse_ms(line.split()[1])
            continue
        if line == "Enter":
            for item in pending:
                kind, _, value = item.partition(":")
                events.append({"kind": kind.strip(), "at": t, "value": value.strip()})
            pending = []
    return events


def smooth(p):
    return f"({p})*({p})*(3-2*({p}))"


def zoom_filter(at, ax, ay, factor):
    up = f"clip((it-{at:.3f})/{EASE},0,1)"
    down = f"clip((it-{at + EASE + HOLD:.3f})/{EASE},0,1)"
    z = f"1+{factor - 1:.3f}*({smooth(up)}-{smooth(down)})"
    return (
        f"scale={W * 2}:{H * 2}:flags=lanczos,"
        f"zoompan=z='{z}':x='{ax}*(iw-iw/zoom)':y='{ay}*(ih-ih/zoom)'"
        f":d=1:s={W}x{H}:fps={FPS}"
    )


def caption_filter(text_file, start, end, font):
    fade = 0.25
    alpha = (
        f"if(lt(t,{start + fade:.3f}),(t-{start:.3f})/{fade},"
        f"if(gt(t,{end - fade:.3f}),({end:.3f}-t)/{fade},1))"
    )
    return (
        f"drawtext=fontfile={font}:textfile={text_file}:fontsize=26:fontcolor=0xcdd6f4"
        f":box=1:boxcolor=0x11111b@0.88:boxborderw=16"
        f":x=(w-text_w)/2:y=h-text_h-56"
        f":enable='between(t,{start:.3f},{end:.3f})':alpha='{alpha}'"
    )


def main():
    mode, source, duration, workdir, font = sys.argv[1:6]
    # Seconds trimmed from the start of the source clip.
    offset = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
    duration = float(duration)
    work = Path(workdir)
    if mode == "terminal":
        events = terminal_events(source)
    else:
        events = json.loads(Path(source).read_text())
    for event in events:
        event["at"] = float(event["at"]) - offset
    chain = []
    zooms = [e for e in events if e["kind"] == "zoom"]
    if zooms:
        ax, ay, factor = (float(v) for v in str(zooms[0]["value"]).split(","))
        at = min(zooms[0]["at"] + 0.8, max(duration - 2 * EASE - HOLD, 0))
        chain.append(zoom_filter(at, ax, ay, factor))
    captions = [e for e in events if e["kind"] == "caption"] if mode == "terminal" else []
    stem = Path(source).stem
    for index, event in enumerate(captions):
        start = event["at"] + 0.3
        end = captions[index + 1]["at"] if index + 1 < len(captions) else duration
        end = min(end - 0.2, duration - 0.2)
        if end - start < 1.0:
            continue
        text_file = work / f"{stem}-caption-{index}.txt"
        text_file.write_text(event["value"])
        chain.append(caption_filter(text_file, start, end, font))
    print(",".join(chain) if chain else "null")


if __name__ == "__main__":
    main()
