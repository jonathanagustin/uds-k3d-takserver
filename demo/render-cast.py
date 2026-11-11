#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Turn a recorded script (demo/deploy.sh, demo/after-atak.sh under
asciinema) into captioned clips.

render-cast.py CAST PREFIX "CAPTION::SECONDS" ...

Splits the asciicast at each command prompt the script prints, renders each
command's output with agg, sped up to about SECONDS when it ran longer, and
writes PREFIX-N.mp4 with PREFIX-N-events.json (the caption and the command's
real elapsed time) for demo/assemble.sh. Nothing is retimed except the
playback speed; silent waits are capped at IDLE seconds before the speed-up,
and the caption says how much faster it is shown.
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from media_command import run_media

LEGACY_PROMPT = "uds-takserver\x1b[0m \x1b[38;2;203;213;225m$\x1b[0m "
PROMPT = LEGACY_PROMPT.replace("uds-takserver", "uds-takserver")
IDLE = 2.0
# Short outputs read better large: CAST_FONT_SIZE, CAST_COLS and CAST_ROWS
# override the font size and the terminal size agg renders.
FONT_SIZE = int(os.environ.get("CAST_FONT_SIZE", "22"))
COLS = os.environ.get("CAST_COLS")
ROWS = os.environ.get("CAST_ROWS")
HOLD = os.environ.get("CAST_HOLD", "2.5")
# The demo palette (demo/style.py) as an agg theme: background, foreground,
# then the 16 ANSI colours.
THEME = ",".join(c.lstrip("#") for c in (
    "#0F172A", "#CBD5E1",
    "#020617", "#F8FAFC", "#34D399", "#F8FAFC", "#818CF8", "#818CF8", "#818CF8", "#CBD5E1",
    "#CBD5E1", "#F8FAFC", "#34D399", "#F8FAFC", "#818CF8", "#818CF8", "#818CF8", "#F8FAFC"))

def human(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def main():
    cast, prefix = Path(sys.argv[1]), sys.argv[2]
    captions = []
    for arg in sys.argv[3:]:
        label, _, target = arg.rpartition("::")
        captions.append((label, float(target)))
    agg = "agg"
    lines = cast.read_text().splitlines()
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:] if line.strip()]
    starts = [i for i, e in enumerate(events) if e[1] == "o" and any(prompt in e[2] for prompt in (PROMPT, LEGACY_PROMPT))]
    # The last prompt is the empty one deploy.sh prints when it is done.
    segments = list(zip(starts, starts[1:]))
    if len(segments) != len(captions):
        sys.exit(f"expected {len(captions)} commands in {cast}, found {len(segments)}")
    Path(prefix).parent.mkdir(parents=True, exist_ok=True)
    for n, ((first, end), (label, target)) in enumerate(zip(segments, captions), start=1):
        part = events[first:end]
        t0 = part[0][0]
        real = part[-1][0] - t0
        played, last = 0.0, t0
        for e in part:
            played += min(e[0] - last, IDLE)
            last = e[0]
        speed = max(1.0, played / target)
        seg = Path(f"{prefix}-{n}.cast")
        with seg.open("w") as f:
            f.write(json.dumps(header) + "\n")
            for e in part:
                f.write(json.dumps([round(e[0] - t0, 6), e[1], e[2]]) + "\n")
        gif = Path(f"{prefix}-{n}.gif")
        run_media([agg, "--font-size", str(FONT_SIZE), "--idle-time-limit", str(IDLE),
                        "--speed", f"{speed:.3f}", "--last-frame-duration", HOLD, "--no-loop",
                        *(["--cols", COLS] if COLS else []), *(["--rows", ROWS] if ROWS else []),
                        "--theme", THEME, "--font-family", "JetBrains Mono", str(seg), str(gif)])
        mp4 = Path(f"{prefix}-{n}.mp4")
        run_media(["ffmpeg", "-v", "error", "-y", "-i", str(gif), "-an",
                        "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                        "-c:v", "libx264", "-crf", "16", str(mp4)])
        sped = "" if speed <= 1.05 else f", shown about {math.floor(real / target)}x faster"
        caption = f"{label} (real time {human(real)}{sped})"
        if real < 1:
            caption = label
        Path(f"{prefix}-{n}-events.json").write_text(
            json.dumps([{"kind": "caption", "at": 0, "value": caption}]) + "\n")
        print(f"segment {n}: real {real:.0f}s, played {played:.0f}s, speed {speed:.1f}: {caption}")


if __name__ == "__main__":
    main()
