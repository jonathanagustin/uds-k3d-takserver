#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Build the ffmpeg filter chain for one demo segment.

terminal TAPE DURATION WORKDIR FONT [OFFSET]
    Reads '# caption: text' and '# zoom: ax,ay,factor' lines from the tape
    demo/ragged.py generated. Each applies to the next typed command and
    starts when that command presses Enter. Times come from the tape itself:
    characters x each chunk's typing speed, every Backspace, and every Sleep.
web EVENTS DURATION WORKDIR FONT [OFFSET] [BASE_VIDEO]
    Reads the events.json the Playwright walkthrough writes: zoom, caption,
    and caption-clear events. With BASE_VIDEO, frames where the browser
    shows a blank white page between two pages (a redirect or a page load)
    are replaced with the last frame before them, so the video holds the
    previous page instead of flashing white. Timing does not change.
fit FONT TEXTFILE MAX_SIZE MAX_WIDTH
    Prints the largest font size up to MAX_SIZE at which the text is at most
    MAX_WIDTH pixels wide. The width is measured by rendering it with ffmpeg.

The input segment is the content area, CONTENT_W x CONTENT_H. The chain
zooms that area only (eased in, held, eased out), then pads a caption band
below it so the frame is W x H, and draws captions inside the band. A
caption never covers recorded content.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

FPS = 24
W, H = 1280, 720
CONTENT_W, CONTENT_H = 1280, 630
BAND = H - CONTENT_H
BAND_COLOR = "0x11111b"
# At least 8% of the width stays clear on each side of any text.
TEXT_MAX_W = int(W * 0.84)
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
    settings = Path("demo/settings.tape")
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
        back_match = re.match(r"Backspace(?:@(\S+))?(?:\s+(\d+))?$", line)
        if back_match:
            speed = parse_ms(back_match.group(1)) if back_match.group(1) else default_speed
            t += speed * int(back_match.group(2) or 1)
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
        f"scale={CONTENT_W * 2}:{CONTENT_H * 2}:flags=lanczos,"
        f"zoompan=z='{z}':x='{ax}*(iw-iw/zoom)':y='{ay}*(ih-ih/zoom)'"
        f":d=1:s={CONTENT_W}x{CONTENT_H}:fps={FPS}"
    )


def text_width(font, text_file, size=100):
    """Rendered width in pixels of the text at the given font size."""
    vf = (
        f"drawtext=fontfile={font}:textfile={text_file}:fontsize={size}"
        f":fontcolor=white:x=40:y=40,cropdetect=limit=24:round=2:reset=0"
    )
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "color=black:s=8000x300:d=0.2",
         "-vf", vf, "-frames:v", "3", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    widths = [int(m) for m in re.findall(r"crop=(\d+):", result.stderr)]
    if not widths:
        raise SystemExit(f"could not measure {text_file}")
    return widths[-1]


def fit_size(font, text_file, max_size, max_width):
    width = text_width(font, text_file)
    return max(10, min(max_size, int(100 * max_width / max(width, 1))))


def blank_ranges(video):
    """Frame ranges where nearly every pixel is white (a blank page).

    signalstats YLOW is the 10th percentile of luma. A rendered page has
    text, images, or a dark theme below that line. A blank page does not.
    """
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video, "-vf",
         "signalstats,metadata=print:key=lavfi.signalstats.YLOW:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    frames = []
    frame = None
    for line in result.stdout.splitlines():
        match = re.match(r"frame:(\d+)", line)
        if match:
            frame = int(match.group(1))
            continue
        match = re.search(r"YLOW=([\d.]+)", line)
        if match and frame is not None and float(match.group(1)) >= 230:
            frames.append(frame)
    ranges = []
    for frame in frames:
        if ranges and frame == ranges[-1][1] + 1:
            ranges[-1][1] = frame
        else:
            ranges.append([frame, frame])
    # Frame 0 has nothing before it to hold.
    return [(a, b) for a, b in ranges if a > 0]


def hold_filters(ranges):
    stages = []
    for index, (first, last) in enumerate(ranges):
        source = f"[h{index}]" if index else ""
        out = f"[h{index + 1}]" if index + 1 < len(ranges) else ""
        stages.append(
            f"{source}split[m{index}][r{index}];"
            f"[m{index}][r{index}]freezeframes=first={first}:last={last}:replace={first - 1}{out}"
        )
    return ";".join(stages)


def caption_filter(text_file, start, end, font):
    size = fit_size(font, text_file, 26, TEXT_MAX_W)
    fade = 0.25
    alpha = (
        f"if(lt(t,{start + fade:.3f}),(t-{start:.3f})/{fade},"
        f"if(gt(t,{end - fade:.3f}),({end:.3f}-t)/{fade},1))"
    )
    return (
        f"drawtext=fontfile={font}:textfile={text_file}:fontsize={size}:fontcolor=0xcdd6f4"
        f":x=(w-text_w)/2:y={CONTENT_H}+({BAND}-text_h)/2"
        f":enable='between(t,{start:.3f},{end:.3f})':alpha='{alpha}'"
    )


def main():
    if sys.argv[1] == "fit":
        font, text_file, max_size, max_width = sys.argv[2:6]
        print(fit_size(font, text_file, int(max_size), int(max_width)))
        return
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
    holds = ""
    if mode == "web" and len(sys.argv) > 7:
        ranges = blank_ranges(sys.argv[7])
        for first, last in ranges:
            print(f"holding frame {first - 1} over blank frames {first}-{last}", file=sys.stderr)
        holds = hold_filters(ranges)
    zooms = [e for e in events if e["kind"] == "zoom"]
    if zooms:
        ax, ay, factor = (float(v) for v in str(zooms[0]["value"]).split(","))
        at = min(zooms[0]["at"] + 0.8, max(duration - 2 * EASE - HOLD, 0))
        chain.append(zoom_filter(at, ax, ay, factor))
    # The band is added after the zoom, so the zoom never touches it.
    chain.append(f"pad={W}:{H}:0:0:color={BAND_COLOR}")
    marks = [e for e in events if e["kind"] in ("caption", "caption-clear")]
    stem = Path(source).stem
    for index, event in enumerate(marks):
        if event["kind"] != "caption":
            continue
        start = max(event["at"] + 0.3, 0.0)
        end = marks[index + 1]["at"] if index + 1 < len(marks) else duration
        end = min(end - 0.2, duration - 0.2)
        if end - start < 1.0:
            continue
        text_file = work / f"{stem}-caption-{index}.txt"
        text_file.write_text(event["value"])
        chain.append(caption_filter(text_file, start, end, font))
    print(f"{holds},{','.join(chain)}" if holds else ",".join(chain))


if __name__ == "__main__":
    main()
